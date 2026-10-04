"""Web/YouTube search used to give the AI up-to-date info for questions that need it."""

import re

from ddgs import DDGS

import config
import state


def web_search(query: str, max_results: int = 3) -> list:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [(r.get("title", ""), r.get("href", "")) for r in results]
    except Exception:
        return []


def youtube_search(query: str) -> tuple:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"site:youtube.com {query}", max_results=3))
        for r in results:
            url = r.get("href", "")
            if "youtube.com/watch" in url or "youtu.be" in url:
                return r.get("title", ""), url
    except Exception:
        pass
    return "", ""


def needs_web_search(question: str) -> bool:
    lower = question.lower()
    return any(kw in lower for kw in config.EXPLICIT_SEARCH_KEYWORDS + config.CURRENT_INFO_KEYWORDS)


def get_search_context(question: str) -> str:
    if not needs_web_search(question) and not state.local_enabled:
        return ""
    lower = question.lower()
    if "youtube" in lower or "video" in lower or "watch" in lower:
        clean = re.sub(r'\b(find|search|look up|get me|show me|youtube|video|link|watch)\b', '', question, flags=re.IGNORECASE).strip()
        title, url = youtube_search(clean if clean else question)
        if url:
            return f"YouTube: {title} — {url.rstrip('.)').strip()}"
        return ""
    results = web_search(question)
    if results:
        return "\n".join(f"{t} — {u.rstrip(')').strip()}" for t, u in results[:2])
    return ""
