from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "verify_deployment_configs.py"
SPEC = importlib.util.spec_from_file_location("verify_deployment_configs", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def test_every_fixed_safe_default_is_pinned_fail_closed() -> None:
    assert verifier.fixed_safe_default_errors(dict(verifier.EXPECTED_FIXED_SAFE_DEFAULTS)) == []
    for key in verifier.EXPECTED_FIXED_SAFE_DEFAULTS:
        drifted = dict(verifier.EXPECTED_FIXED_SAFE_DEFAULTS)
        drifted[key] = "unsafe-drift"
        assert any(key in error for error in verifier.fixed_safe_default_errors(drifted))


def test_fixed_safe_defaults_reject_missing_and_unexpected_fields() -> None:
    missing = dict(verifier.EXPECTED_FIXED_SAFE_DEFAULTS)
    missing.pop("APP_ENV")
    assert any("APP_ENV" in error for error in verifier.fixed_safe_default_errors(missing))

    unexpected = {**verifier.EXPECTED_FIXED_SAFE_DEFAULTS, "UNREVIEWED_FLAG": "true"}
    assert any("UNREVIEWED_FLAG" in error for error in verifier.fixed_safe_default_errors(unexpected))


@pytest.fixture
def web_files():
    return ((ROOT / "frontend/nginx.conf.template").read_text(), (ROOT / "frontend/Dockerfile").read_text())


def test_current_web_files_have_active_required_directives(web_files):
    assert verifier.web_file_errors(*web_files) == []


@pytest.mark.parametrize("directive", [
    "listen ${PORT};", 'set $api_upstream "${API_UPSTREAM}";',
    "proxy_pass $api_upstream;", "resolver ${NGINX_LOCAL_RESOLVERS} valid=10s ipv6=on;",
])
def test_commented_nginx_directive_cannot_satisfy_deployment_gate(web_files, directive):
    nginx, dockerfile = web_files
    assert verifier.web_file_errors(nginx.replace(directive, "# " + directive), dockerfile)


def test_quoted_text_and_unrelated_locations_cannot_supply_the_api_proxy(web_files):
    nginx, dockerfile = web_files
    nginx = nginx.replace("proxy_pass $api_upstream;", 'add_header X-Example "proxy_pass $api_upstream;";')
    nginx = nginx.replace("location /assets/ {", "location /assets/ {\n    proxy_pass $api_upstream;")
    assert any("/api/" in error for error in verifier.web_file_errors(nginx, dockerfile))


def test_location_cannot_override_the_server_private_origin(web_files):
    nginx, dockerfile = web_files
    nginx = nginx.replace("location /api/ {", 'location /api/ {\n    set $api_upstream "http://wrong-origin";')
    assert any("retain the server" in error for error in verifier.web_file_errors(nginx, dockerfile))


def test_build_stage_values_do_not_configure_the_runtime_image(web_files):
    nginx, dockerfile = web_files
    first, runtime = dockerfile.split("FROM nginx:", 1)
    start = runtime.index("ENV PORT=80")
    end = runtime.index("\n\n", start)
    env = runtime[start:end]
    runtime = runtime[:start] + runtime[end:]
    changed = first + env + "\n\nFROM nginx:" + runtime
    errors = verifier.web_file_errors(nginx, changed)
    assert any("local resolvers" in error for error in errors)
    assert any("allowlist" in error for error in errors)


def test_later_docker_env_override_and_wrong_copy_destination_fail(web_files):
    nginx, dockerfile = web_files
    changed = dockerfile + '\nENV NGINX_ENVSUBST_FILTER=".*"\n'
    assert any("allowlist" in error for error in verifier.web_file_errors(nginx, changed))
    assert any("allowlist" in error for error in verifier.web_file_errors(nginx, changed.replace("ENV NGINX_ENVSUBST_FILTER", "ENV\tNGINX_ENVSUBST_FILTER")))
    changed = dockerfile.replace("COPY nginx.conf.template /etc/nginx/templates/default.conf.template",
                                 "# COPY nginx.conf.template /etc/nginx/templates/default.conf.template\nCOPY nginx.conf.template /tmp/unused-template")
    assert any("active path" in error for error in verifier.web_file_errors(nginx, changed))


@pytest.mark.parametrize("correct_web", [False, True])
def test_native_compose_parser_checks_web_settings_not_comments_or_other_services(tmp_path, correct_web):
    expected = {"PORT": "80", "API_UPSTREAM": "${API_UPSTREAM:-http://api:9247}"}
    config = {"services": {
        "api": {"image": "fixture-api", "environment": expected},
        "web": {"image": "fixture-web", "env_file": [".env"],
                "environment": expected if correct_web else {"PORT": "90", "API_UPSTREAM": "http://wrong-origin"}},
    }}
    (tmp_path / "docker-compose.yml").write_text("# - PORT=80\n# API_UPSTREAM=${API_UPSTREAM:-http://api:9247}\n" + json.dumps(config))
    (tmp_path / "env.sample").write_text("PORT=1234\n")
    (tmp_path / ".env").write_text("PORT=9999\nAPI_UPSTREAM=http://private-env-fixture\n")
    errors = verifier.compose_file_errors(tmp_path)
    if correct_web:
        assert errors == []
    else:
        assert len(errors) == 2


def test_commented_sample_key_does_not_satisfy_main_gate(tmp_path, monkeypatch, capsys, web_files):
    configs = {path: verifier.load_json(path) for path in ["backend/railway.json", "backend/railway.worker.json", "backend/railway.expiry.json", "frontend/railway.json", "deploy/railway/template-spec.json"]}
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/nginx.conf.template").write_text(web_files[0])
    (tmp_path / "frontend/Dockerfile").write_text(web_files[1])
    migration = tmp_path / "backend/alembic/versions/0016_service_heartbeats.py"
    migration.parent.mkdir(parents=True)
    migration.touch()
    (tmp_path / "env.sample").write_text((ROOT / "env.sample").read_text().replace("APP_ENV=", "# APP_ENV="))
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "load_json", configs.__getitem__)
    monkeypatch.setattr(verifier, "compose_file_errors", lambda _root: [])
    assert verifier.main() == 1
    assert "env.sample: missing APP_ENV" in capsys.readouterr().out
