"""Web server: WhatsApp webhook + a password-protected test chat page.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from collections import defaultdict

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse

from app import config, notify, store, whatsapp
from app.agent import IncomingMessage, handle_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("adam")

app = FastAPI(title="Adam sales bot")
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # one turn at a time per customer


@app.get("/")
def health():
    return {"status": "ok", "erp": config.ERP_BACKEND, "whatsapp": whatsapp.enabled()}


# ------------------------------------------------------------------ WhatsApp webhook
@app.get("/webhook")
def verify(request: Request):
    p = request.query_params
    token = p.get("hub.verify_token", "")
    if (p.get("hub.mode") == "subscribe" and config.WHATSAPP_VERIFY_TOKEN
            and hmac.compare_digest(token, config.WHATSAPP_VERIFY_TOKEN)):
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not whatsapp.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401)
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if store.mark_processed(m["id"]):
                    background.add_task(_process_whatsapp, m, names.get(m.get("from"), ""))
    return {"ok": True}  # answer Meta immediately; the reply is sent in the background


async def _process_whatsapp(m: dict, name: str) -> None:
    customer = m["from"]
    try:
        await whatsapp.mark_read_and_typing(m["id"])
        msg = IncomingMessage(customer_id=customer, customer_name=name)
        kind = m.get("type")
        if kind == "text":
            msg.text = m["text"]["body"]
        elif kind in ("image", "document", "sticker"):
            media = m[kind]
            msg.text = media.get("caption", "")
            msg.media.append(await whatsapp.download_media(media["id"]))
        elif kind == "location":
            loc = m["location"]
            msg.text = f"[customer shared a location: {loc.get('name', '')} {loc.get('address', '')} " \
                       f"({loc.get('latitude')}, {loc.get('longitude')})]"
        elif kind in ("audio", "voice"):
            msg.text = "[customer sent a voice note, which cannot be listened to. Politely ask them to type the message.]"
        elif kind == "button":
            msg.text = m["button"].get("text", "")
        elif kind == "interactive":
            it = m["interactive"]
            msg.text = (it.get("button_reply") or it.get("list_reply") or {}).get("title", "")
        else:
            msg.text = f"[customer sent an unsupported message type: {kind}]"

        if store.is_paused(customer):
            return
        async with _locks[customer]:
            reply = await handle_message(msg)
        if reply.text:
            await whatsapp.send_text(customer, reply.text)
        for url, caption in reply.photos:
            await whatsapp.send_image(customer, url, caption)
    except Exception:
        log.exception("failed to handle WhatsApp message from %s", customer)


# ------------------------------------------------------------------ test page
def _check(password: str) -> None:
    if config.TEST_PAGE_PASSWORD in ("", "change-me"):
        raise HTTPException(403, "set TEST_PAGE_PASSWORD in .env first")
    if not hmac.compare_digest(password, config.TEST_PAGE_PASSWORD):
        raise HTTPException(401, "wrong password")


@app.get("/test", response_class=HTMLResponse)
def test_page():
    return (config.ROOT / "app" / "static" / "test.html").read_text(encoding="utf-8")


@app.post("/test/api/chat")
async def test_chat(password: str = Form(...), session: str = Form(...), text: str = Form(""),
                    name: str = Form(""), file: UploadFile | None = File(None)):
    _check(password)
    customer = f"test-{session}"
    msg = IncomingMessage(customer_id=customer, text=text, customer_name=name)
    if file is not None and file.filename:
        msg.media.append((await file.read(), file.content_type or "application/octet-stream"))
    before = len(notify.test_log)
    async with _locks[customer]:
        reply = await handle_message(msg)
    return {"text": reply.text, "photos": [u for u, _ in reply.photos],
            "notifications": notify.test_log[before:]}


@app.post("/test/api/reset")
def test_reset(password: str = Form(...), session: str = Form(...)):
    _check(password)
    store.reset_conversation(f"test-{session}")
    return {"ok": True}
