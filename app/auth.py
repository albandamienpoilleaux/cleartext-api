import hashlib
import secrets
from dataclasses import dataclass
from enum import Enum

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.cache import get_redis

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"


@dataclass
class APIKeyData:
    key_hash: str
    tier: Tier
    email: str
    requests_today: int = 0


# Rate limits per tier (requests per day)
TIER_LIMITS = {
    Tier.FREE: 100,
    Tier.PRO: 5000,
    Tier.BUSINESS: 50000,
}

# Rate limits per minute
TIER_RATE_LIMITS = {
    Tier.FREE: 10,
    Tier.PRO: 60,
    Tier.BUSINESS: 300,
}


def hash_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"ct_{secrets.token_urlsafe(32)}"


async def get_or_create_demo_keys() -> None:
    """Create demo API keys in Redis for testing."""
    r = await get_redis()
    if r is None:
        return

    demo_key = "ct_demo_key_for_testing"
    key_data = {
        "key_hash": hash_key(demo_key),
        "tier": Tier.FREE.value,
        "email": "demo@example.com",
    }

    exists = await r.exists(f"apikey:{hash_key(demo_key)}")
    if not exists:
        import json
        await r.set(f"apikey:{hash_key(demo_key)}", json.dumps(key_data))


async def validate_api_key(api_key: str = Security(api_key_header)) -> APIKeyData | None:
    """Validate API key and return key data. Returns None if no auth required."""
    if api_key is None:
        # No API key = free tier with strict limits
        return APIKeyData(
            key_hash="anonymous",
            tier=Tier.FREE,
            email="anonymous",
        )

    r = await get_redis()
    if r is None:
        # Redis down = allow request but treat as free tier
        return APIKeyData(
            key_hash=hash_key(api_key),
            tier=Tier.FREE,
            email="unknown",
        )

    import json
    key_hash = hash_key(api_key)
    data = await r.get(f"apikey:{key_hash}")

    if data is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    key_data = json.loads(data)
    return APIKeyData(
        key_hash=key_hash,
        tier=Tier(key_data["tier"]),
        email=key_data["email"],
    )


async def check_rate_limit(key_data: APIKeyData) -> None:
    """Check if the request is within rate limits."""
    r = await get_redis()
    if r is None:
        return  # Can't enforce limits without Redis

    # Daily limit
    daily_key = f"usage:daily:{key_data.key_hash}"
    daily_count = await r.get(daily_key)
    daily_count = int(daily_count) if daily_count else 0

    limit = TIER_LIMITS[key_data.tier]
    if daily_count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit reached ({limit} requests/day). Upgrade your plan for more.",
            headers={"Retry-After": "86400"},
        )

    # Increment daily counter
    pipe = r.pipeline()
    pipe.incr(daily_key)
    pipe.expire(daily_key, 86400)
    await pipe.execute()

    # Per-minute limit
    minute_key = f"usage:minute:{key_data.key_hash}"
    minute_count = await r.get(minute_key)
    minute_count = int(minute_count) if minute_count else 0

    rate_limit = TIER_RATE_LIMITS[key_data.tier]
    if minute_count >= rate_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached ({rate_limit} requests/min). Slow down.",
            headers={"Retry-After": "60"},
        )

    pipe = r.pipeline()
    pipe.incr(minute_key)
    pipe.expire(minute_key, 60)
    await pipe.execute()
