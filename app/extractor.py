import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from lxml.html.clean import Cleaner
from readability import Document


@dataclass
class ExtractedContent:
    title: str
    content: str
    author: str | None
    domain: str
    word_count: int
    reading_time_minutes: int
    language: str | None
    source_url: str


def _detect_language(text: str) -> str | None:
    """Basic language detection based on common words."""
    sample = text[:2000].lower()
    fr_words = {"le", "la", "les", "de", "des", "un", "une", "et", "est", "en", "que", "pour", "dans", "qui", "sur"}
    en_words = {"the", "is", "and", "of", "to", "in", "that", "it", "for", "was", "with", "on", "are", "this"}
    es_words = {"el", "la", "los", "las", "de", "en", "que", "por", "con", "una", "para", "como", "pero", "sus"}
    de_words = {"der", "die", "das", "und", "ist", "von", "den", "mit", "sich", "des", "auf", "ein", "eine", "auch"}

    words = set(re.findall(r"\b\w+\b", sample))
    scores = {
        "en": len(words & en_words),
        "fr": len(words & fr_words),
        "es": len(words & es_words),
        "de": len(words & de_words),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None


def _extract_author(html: str) -> str | None:
    """Try to extract author from common meta tags."""
    patterns = [
        r'<meta[^>]*name=["\']author["\'][^>]*content=["\'](.*?)["\']',
        r'<meta[^>]*content=["\'](.*?)["\'][^>]*name=["\']author["\']',
        r'<meta[^>]*property=["\']article:author["\'][^>]*content=["\'](.*?)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _html_to_text(html: str) -> str:
    """Convert HTML to clean text, preserving basic structure."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"</h[1-6]>", "\n\n", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"</blockquote>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cache_key(url: str) -> str:
    """Generate a cache key for a URL."""
    return f"cleartext:{hashlib.sha256(url.encode()).hexdigest()}"


async def fetch_html(url: str) -> str:
    """Fetch HTML content from a URL using httpx (fast, no JS)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ClearTextBot/1.0; +https://cleartext-api.com)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


async def fetch_html_js(url: str, timeout_ms: int = 15000) -> str:
    """Fetch HTML with JS rendering via Playwright (slower, for JS-heavy sites)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(2000)  # Let lazy content load
        html = await page.content()
        await browser.close()
        return html


async def extract(url: str, use_js: bool = False, timeout_ms: int = 15000) -> ExtractedContent:
    """Extract clean content from a URL."""
    if use_js:
        html = await fetch_html_js(url, timeout_ms)
    else:
        html = await fetch_html(url)

    author = _extract_author(html)
    doc = Document(html)
    title = doc.title()
    content_html = doc.summary()
    content = _html_to_text(content_html)
    language = _detect_language(content)
    words = len(content.split())
    reading_time = max(1, round(words / 238))
    domain = urlparse(url).netloc

    return ExtractedContent(
        title=title,
        content=content[:500000],
        author=author,
        domain=domain,
        word_count=words,
        reading_time_minutes=reading_time,
        language=language,
        source_url=url,
    )
