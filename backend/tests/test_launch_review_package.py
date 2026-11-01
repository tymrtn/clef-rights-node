"""A review package must preserve source provenance and reject unsafe contents."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import prepare_launch_review as package


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "README.md").write_text("Synthetic review fixture\n")
    return root


def test_package_rejects_private_evidence_and_symlinks(source, tmp_path):
    evidence = source / "agreement.pdf"
    evidence.write_bytes(b"Private fixture")
    with pytest.raises(package.PackageError, match="private artifact"):
        package.collect(source)
    evidence.unlink()
    target = tmp_path / "outside.txt"
    target.write_text("outside source boundary")
    (source / "linked.txt").symlink_to(target)
    with pytest.raises(package.PackageError, match="symlinks"):
        package.collect(source)


def test_package_rejects_secrets_without_echoing_value(source):
    value = "ghp_" + "q" * 36
    (source / "config.txt").write_text(value)
    with pytest.raises(package.PackageError) as error:
        package.collect(source)
    assert value not in str(error.value)
    assert "github-token" in str(error.value)


def test_file_content_and_executable_bit_are_part_of_source_identity(source):
    before = package.collect(source)
    (source / "README.md").chmod(0o755)
    with pytest.raises(package.PackageError, match="Source changed"):
        package.require_unchanged(before, package.collect(source))
    (source / "README.md").chmod(0o644)
    (source / "README.md").write_text("Changed after verification")
    with pytest.raises(package.PackageError, match="Source changed"):
        package.require_unchanged(before, package.collect(source))


def test_archive_is_deterministic_and_preserves_executable_source():
    files = {"source/run": (0o755, b"#!/bin/sh\n"), "source/readme": (0o644, b"Example\n")}
    blob = package.archive_bytes(files)
    assert blob == package.archive_bytes(dict(reversed(list(files.items()))))
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        assert archive.getmember("source/run").mode == 0o755
        assert archive.extractfile("source/readme").read() == b"Example\n"
        assert all(item.mtime == 0 and item.uid == 0 for item in archive)


def test_failed_check_preserves_private_diagnostics_and_never_creates_candidate(source, tmp_path, monkeypatch):
    monkeypatch.setattr(package, "git", lambda *_: b"a" * 40)
    monkeypatch.setattr(package, "collect", lambda *_: {"README.md": (0o644, b"Fixture")})
    def fail(_command, _root, log):
        log.write_text("Synthetic build failure\n")
        raise package.PackageError("Build failed")
    monkeypatch.setattr(package, "run_check", fail)
    output = tmp_path / "failed-review"
    with pytest.raises(package.PackageError, match="private diagnostics"):
        package.prepare(source, source, output)
    assert json.loads((output / "failure.json").read_text())["stage"] == "verification-failed"
    assert (output / "rights-node-checks.log").read_text() == "Synthetic build failure\n"
    assert not (output / "clef-review.tar.gz").exists()
    assert not (output / "manifest.json").exists()
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
    with pytest.raises(package.PackageError, match="existing review bundles"):
        package.prepare(source, source, output)


def test_review_output_cannot_reenter_source_through_parent_symlink(source, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(package.PackageError, match="outside either source"):
        package.prepare(source, source, alias / "review")
    with pytest.raises(package.PackageError, match="symlinks"):
        package.collect(alias, generated=True)


def test_checked_environment_uses_shipped_api_prefix_and_ignores_caller_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("VITE_API_BASE", "https://provider.invalid")
    monkeypatch.setenv("VITE_DEMO_MODE", "true")
    monkeypatch.setenv("GIT_DIR", "/unrelated")
    log = tmp_path / "check.log"
    result = package.run_check([sys.executable, "-c",
        "import os; assert os.environ['VITE_API_BASE']=='/api'; assert os.environ['VITE_DEMO_MODE']=='false'; assert 'GIT_DIR' not in os.environ"], tmp_path, log)
    assert result["exitCode"] == 0


def test_git_inventory_and_revision_ignore_other_repository_overrides(source, tmp_path, monkeypatch):
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    (other / "unrelated.txt").write_text("Unrelated repository")
    for root in (source, other):
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic fixture"], cwd=root, check=True)
    expected = package.git(source, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git/index"))
    assert package.git(source, "rev-parse", "HEAD") == expected
    assert set(package.collect(source)) == {"README.md"}
