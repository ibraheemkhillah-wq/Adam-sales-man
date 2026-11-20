"""Minimal WhatsApp Cloud API (Meta) client."""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from app import config

log = logging.getLogger(__name__)


def _base() -> str:
    return f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def enabled() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Checks X-Hub-Signature-256 so only Meta can post to the webhook."""
    if not config.WHATSAPP_APP_SECRET:
        log.warning("WHATSAPP_APP_SECRET not set - webhook signature NOT verified")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(config.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


async def _post(payload: dict) -> dict:
    url = f"{_base()}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=_headers(), json={"messaging_product": "whatsapp", **payload})
    if r.status_code >= 400:
        log.error("WhatsApp API error %s: %s", r.status_code, r.text)
    return r.json() if r.content else {}


async def send_text(to: str, text: str) -> dict:
    return await _post({"to": to, "type": "text", "text": {"body": text, "preview_url": True}})


async def send_image(to: str, link: str, caption: str = "") -> dict:
    image = {"link": link}
    if caption:
        image["caption"] = caption
    return await _post({"to": to, "type": "image", "image": image})


async def mark_read_and_typing(message_id: str) -> None:
    """Shows blue ticks and the 'typing...' indicator while the bot thinks."""
    await _post({"status": "read", "message_id": message_id, "typing_indicator": {"type": "text"}})


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Returns (bytes, mime_type) for an image/document the customer sent."""
    async with httpx.AsyncClient(timeout=60) as client:
        meta = (await client.get(f"{_base()}/{media_id}", headers=_headers())).json()
        r = await client.get(meta["url"], headers=_headers())
        r.raise_for_status()
        return r.content, meta.get("mime_type", "application/octet-stream")
