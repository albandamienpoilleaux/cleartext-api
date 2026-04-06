import json
import stripe

from app.config import get_settings
from app.cache import get_redis
from app.auth import generate_api_key, hash_key, Tier

settings = get_settings()
stripe.api_key = settings.stripe_secret_key

# Will be set on first call via ensure_stripe_product()
_product_id: str | None = None
_price_id: str | None = None


async def ensure_stripe_product() -> tuple[str, str]:
    """Create or retrieve the ClearText Pro product and price in Stripe."""
    global _product_id, _price_id
    if _product_id and _price_id:
        return _product_id, _price_id

    # Search for existing product
    products = stripe.Product.search(query="name:'ClearText API Pro'", limit=1)
    if products.data:
        product = products.data[0]
    else:
        product = stripe.Product.create(
            name="ClearText API Pro",
            description="5,000 requests/day, JavaScript rendering, priority support",
        )

    _product_id = product.id

    # Search for existing price on this product
    prices = stripe.Price.list(product=_product_id, active=True, limit=1)
    if prices.data:
        price = prices.data[0]
    else:
        price = stripe.Price.create(
            product=_product_id,
            unit_amount=4900,  # $49.00
            currency="usd",
            recurring={"interval": "month"},
        )

    _price_id = price.id
    return _product_id, _price_id


async def create_checkout_session(base_url: str) -> str:
    """Create a Stripe Checkout session and return the URL."""
    _, price_id = await ensure_stripe_product()

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/#pricing",
    )
    return session.url


async def provision_api_key(customer_id: str, customer_email: str) -> str:
    """Generate an API key and store it in Redis for a paying customer."""
    r = await get_redis()
    api_key = generate_api_key()
    key_hash = hash_key(api_key)

    key_data = {
        "key_hash": key_hash,
        "tier": Tier.PRO.value,
        "email": customer_email,
        "stripe_customer_id": customer_id,
    }

    if r:
        await r.set(f"apikey:{key_hash}", json.dumps(key_data))
        # Also store a reverse lookup: customer_id -> key_hash
        await r.set(f"stripe_customer:{customer_id}", json.dumps({
            "key_hash": key_hash,
            "api_key_preview": f"{api_key[:7]}...{api_key[-4:]}",
        }))

    return api_key


async def revoke_api_key(customer_id: str) -> None:
    """Downgrade a customer's API key to free tier when subscription ends."""
    r = await get_redis()
    if not r:
        return

    customer_data = await r.get(f"stripe_customer:{customer_id}")
    if not customer_data:
        return

    data = json.loads(customer_data)
    key_hash = data["key_hash"]

    # Get existing key data and downgrade to free
    existing = await r.get(f"apikey:{key_hash}")
    if existing:
        key_data = json.loads(existing)
        key_data["tier"] = Tier.FREE.value
        await r.set(f"apikey:{key_hash}", json.dumps(key_data))


async def handle_webhook_event(event: dict) -> str:
    """Process a Stripe webhook event. Returns a status message."""
    event_type = event["type"]

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session["customer"]
        customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email", "unknown")

        api_key = await provision_api_key(customer_id, customer_email)

        # Store the API key temporarily so the success page can show it
        r = await get_redis()
        if r:
            await r.set(
                f"checkout_result:{session['id']}",
                json.dumps({"api_key": api_key, "email": customer_email}),
                ex=3600,  # expires in 1 hour
            )

        return f"API key provisioned for {customer_email}"

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        await revoke_api_key(customer_id)
        return f"Subscription cancelled, key downgraded for customer {customer_id}"

    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        customer_id = invoice["customer"]
        # Don't revoke immediately — Stripe retries. Just log it.
        return f"Payment failed for customer {customer_id}"

    return f"Unhandled event type: {event_type}"


async def get_checkout_result(session_id: str) -> dict | None:
    """Get the API key from a completed checkout session."""
    r = await get_redis()
    if not r:
        return None
    data = await r.get(f"checkout_result:{session_id}")
    if data:
        return json.loads(data)
    return None


async def create_portal_session(customer_id: str, base_url: str) -> str:
    """Create a Stripe Customer Portal session for managing subscription."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base_url}/",
    )
    return session.url
