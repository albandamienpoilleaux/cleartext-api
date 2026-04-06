import json
from typing import Any

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis | None:
    """Get or create Redis connection. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = None
        return None


async def cache_get(key: str) -> dict | None:
    """Get a cached value. Returns None on miss or if Redis is down."""
    r = await get_redis()
    if r is None:
        return None
    try:
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


async def cache_set(key: str, value: dict, ttl: int | None = None) -> None:
    """Cache a value. Silently fails if Redis is down."""
    r = await get_redis()
    if r is None:
        return
    try:
        ttl = ttl or settings.cache_ttl_seconds
        await r.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass


async def cache_delete(key: str) -> None:
    """Delete a cached value."""
    r = await get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass
