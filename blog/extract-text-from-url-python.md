# How to Extract Clean Text from a URL in Python (2026)

You have a URL. You want the article text — no HTML tags, no ads, no navigation menus. Just the content.

Here are three ways to do it, from simplest to most involved.

## Method 1: ClearText API (Simplest)

One HTTP request. No libraries to install. No HTML parsing.

```python
import requests

url = "https://paulgraham.com/persistence.html"
response = requests.get(
    "https://cleartext-api-production.up.railway.app/extract",
    params={"url": url}
)

data = response.json()["data"]
print(data["title"])        # "The Right Kind of Stubborn"
print(data["word_count"])   # 1936
print(data["content"])      # Clean article text
```

**For JavaScript-rendered pages (React, Next.js, SPAs):**
```python
response = requests.get(
    "https://cleartext-api-production.up.railway.app/extract",
    params={"url": url, "js": True}
)
```

**Pros:** Dead simple, handles edge cases, works with JS-rendered pages, free tier available.
**Cons:** External API dependency.

## Method 2: BeautifulSoup + Requests (Manual)

The classic approach. More control, more work.

```python
import requests
from bs4 import BeautifulSoup

url = "https://paulgraham.com/persistence.html"
response = requests.get(url)
soup = BeautifulSoup(response.text, "html.parser")

# Remove scripts, styles, nav, footer
for tag in soup(["script", "style", "nav", "footer", "header"]):
    tag.decompose()

text = soup.get_text(separator="\n", strip=True)
print(text)
```

**Pros:** No external dependencies, full control.
**Cons:** Doesn't handle JavaScript-rendered pages. Extraction quality varies wildly depending on the site's HTML structure. You'll spend hours writing rules for different sites.

## Method 3: Readability + Requests (Better Manual)

Uses Mozilla's Readability algorithm (same as Firefox Reader View).

```python
import requests
from readability import Document

url = "https://paulgraham.com/persistence.html"
response = requests.get(url)

doc = Document(response.text)
print(doc.title())
print(doc.summary())  # HTML of main content
```

Install with: `pip install readability-lxml`

**Pros:** Much better extraction than raw BeautifulSoup. Battle-tested algorithm.
**Cons:** Returns HTML, not plain text (you need to strip tags yourself). No JS rendering. No metadata like word count or reading time.

## Comparison

| Feature | ClearText API | BeautifulSoup | Readability |
|---------|:---:|:---:|:---:|
| Setup time | 0 min | 10 min | 5 min |
| JS rendering | Yes | No | No |
| Extraction quality | High | Low-Medium | High |
| Returns clean text | Yes | Sort of | HTML only |
| Word count / reading time | Yes | No | No |
| Language detection | Yes | No | No |
| Self-hosted | No | Yes | Yes |
| Free | 100 req/day | Unlimited | Unlimited |

## When to Use What

**Use ClearText API when:**
- You want it to just work, fast
- You need JS rendering support
- You're building a RAG pipeline or AI agent that needs clean text
- You don't want to maintain extraction infrastructure

**Use BeautifulSoup when:**
- You need to extract very specific elements (not just the article)
- You're scraping structured data, not articles
- You want zero external dependencies

**Use Readability when:**
- You want good extraction quality AND self-hosting
- You're comfortable stripping HTML tags yourself
- You don't need JS rendering

## Bonus: Batch Extraction

Need to extract text from multiple URLs? Here's a quick async script using ClearText API:

```python
import asyncio
import httpx

API_URL = "https://cleartext-api-production.up.railway.app/extract"

async def extract(client, url):
    response = await client.get(API_URL, params={"url": url})
    return response.json()["data"]

async def main():
    urls = [
        "https://paulgraham.com/persistence.html",
        "https://paulgraham.com/read.html",
        "https://paulgraham.com/think.html",
    ]
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[extract(client, url) for url in urls])
        for r in results:
            print(f"{r['title']} — {r['word_count']} words")

asyncio.run(main())
```

---

*[Try ClearText API for free →](https://cleartext-api-production.up.railway.app/docs)*
