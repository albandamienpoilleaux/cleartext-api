from pathlib import Path

import stripe
from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from app.config import get_settings
from app.extractor import extract, cache_key
from app.cache import cache_get, cache_set
from app.auth import validate_api_key, check_rate_limit, APIKeyData
from app.billing import (
    create_checkout_session,
    handle_webhook_event,
    get_checkout_result,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Extract clean, readable text from any URL. Like Reader Mode, as an API.",
    docs_url="/docs",
    redoc_url="/redoc",
)


class ExtractionResponse(BaseModel):
    success: bool = True
    cached: bool = False
    data: dict


class ErrorResponse(BaseModel):
    success: bool = False
    error: str


STATIC_DIR = Path(__file__).parent.parent / "static"


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/extract", response_model=ExtractionResponse)
async def extract_content(
    url: str = Query(..., description="The URL to extract content from"),
    js: bool = Query(False, description="Enable JavaScript rendering (slower, for JS-heavy sites)"),
    no_cache: bool = Query(False, description="Bypass cache and fetch fresh content"),
    key_data: APIKeyData = Depends(validate_api_key),
):
    """
    Extract clean, readable text from any URL.

    Returns the main article content stripped of navigation, ads, footers,
    and other non-content elements.

    - **url**: The web page URL to extract content from
    - **js**: Set to true for JavaScript-rendered pages (SPA, React sites). Slower but more accurate.
    - **no_cache**: Set to true to bypass the 24h cache and get fresh content.
    """
    # Rate limit check
    await check_rate_limit(key_data)

    # Validate URL format
    try:
        parsed = HttpUrl(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL format")

    if str(parsed).startswith("file://"):
        raise HTTPException(status_code=400, detail="file:// URLs are not allowed")

    # Check cache first
    ck = cache_key(url)
    if not no_cache:
        cached = await cache_get(ck)
        if cached:
            return ExtractionResponse(cached=True, data=cached)

    # Extract content
    try:
        result = await extract(
            url=str(url),
            use_js=js,
            timeout_ms=settings.playwright_timeout_ms,
        )
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            raise HTTPException(status_code=504, detail="Timeout fetching URL")
        if "404" in error_msg or "Not Found" in error_msg:
            raise HTTPException(status_code=404, detail="URL returned 404")
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {error_msg[:200]}")

    if not result.content or result.word_count < 10:
        raise HTTPException(status_code=422, detail="Could not extract meaningful content from this URL")

    response_data = {
        "title": result.title,
        "content": result.content,
        "author": result.author,
        "domain": result.domain,
        "word_count": result.word_count,
        "reading_time_minutes": result.reading_time_minutes,
        "language": result.language,
        "source_url": result.source_url,
    }

    # Cache the result
    await cache_set(ck, response_data)

    return ExtractionResponse(data=response_data)


# ─── Billing routes ───────────────────────────────────────────────

@app.post("/billing/checkout")
async def billing_checkout(request: Request):
    """Create a Stripe Checkout session for the Pro plan."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing not configured")
    base_url = str(request.base_url).rstrip("/")
    checkout_url = await create_checkout_session(base_url)
    return RedirectResponse(url=checkout_url, status_code=303)


@app.get("/billing/success", response_class=HTMLResponse)
async def billing_success(session_id: str = Query(None)):
    """Show the API key after successful checkout."""
    if not session_id:
        return RedirectResponse(url="/")

    result = await get_checkout_result(session_id)
    if not result:
        # Webhook may not have fired yet — show a waiting message
        return HTMLResponse(SUCCESS_PAGE_WAITING)

    return HTMLResponse(success_page_html(result["api_key"], result["email"]))


@app.post("/billing/webhook")
async def billing_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if settings.stripe_webhook_secret and sig_header:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    else:
        import json
        event = json.loads(payload)

    message = await handle_webhook_event(event)
    return {"received": True, "message": message}


# ─── Success page templates ──────────────────────────────────────

SUCCESS_PAGE_WAITING = """<!DOCTYPE html>
<html><head><title>Processing...</title>
<meta http-equiv="refresh" content="3">
<style>
body { font-family: system-ui; background: #0a0a0a; color: #e5e5e5;
       display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
.card { background: #171717; padding: 3rem; border-radius: 1rem; text-align: center; max-width: 500px; }
h1 { color: #22c55e; }
</style></head>
<body><div class="card">
<h1>Processing payment...</h1>
<p>This page will refresh automatically. Please wait a few seconds.</p>
</div></body></html>"""


def success_page_html(api_key: str, email: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Welcome to ClearText Pro!</title>
<style>
body {{ font-family: system-ui; background: #0a0a0a; color: #e5e5e5;
       display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
.card {{ background: #171717; padding: 3rem; border-radius: 1rem; max-width: 600px; }}
h1 {{ color: #22c55e; margin-bottom: 0.5rem; }}
.key-box {{ background: #0a0a0a; border: 1px solid #333; border-radius: 0.5rem;
            padding: 1rem; margin: 1.5rem 0; font-family: monospace; font-size: 1.1rem;
            word-break: break-all; color: #4ade80; cursor: pointer; }}
.key-box:hover {{ border-color: #22c55e; }}
.warn {{ background: #1c1107; border: 1px solid #854d0e; padding: 1rem; border-radius: 0.5rem;
         margin: 1rem 0; color: #fbbf24; }}
code {{ background: #262626; padding: 0.2rem 0.5rem; border-radius: 0.25rem; }}
a {{ color: #22c55e; }}
</style>
<script>
function copyKey() {{
  navigator.clipboard.writeText("{api_key}");
  document.getElementById('copied').style.display = 'inline';
  setTimeout(() => document.getElementById('copied').style.display = 'none', 2000);
}}
</script>
</head>
<body><div class="card">
<h1>You're in!</h1>
<p>ClearText Pro is active for <strong>{email}</strong></p>

<p>Your API key (click to copy):</p>
<div class="key-box" onclick="copyKey()">{api_key}</div>
<span id="copied" style="display:none; color:#22c55e;">Copied!</span>

<div class="warn">
  Save this key now! It won't be shown again after you leave this page.
</div>

<h3>Quick start:</h3>
<pre style="background:#0a0a0a; padding:1rem; border-radius:0.5rem; overflow-x:auto;"><code>curl "https://cleartext-api-production.up.railway.app/extract?url=https://example.com" \\
  -H "X-API-Key: {api_key}"</code></pre>

<p style="margin-top:2rem;">
  <a href="/docs">API Documentation</a>
</p>
</div></body></html>"""


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )
