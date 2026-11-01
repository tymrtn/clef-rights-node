import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError


SPEC = importlib.util.spec_from_file_location(
    "workflow_database_verifier",
    Path(__file__).resolve().parents[2] / "scripts/verify_rightsholder_workflow.py",
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


@pytest.mark.parametrize("matches", [None, {}, {"artist_credit": True}, {"artist_credit": True, "clef_license": False}, {"artist_credit": True, "clef_license": "true"}, []])
def test_publication_verifier_rejects_missing_or_partial_metadata_comparisons(matches):
    with pytest.raises(verifier.WorkflowFailure, match="every required metadata"):
        verifier.require_metadata_checks({"metadataExactMatches": matches}, {"artist_credit": "Example Artist", "clef_license": "Synthetic license"})


def test_publication_verifier_accepts_complete_exact_metadata():
    verifier.require_metadata_checks({"metadataExactMatches": {"artist_credit": True, "clef_license": True}}, {"artist_credit": "Example Artist", "clef_license": "Synthetic license"})


@pytest.mark.parametrize("missing", ["permission_request.created", "permission_request.approved"])
def test_audit_verifier_rejects_missing_required_action_even_with_extra_actions(missing):
    events = [{"action": action, "actor": {"credentialId": "authority-credential"}} for action in ["permission_request.created", "permission_request.approved", "permission_request.disputed"] if action != missing]
    with pytest.raises(verifier.WorkflowFailure, match="machine permission transaction"):
        verifier.require_permission_audit(events, "authority-credential")


def test_audit_verifier_requires_the_approval_actor_on_the_approval_event():
    events = [{"action": "permission_request.created", "actor": {"credentialId": "authority-credential"}}, {"action": "permission_request.approved", "actor": {"credentialId": "different-credential"}}]
    with pytest.raises(verifier.WorkflowFailure, match="rightsholder machine actor"):
        verifier.require_permission_audit(events, "authority-credential")
    events[1]["actor"]["credentialId"] = "authority-credential"
    verifier.require_permission_audit(events, "authority-credential")
@pytest.mark.parametrize("url", ["", "sqlite:///:memory:", "postgresql+psycopg2://localhost", "not-a-url"])
def test_postgres_preflight_rejects_invalid_or_wrong_database_targets(url):
    with pytest.raises(verifier.WorkflowFailure):
        verifier.require_empty_postgres(url)


def test_failed_postgres_preflight_preserves_existing_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "original-environment-sentinel")
    called = []
    monkeypatch.setattr(verifier, "configure_environment", lambda *_args, **_kwargs: called.append(True))
    with pytest.raises(verifier.WorkflowFailure):
        verifier.run_workflow(tmp_path / "fallback.db", "fixture", {}, database_url="sqlite:///:memory:")
    assert called == []
    assert not (tmp_path / "fallback.db").exists()


def test_postgres_preflight_reports_connection_failure_without_secret(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OperationalError("fixture", {}, Exception("private-database-password"))

    monkeypatch.setattr("sqlalchemy.create_engine", fail)
    with pytest.raises(verifier.WorkflowFailure) as failure:
        verifier.require_empty_postgres("postgresql+psycopg2://user:private-database-password@localhost/workflow")
    assert "private-database-password" not in str(failure.value)
    assert "check its URL and access" in str(failure.value)
