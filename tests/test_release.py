"""What a release is made of: one version number, an update check that only
runs when asked, and a launch button that exists only where a model script does."""
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from server import fetch, settings, updates
from server.settings import REPO_URL, ROOT, VERSION

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


# ---------------------------------------------------------- one version number
def test_the_version_is_written_once_and_read_everywhere():
    assert SEMVER.match(VERSION)
    assert settings.REPO_URL == "https://github.com/Haci-brt/concept-trail"
    # the page reader introduces itself with that version and this repository
    assert f"ConceptTrail/{VERSION}" in fetch.USER_AGENT and REPO_URL in fetch.USER_AGENT
    assert f"ConceptTrail/{VERSION}" in fetch.BROWSER_UA
    # no other module carries a second copy of the number
    for path in (ROOT / "server").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"""VERSION\s*=\s*["']\d""", text) or path.name == "settings.py", path.name


def test_the_changelog_and_both_readmes_agree_with_it():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{VERSION}]" in changelog
    assert f"/releases/tag/v{VERSION}" in changelog
    for name in ("README.md", "README.tr.md"):
        assert "CHANGELOG.md" in (ROOT / name).read_text(encoding="utf-8"), name


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "config"))
    from server.app import create_app
    app = create_app(settings.Settings(vault=tmp_path / "vault", port=8765))
    return TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Fikir": "1"})


def test_the_api_reports_that_version(client):
    assert client.get("/api/version").json()["version"] == VERSION
    assert client.get("/api/state").json()["version"] == VERSION


# ---------------------------------------------------------------- update check
def github(monkeypatch, routes: dict[str, httpx.Response | Exception]):
    """Answer the GitHub API from `routes` (path suffix -> reply); log what was asked."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        for suffix, reply in routes.items():
            if request.url.path.endswith(suffix):
                if isinstance(reply, Exception):
                    raise reply
                return reply
        return httpx.Response(404)

    monkeypatch.setattr(updates, "transport", httpx.MockTransport(handler))
    return asked


def release(tag: str) -> httpx.Response:
    return httpx.Response(200, json={"tag_name": tag, "html_url": f"{REPO_URL}/releases/tag/{tag}"})


def test_a_newer_release_says_which_version_and_how_to_update(monkeypatch):
    asked = github(monkeypatch, {"/releases/latest": release("v99.0.0")})
    result = updates.check()
    assert result["status"] == "update" and result["latest"] == "99.0.0" and result["current"] == VERSION
    assert result["url"].endswith("/releases/tag/v99.0.0")
    assert "install" in result["command"]
    # the agent identifies itself with the version and the contact URL
    assert VERSION in asked[0].headers["user-agent"] and REPO_URL in asked[0].headers["user-agent"]


def test_the_same_or_an_older_release_is_up_to_date(monkeypatch):
    github(monkeypatch, {"/releases/latest": release(f"v{VERSION}")})
    assert updates.check()["status"] == "current"
    github(monkeypatch, {"/releases/latest": release("v0.0.1")})
    assert updates.check()["status"] == "current"


def test_versions_compare_as_numbers_not_as_text():
    assert updates.parse_version("v0.10.0") > updates.parse_version("0.9.0")
    assert updates.parse_version("0.4") == updates.parse_version("v0.4.0")
    assert updates.parse_version("v1.0.0-beta.1") is None and updates.parse_version("nightly") is None


def test_without_a_release_the_highest_tag_answers(monkeypatch):
    github(monkeypatch, {"/tags": httpx.Response(200, json=[{"name": "v0.9.0"}, {"name": "v0.10.0"}, {"name": "junk"}])})
    result = updates.check()
    assert result["status"] == "update" and result["latest"] == "0.10.0"


def test_a_404_is_not_an_error(monkeypatch):
    """A private repository and one with nothing published both answer 404."""
    github(monkeypatch, {})
    result = updates.check()
    assert result["status"] == "none" and result["latest"] is None and "reason" not in result


@pytest.mark.parametrize("reply,reason", [
    (httpx.Response(403, json={"message": "rate limit"}), "limit"),
    (httpx.Response(429), "limit"),
    (httpx.Response(500), "http"),
    (httpx.Response(200, content=b"<html>"), "http"),
    (httpx.ConnectError("offline"), "network"),
])
def test_a_failed_check_names_its_reason(monkeypatch, reply, reason):
    github(monkeypatch, {"/releases/latest": reply})
    result = updates.check()
    assert result["status"] == "error" and result["reason"] == reason


def test_the_check_runs_only_when_asked(client, monkeypatch):
    asked = github(monkeypatch, {"/releases/latest": release("v99.0.0")})
    client.get("/api/state")
    client.get("/api/version")
    assert asked == []                       # nothing calls home by itself
    assert client.post("/api/update/check").json()["status"] == "update"
    assert len(asked) == 1
    # a page of some other origin cannot make the app ask GitHub
    assert TestClient(client.app, base_url="http://127.0.0.1:8765").post("/api/update/check").status_code == 403


# --------------------------------------------------------------- launch scripts
def test_only_scripts_that_exist_are_offered(tmp_path, monkeypatch, client):
    present = tmp_path / "run_model.sh"
    present.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(settings, "LAUNCH_SCRIPTS", {"Here": present, "Gone": tmp_path / "missing.sh"})
    assert settings.available_launch_scripts() == ["Here"]
    assert client.get("/api/state").json()["scripts"] == ["Here"]


def test_with_no_script_there_is_nothing_to_launch(tmp_path, monkeypatch, client):
    monkeypatch.setattr(settings, "LAUNCH_SCRIPTS", {"Gone": tmp_path / "missing.sh"})
    assert settings.available_launch_scripts() == []
    assert client.get("/api/state").json()["scripts"] == []
    reply = client.post("/api/model/launch", json={})
    assert reply.status_code == 404 and "Sihirbazla bağla" in reply.json()["detail"]
