"""Pure validation shared by runtime settings and operator source checks."""

import re
from urllib.parse import unquote, urlsplit


def valid_immutable_revision(revision: object) -> bool:
    return isinstance(revision, str) and bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision))


def source_url_names_revision(source_url: object, revision: object) -> bool:
    if not isinstance(source_url, str) or not valid_immutable_revision(revision):
        return False
    try:
        if any(ord(char) <= 32 or ord(char) == 127 for char in source_url) or "\\" in source_url:
            return False
        parsed = urlsplit(source_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            return False
        path = unquote(parsed.path).rstrip("/")
        return bool(re.search(rf"(?:^|/){revision}(?:/|\.tar\.gz$|\.tgz$|\.tar$|$)", path))
    except ValueError:
        return False
