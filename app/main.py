from pathlib import Path

from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from app.config import get_settings
from app.extractor import extract, cache_key
from app.cache import cache_get, cache_set
from app.auth import validate_api_key, check_rate_limit, APIKeyData

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


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )
