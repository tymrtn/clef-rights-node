import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest


SPEC = importlib.util.spec_from_file_location("source_archive_verifier", Path(__file__).resolve().parents[2] / "scripts/source_binding.py")
binding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binding)


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                               "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", *args],
                              cwd=tmp_path, check=True, capture_output=True).stdout
    git("init", "--quiet")
    (tmp_path / "README.txt").write_text("A complete source fixture.\n")
    (tmp_path / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "run.sh").chmod(0o755)
    (tmp_path / "readme-link").symlink_to("README.txt")
    git("add", ".")
    git("commit", "--quiet", "-m", "Synthetic source fixture")
    revision = git("rev-parse", "HEAD").decode().strip()
    return tmp_path, revision, git("archive", "--format=tar.gz", "--prefix=source/", revision)


def serve(monkeypatch, data):
    class Response(io.BytesIO):
        status = 200
    monkeypatch.setattr(binding, "anonymous_open", lambda *_args: Response(data))


def test_anonymous_archive_matches_real_git_blobs_modes_and_symlink(repository, monkeypatch):
    root, revision, data = repository
    serve(monkeypatch, data)
    result = binding.verify_public_source(f"https://github.com/example/node/tree/{revision}", revision, root)
    assert result["verified"] is True
    assert result["fileCount"] == 3
    assert len(result["archiveSha256"]) == 64


def changed_archive(data, change):
    result = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as original, tarfile.open(fileobj=result, mode="w:gz") as output:
        for entry in original:
            content = original.extractfile(entry).read() if entry.isfile() else None
            entry, content = change(entry, content)
            if entry is not None:
                if content is not None:
                    entry.size = len(content)
                output.addfile(entry, io.BytesIO(content) if content is not None else None)
    return result.getvalue()


@pytest.mark.parametrize("change", ["content", "missing", "mode", "symlink"])
def test_reachable_archive_with_different_contents_or_modes_fails(repository, monkeypatch, change):
    root, revision, data = repository
    def alter(entry, content):
        if entry.name == "source/README.txt":
            if change == "content": content = b"Unrelated source that still returns HTTP 200."
            if change == "missing": return None, None
            if change == "mode": entry.mode = 0o755
        if entry.issym() and change == "symlink": entry.linkname = "run.sh"
        return entry, content
    serve(monkeypatch, changed_archive(data, alter))
    with pytest.raises(binding.SourceVerificationError, match="differ"):
        binding.verify_public_source(f"https://github.com/example/node/tree/{revision}", revision, root)


def test_http_200_html_page_is_not_corresponding_source(repository, monkeypatch):
    root, revision, _data = repository
    serve(monkeypatch, b"<html>Unrelated landing page</html>")
    with pytest.raises(binding.SourceVerificationError, match="tar archive"):
        binding.verify_public_source(f"https://source.example/{revision}/source.tar.gz", revision, root)


@pytest.mark.parametrize("path", ["../outside", "/absolute", "source/../../outside"])
def test_unsafe_archive_paths_never_extract(path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        entry = tarfile.TarInfo(path)
        entry.size = 1
        archive.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(binding.SourceVerificationError, match="unsafe path"):
        binding.archive_files(raw.getvalue(), algorithm="sha1", max_bytes=20000)


def test_compressed_metadata_is_bounded_before_tar_parsing():
    compressed = gzip.compress(b"x" * 100000)
    with pytest.raises(binding.SourceVerificationError, match="expanded size"):
        binding.archive_files(compressed, algorithm="sha1", max_bytes=1024)


def test_unrelated_source_page_cannot_select_an_arbitrary_archive(repository):
    _root, revision, _data = repository
    with pytest.raises(binding.SourceVerificationError, match="Use a GitHub"):
        binding.archive_url(f"https://unrelated.example/{revision}", revision)


def test_source_archive_mapping_supports_gitlab_and_explicit_archive(repository):
    _root, revision, _data = repository
    assert binding.archive_url(f"https://git.example/team/subgroup/node/-/tree/{revision}", revision) == f"https://git.example/team/subgroup/node/-/archive/{revision}/node-{revision}.tar.gz"
    url = f"https://source.example/{revision}/source.tar.gz"
    assert binding.archive_url(url, revision) == url


@pytest.mark.parametrize("valid_archive", [True, False])
def test_release_gate_requires_matching_public_content_not_just_http_200(repository, monkeypatch, capsys, valid_archive):
    root, revision, data = repository
    spec = importlib.util.spec_from_file_location("release_archive_gate", Path(__file__).resolve().parents[2] / "scripts/verify_release.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    serve(monkeypatch, data if valid_archive else b"<html>HTTP 200, unrelated content</html>")
    monkeypatch.setattr(release, "verify_public_source", binding.verify_public_source)
    monkeypatch.setattr(release, "public_source_status", lambda _url: 200)
    monkeypatch.setattr(release, "fetch_json", lambda _url: {
        "sourceCodeRevision": revision, "sourceCodeUrl": f"https://github.com/example/node/tree/{revision}",
        "ephemeralSigningKey": False, "keyId": "fixture-key",
    })
    monkeypatch.setattr(sys, "argv", ["verify_release.py", "--api-url", "https://node.example.test",
                                    "--source-dir", str(root), "--expected-revision", revision, "--require-clean"])
    assert release.main() == (0 if valid_archive else 1)
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is valid_archive
    assert report["sourceHttpStatus"] == 200
