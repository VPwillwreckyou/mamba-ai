"""Real web search and page fetching using DuckDuckGo's HTML endpoint."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class WebSearch:
    """Web research: live search results with sources, plus page text fetch."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    @staticmethod
    def _unwrap_ddg_url(href: str) -> str:
        """DuckDuckGo wraps results in /l/?uddg=<real-url> redirects."""
        try:
            parsed = urlparse(href)
            if parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    return unquote(qs["uddg"][0])
        except Exception:
            pass
        return href

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Run a live web search and return titles, URLs, and snippets."""
        if not query or not query.strip():
            return {"success": False, "error": "Empty query"}
        try:
            response = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=DEFAULT_HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Search endpoint returned HTTP {response.status_code}",
                    "query": query,
                }
            results = self._parse_results(response.text, max_results)
            if not results:
                return {
                    "success": False,
                    "error": "No results parsed from response",
                    "query": query,
                    "provider": "duckduckgo_html",
                }
            return {
                "success": True,
                "query": query,
                "provider": "duckduckgo_html",
                "results": results,
                "count": len(results),
            }
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"Network error: {exc}", "query": query}
        except Exception as exc:
            return {"success": False, "error": str(exc), "query": query}

    @staticmethod
    def _parse_results(html: str, max_results: int) -> list[dict[str, str]]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, str]] = []
        for block in soup.select("div.result, div.web-result"):
            anchor = block.select_one("a.result__a")
            if anchor is None:
                continue
            snippet_el = block.select_one("a.result__snippet, div.result__snippet")
            title = anchor.get_text(" ", strip=True)
            href = anchor.get("href", "")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if not title or not href:
                continue
            results.append({
                "title": title,
                "url": WebSearch._unwrap_ddg_url(href),
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break
        return results

    def fetch_page(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        """Fetch a page and return its title and readable text."""
        try:
            response = httpx.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
            )
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}", "url": url}
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = soup.title.get_text(strip=True) if soup.title else ""
            text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:max_chars]
            return {
                "success": True,
                "url": str(response.url),
                "title": title,
                "text": text,
                "chars": len(text),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": url}
