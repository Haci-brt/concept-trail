"""Is there a newer Concept Trail? Asked only when the writer presses
"Güncellemeleri denetle": the app never calls home by itself.

GitHub's newest release is the answer; a repository with tags but no release
answers through its highest tag. One with neither — or one still private,
which GitHub hides behind the same 404 — is not an error: there is simply
nothing published to compare with yet.
"""
import re
import sys

import httpx

from server.settings import REPO, REPO_URL, VERSION

API = f"https://api.github.com/repos/{REPO}"
TIMEOUT_S = 10
# tests put an httpx.MockTransport here; None is the real network
transport: httpx.BaseTransport | None = None

# what the README says: running the installer again is the update
INSTALL_COMMANDS = {
    "windows": f"irm https://raw.githubusercontent.com/{REPO}/main/install.ps1 | iex",
    "unix": f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install.sh | bash",
}

# "v0.4.0", "0.4": a release. "v0.4.0-beta.1" and other names are not compared.
TAG = re.compile(r"^v?(\d+(?:\.\d+){0,3})$")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    match = TAG.match((text or "").strip())
    if not match:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:      # 0.4 and 0.4.0 are one version
        parts.pop()
    return tuple(parts)


def install_command(platform: str = sys.platform) -> str:
    return INSTALL_COMMANDS["windows" if platform == "win32" else "unix"]


class _Unanswered(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _get(http: httpx.Client, path: str, **params):
    """The JSON at path, or None when GitHub says there is nothing there."""
    reply = http.get(path, params=params or None)
    if reply.status_code == 404:
        return None
    if reply.status_code in (403, 429):
        raise _Unanswered("limit")
    if reply.status_code != 200:
        raise _Unanswered("http")
    try:
        return reply.json()
    except ValueError:
        raise _Unanswered("http") from None


def _newest(http: httpx.Client) -> tuple[str, str] | None:
    release = _get(http, "/releases/latest")
    if isinstance(release, dict) and parse_version(release.get("tag_name")):
        return release["tag_name"].strip(), release.get("html_url") or f"{REPO_URL}/releases"
    tags = _get(http, "/tags", per_page=100) or []
    named = [tag.get("name") for tag in tags if isinstance(tag, dict)]
    versions = [name for name in named if parse_version(name)]
    if not versions:
        return None
    # the API lists tags by name, not by version: 0.10 would come after 0.9
    best = max(versions, key=parse_version)
    return best.strip(), f"{REPO_URL}/releases/tag/{best.strip()}"


def check() -> dict:
    """{"status": "update" | "current" | "none" | "error", ...}. "none" means
    nothing is published yet; "error" carries a reason: network, limit, http."""
    result = {"current": VERSION, "latest": None, "url": None, "command": install_command()}
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": f"ConceptTrail/{VERSION} (+{REPO_URL})"}
    try:
        with httpx.Client(base_url=API, headers=headers, timeout=TIMEOUT_S, follow_redirects=True,
                          trust_env=False, transport=transport) as http:
            newest = _newest(http)
    except _Unanswered as exc:
        return {**result, "status": "error", "reason": exc.reason}
    except httpx.HTTPError:
        return {**result, "status": "error", "reason": "network"}
    if newest is None:
        return {**result, "status": "none"}
    tag, url = newest
    latest = tag.removeprefix("v")
    newer = parse_version(tag) > parse_version(VERSION)
    return {**result, "status": "update" if newer else "current", "latest": latest, "url": url}
