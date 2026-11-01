"""Shared exact corresponding-source URL and revision validation."""

from __future__ import annotations

import hashlib
import gzip
import io
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import urllib.request
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.source_reference import source_url_names_revision, valid_immutable_revision


class SourceVerificationError(RuntimeError):
    pass


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise SourceVerificationError("Public source redirects must retain HTTPS and anonymous access")
        return super().redirect_request(request, response, code, message, headers, new_url)


def anonymous_open(url: str, timeout: float = 10):
    # A fresh opener has no cookies, HTTP authentication handler, or Git credentials.
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise SourceVerificationError("Public source access requires anonymous HTTPS")
    return urllib.request.build_opener(HTTPSRedirect()).open(
        urllib.request.Request(url, headers={"User-Agent": "Clef-Release-Verifier/1.0"}), timeout=timeout)


def public_source_status(source_url: str, timeout: float = 10) -> int:
    with anonymous_open(source_url, timeout) as response:
        return int(response.status)


def archive_url(source_url: str, revision: str) -> str:
    if not source_url_names_revision(source_url, revision):
        raise SourceVerificationError("Source URL must identify a full Git commit hash over HTTPS")
    parsed = urlsplit(source_url)
    path = parsed.path.rstrip("/")
    if path.endswith((".tar.gz", ".tgz", ".tar")):
        return source_url
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.hostname == "github.com":
        match = re.fullmatch(rf"/([^/]+/[^/]+)/(?:tree|commit)/{revision}", path)
        if match:
            return f"{origin}/{match[1]}/archive/{revision}.tar.gz"
    match = re.fullmatch(rf"/(.+)/-/tree/{revision}", path)
    if match:
        repository = match[1]
        return f"{origin}/{repository}/-/archive/{revision}/{repository.split('/')[-1]}-{revision}.tar.gz"
    raise SourceVerificationError("Use a GitHub commit page, GitLab commit tree, or HTTPS tar archive naming the full commit")


def commit_files(source_dir: Path, revision: str) -> dict[str, tuple[str, str]]:
    if not valid_immutable_revision(revision):
        raise SourceVerificationError("Expected revision must be a full Git commit hash")
    try:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        resolved = subprocess.run(["git", "rev-parse", f"{revision}^{{commit}}"], cwd=source_dir,
                                  check=True, capture_output=True, timeout=15, env=environment).stdout.decode().strip()
        if resolved != revision:
            raise SourceVerificationError("Expected hash does not identify a commit")
        tree = subprocess.run(["git", "ls-tree", "-rz", "--full-tree", revision], cwd=source_dir,
                              check=True, capture_output=True, timeout=15, env=environment).stdout
        result = {}
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            info, name = entry.split(b"\t", 1)
            mode, kind, digest = info.decode().split()
            if kind != "blob" or mode not in {"100644", "100755", "120000"}:
                raise SourceVerificationError("Source verification requires complete file content; include submodule sources in the release")
            result[name.decode("utf-8")] = (mode, digest)
        if not result:
            raise SourceVerificationError("Expected commit contains no source files")
        return result
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        raise SourceVerificationError("Could not read the expected commit from the local source checkout") from None


def archive_files(data: bytes, *, algorithm: str, max_bytes: int) -> dict[str, tuple[str, str]]:
    files = {}
    expanded = 0
    try:
        if data.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                data = compressed.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SourceVerificationError("Source archive exceeds the expanded size limit")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for index, member in enumerate(archive):
                if index >= 10000:
                    raise SourceVerificationError("Source archive exceeds the entry limit")
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                    raise SourceVerificationError("Source archive contains an unsafe path")
                if member.isdir():
                    continue
                name = str(path)
                if name in files:
                    raise SourceVerificationError("Source archive contains duplicate file paths")
                if member.issym():
                    content = member.linkname.encode("utf-8")
                    mode = "120000"
                elif member.isfile():
                    expanded += member.size
                    if expanded > max_bytes:
                        raise SourceVerificationError("Source archive exceeds the expanded size limit")
                    handle = archive.extractfile(member)
                    content = handle.read(member.size + 1)
                    if len(content) != member.size:
                        raise SourceVerificationError("Source archive contains a truncated file")
                    mode = "100755" if member.mode & 0o111 else "100644"
                else:
                    raise SourceVerificationError("Source archive contains an unsupported entry type")
                digest = hashlib.new(algorithm, f"blob {len(content)}\0".encode() + content).hexdigest()
                files[name] = (mode, digest)
    except (tarfile.TarError, OSError, EOFError, UnicodeError):
        raise SourceVerificationError("Public source response is not a readable tar archive") from None
    return files


def verify_public_source(source_url: str, revision: str, source_dir: Path, *, max_bytes: int = 128 * 1024 * 1024) -> dict:
    expected = commit_files(source_dir, revision)
    download = archive_url(source_url, revision)
    try:
        with anonymous_open(download, 30) as response:
            if response.status != 200:
                raise SourceVerificationError("Source archive did not return HTTP 200")
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SourceVerificationError("Source archive exceeds the download limit")
    except OSError:
        raise SourceVerificationError("Public source archive could not be downloaded anonymously") from None
    observed = archive_files(data, algorithm="sha1" if len(revision) == 40 else "sha256", max_bytes=max_bytes)
    # Git host archives use one enclosing directory; custom archives may start at root.
    matches = observed == expected
    roots = {name.split("/", 1)[0] for name in observed}
    if not matches and len(roots) == 1 and all("/" in name for name in observed):
        matches = {name.split("/", 1)[1]: value for name, value in observed.items()} == expected
    if not matches:
        raise SourceVerificationError("Public archive file contents or modes differ from the expected Git commit")
    return {"verified": True, "revision": revision, "archiveUrl": download,
            "archiveSha256": hashlib.sha256(data).hexdigest(), "fileCount": len(expected)}
