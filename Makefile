.PHONY: up down reset logs seed test test-local install-ddex-schemas verify-ddex verify-workflow verify-real-pilot verify-deployment verify-public verify-alpha verify-running verify-release expire-due deliver-webhooks build build-backend build-frontend

DC=docker compose
DDEX_SCHEMA_DIR?=var/ddex/mwl-1.0.1

up:
	$(DC) up --build

down:
	$(DC) down

reset:
	$(DC) down -v

logs:
	$(DC) logs -f

seed:
	$(DC) run --rm api python seed.py --fixtures /app/fixtures/sample_catalog.json

test:
	$(DC) run --build --rm api pytest -q

test-local:
	cd backend && PYTHONPATH=. ../.venv/bin/python -m pytest -q

install-ddex-schemas:
	.venv/bin/python scripts/verify_ddex_mwl.py --install-dir "$(DDEX_SCHEMA_DIR)"

verify-ddex:
	.venv/bin/python scripts/verify_ddex_mwl.py

verify-workflow:
	.venv/bin/python scripts/verify_rightsholder_workflow.py

verify-real-pilot:
	@test -n "$(PILOT_MANIFEST)" || (echo "Set PILOT_MANIFEST to the completed pilot manifest" >&2; exit 2)
	.venv/bin/python scripts/verify_real_pilot.py --manifest "$(PILOT_MANIFEST)" $(if $(PILOT_REPORT),--output "$(PILOT_REPORT)",)

verify-deployment:
	.venv/bin/python scripts/verify_deployment_configs.py

verify-public:
	.venv/bin/python scripts/verify_public_repository.py

verify-alpha: test-local
	cd frontend && npm run build
	$(MAKE) verify-workflow
	$(MAKE) verify-ddex
	$(MAKE) verify-deployment
	$(MAKE) verify-public
	git diff --check

verify-running:
	.venv/bin/python scripts/verify_deployment.py

verify-release:
	@test -n "$(API_URL)" || (echo "Set API_URL to the deployed node" >&2; exit 2)
	@test -n "$(SOURCE_REVISION)" || (echo "Set SOURCE_REVISION to the immutable deployed revision" >&2; exit 2)
	.venv/bin/python scripts/verify_release.py --api-url "$(API_URL)" --expected-revision "$(SOURCE_REVISION)" --require-clean --require-source-reachable

expire-due:
	$(DC) exec -T api python expire_permissions.py

deliver-webhooks:
	$(DC) exec -T api python webhook_worker.py --once

build: build-backend build-frontend

build-backend:
	$(DC) build api

build-frontend:
	$(DC) build web
