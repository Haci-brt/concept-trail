"""GitHub research inside the app: its safety rules, its widened limits, its cache."""
import base64
import json

import httpx
import pytest

from server.errors import ApiError
from server.github import SEARCH_SPACING_ANON, SEARCH_SPACING_TOKEN, GitHubLimited, GitHubResearch

REPO = {"full_name": "mealie-recipes/mealie", "html_url": "https://github.com/mealie-recipes/mealie",
        "description": "Recipe manager", "stargazers_count": 13000, "forks_count": 900, "open_issues_count": 80,
        "pushed_at": "2026-09-01T00:00:00Z", "archived": False, "fork": False, "topics": ["recipe-manager"],
        "language": "Python", "homepage": "https://mealie.io", "license": {"spdx_id": "AGPL-3.0"},
        "private": False, "visibility": "public"}


def client(handler, token="", tmp_path=None, waits=None):
    clock = {"now": 0.0}

    def sleep(seconds):
        (waits if waits is not None else []).append(seconds)
        clock["now"] += seconds
    return GitHubResearch(token=lambda: token, cache_dir=tmp_path, transport=httpx.MockTransport(handler),
                          clock=lambda: clock["now"], sleep=sleep)


def test_search_keeps_only_public_repositories_sorted_by_stars():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"total_count": 2, "incomplete_results": False,
                                         "items": [REPO, {**REPO, "full_name": "x/private", "private": True}]})
    result = client(handler).search("topic:recipe-manager", per_page=50)
    assert [r["repo"] for r in result["items"]] == ["mealie-recipes/mealie"]
    assert seen["q"] == "topic:recipe-manager is:public" and seen["sort"] == "stars" and seen["order"] == "desc"
    assert result["items"][0]["homepage"] == "https://mealie.io" and result["items"][0]["forks"] == 900


def test_searches_are_spaced_by_what_github_allows():
    """30 a minute with a token, 10 without; llm-stack spaced every search 6.1 s."""
    ok = lambda request: httpx.Response(200, json={"total_count": 0, "items": []})
    waits = []
    with_token = client(ok, token="t", waits=waits)
    with_token.search("a")
    with_token.search("b")
    assert waits == [pytest.approx(SEARCH_SPACING_TOKEN)]
    waits.clear()
    anonymous = client(ok, waits=waits)
    anonymous.search("a")
    anonymous.search("b")
    assert waits == [pytest.approx(SEARCH_SPACING_ANON)]


def test_a_rate_limit_blocks_until_reset_and_says_so():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "retry-after": "30"})
    github = client(handler)
    with pytest.raises(GitHubLimited):
        github.repo("a/b")
    with pytest.raises(GitHubLimited):
        github.repo("c/d")
    assert len(calls) == 1                        # the second never left


def test_the_cache_answers_a_question_asked_again(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=REPO)
    github = client(handler, tmp_path=tmp_path)
    assert github.repo("mealie-recipes/mealie")["stars"] == 13000
    assert github.repo("mealie-recipes/mealie")["stars"] == 13000
    assert len(calls) == 1


def test_only_known_paths_and_repository_names_leave():
    github = client(lambda request: httpx.Response(200, json=REPO))
    with pytest.raises(ApiError):
        github.repo("../../user")
    with pytest.raises(ApiError):
        github._get("repo", "/user/repos")


def test_a_private_repository_is_refused():
    with pytest.raises(ApiError):
        client(lambda request: httpx.Response(200, json={**REPO, "private": True})).repo("a/b")


def test_the_token_never_appears_in_an_error():
    def handler(request):
        raise httpx.ConnectError("could not reach with secret-token-123")
    with pytest.raises(ApiError) as err:
        client(handler, token="secret-token-123").repo("a/b")
    assert "secret-token-123" not in err.value.message


def test_or_between_topics_is_explained():
    with pytest.raises(ApiError) as err:
        client(lambda request: httpx.Response(422, json={})).search("topic:a OR topic:b")
    assert "OR" in err.value.message


def test_widened_readme_issues_and_topics():
    readme = base64.b64encode("# Mealie\nhttps://mealie.io".encode()).decode()

    def handler(request):
        path = request.url.path
        if path.endswith("/readme"):
            return httpx.Response(200, json={"encoding": "base64", "content": readme, "html_url": "u"})
        if path.endswith("/issues"):
            assert request.url.params["sort"] == "comments"
            return httpx.Response(200, json=[{"number": 1, "title": "Sync loses data", "comments": 40},
                                             {"number": 2, "title": "PR", "pull_request": {}}])
        if path == "/search/topics":
            return httpx.Response(200, json={"items": [{"name": "recipe-manager"}, {"name": "recipes"}]})
        return httpx.Response(404)
    github = client(handler)
    assert github.readme("mealie-recipes/mealie")["text"].startswith("# Mealie")
    assert [i["title"] for i in github.issues("mealie-recipes/mealie", sort="comments")["items"]] == ["Sync loses data"]
    assert [t["name"] for t in github.topics("recipe manager")["items"]] == ["recipe-manager", "recipes"]
