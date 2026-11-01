from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "source_binding.py"
SPEC = importlib.util.spec_from_file_location("source_binding_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
binding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binding)


def test_source_binding_requires_exact_https_path_revision() -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    assert binding.source_url_names_revision(
        "https://github.com/example/node/tree/0123456789abcdef0123456789abcdef01234567",
        revision,
    )
    assert not binding.source_url_names_revision(
        "https://github.com/example/node/tree/0123456789abcdef0123456789abcdef012345670-not-the-release",
        revision,
    )
    assert not binding.source_url_names_revision(
        "https://github.com/example/node?revision=0123456789abcdef0123456789abcdef01234567",
        revision,
    )
    assert not binding.source_url_names_revision(
        "https:///tree/0123456789abcdef0123456789abcdef01234567",
        revision,
    )


def test_moving_or_malformed_revisions_are_rejected() -> None:
    for revision in ("main", "latest", "development", "../release", "short", "production", "release-branch", "v1.0.0", "abcdef0"):
        assert not binding.valid_immutable_revision(revision)
