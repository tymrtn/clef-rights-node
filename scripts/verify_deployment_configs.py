#!/usr/bin/env python3
"""Fail closed when the checked-in production deployment topology drifts."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "https://railway.com/railway.schema.json"


def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid deployment config {relative_path}: {error}") from error


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    configs = {
        "api": load_json("backend/railway.json"),
        "webhook-worker": load_json("backend/railway.worker.json"),
        "expiry-worker": load_json("backend/railway.expiry.json"),
        "web": load_json("frontend/railway.json"),
    }

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

    nginx_template = (ROOT / "frontend/nginx.conf.template").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    require("listen ${PORT};" in nginx_template, "web: nginx must listen on Railway's runtime port", errors)
    require(
        'set $api_upstream "${API_UPSTREAM}";' in nginx_template
        and "proxy_pass $api_upstream;" in nginx_template,
        "web: API proxy must use the configured private origin",
        errors,
    )
    require(
        "resolver ${NGINX_LOCAL_RESOLVERS} valid=10s" in nginx_template
        and "NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1" in frontend_dockerfile,
        "web: private service DNS must be refreshed after API replacements",
        errors,
    )
    require("NGINX_ENVSUBST_FILTER" in frontend_dockerfile, "web: nginx substitution must be allowlisted", errors)
    require("nginx.conf.template" in frontend_dockerfile, "web: runtime nginx template is not installed", errors)

    sample = (ROOT / "env.sample").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    require("container_name:" not in compose, "compose: fixed global container names break parallel deployments", errors)
    require("- PORT=80" in compose, "compose: web must override the API port inherited from .env", errors)
    require("API_UPSTREAM=${API_UPSTREAM:-http://api:9247}" in compose, "compose: web must proxy to the Compose API service", errors)
    for key in (
        "APP_ENV",
        "DATABASE_URL",
        "RIGHTS_MAGIC_LINK_SECRET",
        "NODE_SIGNING_PRIVATE_KEY_B64",
        "SOURCE_CODE_URL",
        "SOURCE_CODE_REVISION",
        "WEBHOOK_ENCRYPTION_KEY_B64",
        "API_UPSTREAM",
    ):
        require(f"{key}=" in sample, f"env.sample: missing {key}", errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("deployment config: valid (api, web, webhook worker, expiry worker)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
