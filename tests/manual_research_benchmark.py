"""Run a small live research benchmark against an isolated local test vault.

Example: python tests/manual_research_benchmark.py --url http://127.0.0.1:8877
The server's vault name must contain ``fikir-research-eval``. Only synthetic
notes are created, so a real vault cannot be used by accident.
"""

import argparse
import json
import time
from urllib.parse import urlparse

import requests


CASES = [
    {
        "name": "Markdown bilgi ağı",
        "content": "# Local-first Markdown knowledge graph\n\nBuild an open-source Markdown notebook with backlinks, a graph view, full-text search, and threaded questions. Find reusable graph visualization, Markdown editing, and local search components.\n",
        "focus": "graph visualization and local full-text search libraries",
        "known": ["logseq", "foam", "silverbullet", "cytoscape", "vis-network", "meilisearch"],
    },
    {
        "name": "Kanıtlı web araştırması",
        "content": "# Evidence-based web research assistant\n\nBuild a local research workspace that searches the web, opens pages, extracts their main text, cites evidence, respects robots.txt, and blocks SSRF. Find open-source crawlers, extraction libraries, and browser automation tools.\n",
        "focus": "page extraction, crawling, citations, and safe fetching tools",
        "known": ["crawl4ai", "trafilatura", "scrapy", "playwright", "readability"],
    },
    {
        # a Turkish note outside the two domains the heuristics were tuned on
        "name": "Kod inceleme botu",
        "content": "# Kod inceleme botu\n\nPull request'leri otomatik inceleyen bir GitHub uygulaması yapmak istiyorum. Değişen dosyaları okuyup riskli kısımlara satır yorumu bıraksın, statik analiz çalıştırsın ve sadece önemli uyarıları yazsın.\n",
        "focus": "",
        "known": ["pr-agent", "reviewdog", "danger", "sonarqube", "semgrep"],
    },
]


def run(base_url: str, timeout: float, cases=CASES) -> list[dict]:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise SystemExit("Benchmark yalnız http://127.0.0.1 üzerinde çalışır.")
    session = requests.Session()
    session.headers.update({"X-Fikir": "1", "Content-Type": "application/json"})
    base = base_url.rstrip("/")
    state = session.get(base + "/api/state", timeout=10).json()
    if "fikir-research-eval" not in state.get("vault", ""):
        raise SystemExit("İzole test kasası bulunamadı; gerçek notlara yazılmadı.")
    results = []
    for case in cases:
        created = session.post(base + "/api/notes/create", json={"name": case["name"], "content": case["content"]}, timeout=10)
        created.raise_for_status()
        path = created.json()["path"]
        start_time = time.monotonic()
        started = session.post(base + "/api/research/start", json={"path": path, "content": case["content"], "focus": case["focus"]}, timeout=10)
        started.raise_for_status()
        deadline = start_time + timeout
        while time.monotonic() < deadline:
            response = session.get(base + "/api/research", params={"path": path}, timeout=10)
            response.raise_for_status()
            report = response.json()
            if report.get("status") in {"done", "error", "cancelled"}:
                break
            time.sleep(2)
        else:
            report = {"status": "timeout"}
        sources = report.get("sources") or []
        verified = [source for source in sources if source.get("verified")]
        readmes = [source for source in verified if urlparse(source.get("url") or "").hostname == "github.com"]
        queries = report.get("queries") or []
        corpus = " ".join(str(row.get(key) or "") for group in
                          (report.get("candidates") or [], report.get("tools") or [], sources)
                          for row in group for key in ("repo", "name", "title", "description", "excerpt", "url")).lower()
        row = {
            "case": case["name"], "path": path, "status": report.get("status"),
            "error": report.get("error"), "seconds": round(time.monotonic() - start_time, 1),
            "queries": len(queries), "successful_queries": sum(bool(query.get("ok")) for query in queries),
            "sources": len(sources), "read_pages": len(verified),
            "read_web_pages": len(verified) - len(readmes), "read_readmes": len(readmes),
            "read_chars": sum(len(source.get("content") or "") for source in verified),
            "read_hosts": len({urlparse(source["url"]).hostname for source in verified}),
            "projects": len(report.get("candidates") or []), "tools": len(report.get("tools") or []),
            "opportunities": len(report.get("opportunities") or []),
            "timings": report.get("timings") or {},
            "known_project_or_tool_hits": [name for name in case["known"] if name in corpus],
            "read_source_titles": [source.get("title") for source in verified],
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--timeout", type=float, default=360)
    parser.add_argument("--case", type=int, choices=range(1, len(CASES) + 1),
                        help="Yalnız seçilen sentetik fikri çalıştır")
    options = parser.parse_args()
    run(options.url, options.timeout, CASES[options.case - 1:options.case] if options.case else CASES)
