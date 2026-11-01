from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_release.py"
SPEC = importlib.util.spec_from_file_location("verify_release", MODULE_PATH)
assert SPEC and SPEC.loader
verify_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_release)


def test_source_url_must_name_the_full_commit_and_reject_tags_and_abbreviations() -> None:
    assert not verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node/tree/v0.2.0-alpha",
        "v0.2.0-alpha",
    )
    assert not verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node/tree/0123456789abcdef",
        "0123456789abcdef",
    )
    assert verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node/tree/0123456789abcdef0123456789abcdef01234567",
        "0123456789abcdef0123456789abcdef01234567",
    )
    assert not verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node",
        "v0.2.0-alpha",
    )
    assert not verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node/tree/v0.2.0-alpha.1-not-the-release",
        "v0.2.0-alpha.1",
    )
    assert not verify_release.source_url_contains_revision(
        "https://github.com/tymrtn/clef-rights-node?revision=v0.2.0-alpha",
        "v0.2.0-alpha",
    )


def test_release_target_requires_public_source_reachability() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("verify-release:", 1)[1].split("\n\n", 1)[0]
    assert "--require-source-reachable" in target
