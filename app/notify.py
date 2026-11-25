"""Notifications to the owner: WhatsApp message and/or a JSON webhook."""
from __future__ import annotations

import logging

import httpx

from app import config, whatsapp

log = logging.getLogger(__name__)

# Notifications raised while testing (CLI / test page) are kept here so they can be shown.
test_log: list[dict] = []

TITLES = {
    "booking_request": "📝 طلب حجز جديد — بانتظار تأكيدكم",
    "hot_lead": "🔥 عميل جاهز للشراء",
    "human_needed": "🙋 عميل يحتاج موظف بشري",
    "complaint": "⚠️ شكوى",
    "other": "ℹ️ تنبيه",
}


async def notify(kind: str, customer_id: str, summary: str, details: dict | None = None) -> None:
    event = {"kind": kind, "customer": customer_id, "summary": summary, "details": details or {}}
    test_log.append(event)
    del test_log[:-200]  # keep memory bounded
    log.info("NOTIFY %s", event)

    text = f"{TITLES.get(kind, TITLES['other'])}\nالعميل: +{customer_id}\n{summary}"
    if details:
        text += "\n" + "\n".join(f"• {k}: {v}" for k, v in details.items())

    if config.OWNER_WHATSAPP_NUMBER and whatsapp.enabled():
        try:
            await whatsapp.send_text(config.OWNER_WHATSAPP_NUMBER, text)
        except Exception:
            log.exception("owner WhatsApp notification failed")

    if config.NOTIFY_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(config.NOTIFY_WEBHOOK_URL, json=event)
        except Exception:
            log.exception("notify webhook failed")
