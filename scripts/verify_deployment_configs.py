#!/usr/bin/env python3
"""Fail closed when the checked-in production deployment topology drifts."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "https://railway.com/railway.schema.json"
EXPECTED_FIXED_SAFE_DEFAULTS = {
    "APP_ENV": "staging",
    "NODE_DEPLOYMENT_MODE": "adopter_staging",
    "AUTH_SIGNUP_MODE": "operator_only",
    "NOTIFICATION_PROVIDER": "smtp",
    "ALLOW_DEV_IDENTITY_HEADERS": "false",
    "ALLOW_DEV_MAGIC_LINKS": "false",
    "MLC_ENABLED": "false",
    "DDEX_ENABLED": "false",
    "DDEX_LIVE_MESSAGES": "false",
    "MUSICBRAINZ_ENABLED": "false",
    "WEBHOOK_ALLOW_PRIVATE_TARGETS": "false",
}


def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid deployment config {relative_path}: {error}") from error


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def fixed_safe_default_errors(fixed: object) -> list[str]:
    if not isinstance(fixed, dict):
        return ["template: fixedSafeDefaults must be an object"]
    errors = [
        f"template: {key} must default to {expected}"
        for key, expected in EXPECTED_FIXED_SAFE_DEFAULTS.items()
        if fixed.get(key) != expected
    ]
    unexpected = sorted(set(fixed) - set(EXPECTED_FIXED_SAFE_DEFAULTS))
    if unexpected:
        errors.append(f"template: unexpected fixedSafeDefaults: {', '.join(unexpected)}")
    return errors


def nginx_nodes(text: str) -> list[dict]:
    # Protect envsubst placeholders from nginx's block delimiters before lexing.
    prefix = "CLEF_ENV_"
    while prefix in text:
        prefix += "_"
    placeholders = {}
    def protect(match):
        marker = f"{prefix}{len(placeholders)}_"
        placeholders[marker] = match[0]
        return marker
    text = re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", protect, text)
    lexer = shlex.shlex(text, posix=True, punctuation_chars="{};")
    lexer.whitespace_split = True
    def restored_tokens():
        for token in lexer:
            for marker, original in placeholders.items():
                token = token.replace(marker, original)
            if re.fullmatch(r"[{};]+", token):
                yield from token
            else:
                yield token
    tokens = iter(restored_tokens())
    def parse(nested=False):
        nodes, words = [], []
        for token in tokens:
            if token == "}":
                if words or not nested:
                    raise ValueError("unexpected nginx block end")
                return nodes
            if token == "{":
                if not words:
                    raise ValueError("nginx block has no name")
                nodes.append({"words": words, "children": parse(True)})
                words = []
            elif token == ";":
                if not words:
                    raise ValueError("nginx directive has no name")
                nodes.append({"words": words, "children": None})
                words = []
            else:
                words.append(token)
        if words or nested:
            raise ValueError("incomplete nginx configuration")
        return nodes
    return parse()


def directives(nodes: list[dict], name: str) -> list[list[str]]:
    return [node["words"][1:] for node in nodes if node["children"] is None and node["words"][0] == name]


def runtime_docker_settings(text: str) -> tuple[dict[str, str], list[list[str]]]:
    environment, copies, pending = {}, [], ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pending += line.strip()
        if pending.endswith("\\"):
            pending = pending[:-1] + " "
            continue
        pieces = pending.split(None, 1)
        instruction, body = pieces[0], pieces[1] if len(pieces) == 2 else ""
        pending = ""
        instruction = instruction.upper()
        if instruction == "FROM":
            environment, copies = {}, []
        elif instruction == "ENV":
            words = shlex.split(body)
            if not words:
                raise ValueError("empty Docker ENV instruction")
            if "=" not in words[0]:
                if len(words) < 2:
                    raise ValueError("missing Docker ENV value")
                environment[words[0]] = " ".join(words[1:])
            else:
                for word in words:
                    if "=" not in word:
                        raise ValueError("invalid Docker ENV assignment")
                    key, value = word.split("=", 1)
                    environment[key] = value
        elif instruction == "COPY":
            copies.append(json.loads(body) if body.lstrip().startswith("[") else shlex.split(body))
    if pending:
        raise ValueError("incomplete Docker instruction")
    return environment, copies


def web_file_errors(nginx: str, dockerfile: str) -> list[str]:
    errors = []
    try:
        nodes = nginx_nodes(nginx)
        servers = [node for node in nodes if node["words"] == ["server"] and node["children"] is not None]
        require(len(servers) == 1, "web: exactly one active nginx server is required", errors)
        server = servers[0]["children"] if len(servers) == 1 else []
        require(directives(server, "listen") == [["${PORT}"]], "web: nginx must listen on Railway's runtime port", errors)
        sets = [row for row in directives(server, "set") if row and row[0] == "$api_upstream"]
        require(sets == [["$api_upstream", "${API_UPSTREAM}"]], "web: API origin must be set on the active server", errors)
        locations = [node for node in server if node["words"] == ["location", "/api/"] and node["children"] is not None]
        api = locations[0]["children"] if len(locations) == 1 else []
        require(len(locations) == 1 and directives(api, "proxy_pass") == [["$api_upstream"]], "web: /api/ must proxy to the configured private origin", errors)
        require(not any(row and row[0] == "$api_upstream" for row in directives(api, "set")), "web: API location must retain the server's origin", errors)
        require(directives(server, "resolver") == [["${NGINX_LOCAL_RESOLVERS}", "valid=10s", "ipv6=on"]], "web: private service DNS must be refreshed after API replacements", errors)
        environment, copies = runtime_docker_settings(dockerfile)
        require(environment.get("NGINX_ENTRYPOINT_LOCAL_RESOLVERS") == "1", "web: runtime image must enable local resolvers", errors)
        require(environment.get("NGINX_ENVSUBST_FILTER") == "^(PORT|API_UPSTREAM|NGINX_LOCAL_RESOLVERS)$", "web: runtime nginx substitution must use the exact allowlist", errors)
        require(["nginx.conf.template", "/etc/nginx/templates/default.conf.template"] in copies, "web: runtime nginx template must be installed at its active path", errors)
    except (ValueError, TypeError, KeyError):
        errors.append("web: could not parse the deployment directives")
    return errors


def compose_file_errors(root: Path) -> list[str]:
    try:
        result = subprocess.run([
            "docker", "compose", "--project-directory", str(root), "--env-file", str(root / "env.sample"),
            "-f", str(root / "docker-compose.yml"), "config", "--format", "json", "--no-interpolate", "--no-env-resolution",
        ], check=True, capture_output=True, text=True, timeout=30)
        services = json.loads(result.stdout)["services"]
        environment = services.get("web", {}).get("environment", {})
        if isinstance(environment, list):
            environment = dict(item.split("=", 1) for item in environment if "=" in item)
        errors = []
        require(not any("container_name" in service for service in services.values()), "compose: fixed global container names break parallel deployments", errors)
        require(str(environment.get("PORT")) == "80", "compose: web must override the API port inherited from .env", errors)
        require(environment.get("API_UPSTREAM") == "${API_UPSTREAM:-http://api:9247}", "compose: web must proxy to the Compose API service", errors)
        return errors
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return ["compose: install Docker Compose with JSON config and --no-env-resolution support, and check the deployment file"]


def main() -> int:
    errors: list[str] = []
    configs = {
        "api": load_json("backend/railway.json"),
        "webhook-worker": load_json("backend/railway.worker.json"),
        "expiry-worker": load_json("backend/railway.expiry.json"),
        "web": load_json("frontend/railway.json"),
    }
    template = load_json("deploy/railway/template-spec.json")

    for name, config in configs.items():
        require(config.get("$schema") == SCHEMA, f"{name}: current Railway schema is required", errors)
        build = config.get("build", {})
        require(build.get("builder") == "DOCKERFILE", f"{name}: Dockerfile builder is required", errors)
        require(build.get("dockerfilePath") == "Dockerfile", f"{name}: Dockerfile path drifted", errors)

    api_deploy = configs["api"].get("deploy", {})
    require(api_deploy.get("preDeployCommand") == "alembic upgrade head", "api: migrations must run before deploy", errors)
    require(api_deploy.get("healthcheckPath") == "/health", "api: healthcheck must use /health", errors)
    require("startCommand" not in api_deploy, "api: Dockerfile CMD must remain the startup authority", errors)

    require(
        configs["webhook-worker"].get("deploy", {}).get("startCommand") == "python webhook_worker.py",
        "webhook-worker: incorrect start command",
        errors,
    )
    require(
        configs["expiry-worker"].get("deploy", {}).get("startCommand") == "python expiry_worker.py",
        "expiry-worker: incorrect start command",
        errors,
    )
    require(template.get("schemaVersion") == "clef.railway-template.v1", "template: schema version drifted", errors)
    require(template.get("ownership") == "adopter", "template: adopter ownership must be explicit", errors)
    template_services = {row.get("name"): row for row in template.get("services", [])}
    require(set(template_services) == {"Postgres", "api", "webhook-worker", "expiry-worker", "web"}, "template: five-service topology drifted", errors)
    require(template_services.get("web", {}).get("public") is True, "template: web must be public", errors)
    require(
        all(not row.get("public") for name, row in template_services.items() if name != "web"),
        "template: only web may be public",
        errors,
    )
    require(template_services.get("expiry-worker", {}).get("singleton") is True, "template: expiry worker must be a singleton", errors)
    require(
        template.get("referenceVariables", {}).get("DATABASE_URL") == "${{Postgres.DATABASE_URL}}",
        "template: database must use an adopter-owned Railway reference",
        errors,
    )
    composer = template.get("composerVariables", {})
    generated = composer.get("generatedInAdopterProject", {})
    require(
        generated.get("RIGHTS_MAGIC_LINK_SECRET") == "${{secret(64)}}",
        "template: magic-link secret must be generated in the adopter project",
        errors,
    )
    base64_secret = '${{secret(43, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/")}}='
    for key in ("NODE_SIGNING_PRIVATE_KEY_B64", "WEBHOOK_ENCRYPTION_KEY_B64"):
        require(generated.get(key) == base64_secret, f"template: {key} must be an adopter-generated 32-byte base64 secret", errors)
    adopter_inputs = set(composer.get("requiredAdopterInputs", []))
    require(
        {"NODE_OPERATOR_EMAILS", "NOTIFICATION_FROM_EMAIL", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_SECURITY"} <= adopter_inputs,
        "template: adopter SMTP identity and credentials must be explicit inputs",
        errors,
    )
    require(
        set(composer.get("requiredPublisherBindings", [])) == {"SOURCE_CODE_REVISION", "SOURCE_CODE_URL"},
        "template: publisher must bind the exact public source revision before reproduction",
        errors,
    )
    derived = composer.get("derivedInProject", {})
    require(derived.get("DATABASE_URL") == "${{Postgres.DATABASE_URL}}", "template: database reference drifted", errors)
    require(
        derived.get("NODE_ID") == "urn:clef:rights-node:${{RAILWAY_PROJECT_ID}}",
        "template: node identity must derive from the adopter-owned Railway project",
        errors,
    )
    require(
        derived.get("CONSOLE_BASE_URL") == "https://${{web.RAILWAY_PUBLIC_DOMAIN}}"
        and derived.get("CORS_ALLOW_ORIGINS") == "https://${{web.RAILWAY_PUBLIC_DOMAIN}}",
        "template: console and CORS origins must derive from the adopter web domain",
        errors,
    )
    require(
        derived.get("API_UPSTREAM") == "http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}",
        "template: web must derive its API origin from Railway private networking",
        errors,
    )
    fixed = composer.get("fixedSafeDefaults", {})
    errors.extend(fixed_safe_default_errors(fixed))

    nginx_template = (ROOT / "frontend/nginx.conf.template").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    errors.extend(web_file_errors(nginx_template, frontend_dockerfile))
    errors.extend(compose_file_errors(ROOT))
    sample = (ROOT / "env.sample").read_text(encoding="utf-8")
    sample_keys = set(re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]*)=", sample))
    for key in (
        "APP_ENV",
        "DATABASE_URL",
        "RIGHTS_MAGIC_LINK_SECRET",
        "NOTIFICATION_PROVIDER",
        "NOTIFICATION_FROM_EMAIL",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "NODE_SIGNING_PRIVATE_KEY_B64",
        "SOURCE_CODE_URL",
        "SOURCE_CODE_REVISION",
        "WEBHOOK_ENCRYPTION_KEY_B64",
        "API_UPSTREAM",
    ):
        require(key in sample_keys, f"env.sample: missing {key}", errors)
    require(
        (ROOT / "backend/alembic/versions/0016_service_heartbeats.py").is_file(),
        "deployment: database-backed worker heartbeat migration is missing",
        errors,
    )

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("deployment config: valid (api, web, webhook worker, expiry worker)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
