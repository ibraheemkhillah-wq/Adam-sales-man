"""The sales agent: one call to `handle_message` per incoming customer message.

Flow: load history -> append the customer's message -> call Claude with tools in a
loop until it produces a reply -> save history -> return reply text + photos to send.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import anthropic

from app import config, notify, pricing, store
from app.erp import get_erp
from app.erp.base import BookingRequest
from app.prompt import build_system_prompt

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic()
SYSTEM_PROMPT = build_system_prompt()
TIMEZONE = ZoneInfo("Europe/Istanbul")
MAX_TOOL_ROUNDS = 8
FALLBACK_REPLY = "عذراً، صار عندي خلل بسيط 🙏 رح يتواصل معك أحد زملائي بأقرب وقت."


@dataclass
class IncomingMessage:
    customer_id: str                      # WhatsApp number (or a test id)
    text: str = ""
    customer_name: str = ""
    media: list[tuple[bytes, str]] = field(default_factory=list)  # (bytes, mime_type)


@dataclass
class AgentReply:
    text: str
    photos: list[tuple[str, str]] = field(default_factory=list)  # (url, caption)


# ---------------------------------------------------------------- tools
def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_CAR = {"type": "string", "description": "Car id from search_available_cars"}

TOOLS = [
    {
        "name": "search_available_cars",
        "description": "List cars that are free for the whole period, with their total price. "
                       "Call this before recommending or promising any car.",
        "strict": True,
        "input_schema": _schema(
            {"start_date": _DATE, "end_date": _DATE,
             "category": {"type": "string", "description": "Optional filter, e.g. SUV, اقتصادية, فخمة. Empty string for all."}},
            ["start_date", "end_date", "category"]),
    },
    {
        "name": "get_price_quote",
        "description": "Official price for one car and period (applies duration discounts and any price already agreed).",
        "strict": True,
        "input_schema": _schema({"car_id": _CAR, "start_date": _DATE, "end_date": _DATE},
                                ["car_id", "start_date", "end_date"]),
    },
    {
        "name": "evaluate_customer_offer",
        "description": "When the customer negotiates, pass the TOTAL price they offer for the rental. "
                       "Returns accept / counter_offer / final_price. Only ever quote prices this tool returns.",
        "strict": True,
        "input_schema": _schema({"car_id": _CAR, "start_date": _DATE, "end_date": _DATE,
                                 "offered_total": {"type": "number"}},
                                ["car_id", "start_date", "end_date", "offered_total"]),
    },
    {
        "name": "send_car_photos",
        "description": "Send the customer photos of a car. They are delivered right after your text reply.",
        "strict": True,
        "input_schema": _schema({"car_id": _CAR}, ["car_id"]),
    },
    {
        "name": "submit_booking_request",
        "description": "Send a booking request to the team for confirmation. Only after the customer explicitly "
                       "confirmed the summary. The price used is the official/agreed price, not one you provide.",
        "strict": True,
        "input_schema": _schema(
            {"car_id": _CAR, "start_date": _DATE, "end_date": _DATE,
             "customer_name": {"type": "string"},
             "pickup_location": {"type": "string"}, "dropoff_location": {"type": "string"},
             "notes": {"type": "string", "description": "Extras, times, flight number... Empty string if none."}},
            ["car_id", "start_date", "end_date", "customer_name", "pickup_location", "dropoff_location", "notes"]),
    },
    {
        "name": "notify_team",
        "description": "Alert the human team about this customer.",
        "strict": True,
        "input_schema": _schema(
            {"kind": {"type": "string", "enum": ["hot_lead", "human_needed", "complaint", "other"]},
             "summary": {"type": "string", "description": "Short summary in Arabic of what the team should know/do."}},
            ["kind", "summary"]),
    },
]


class ToolError(Exception):
    pass


def _dates(inp: dict) -> tuple[date, date]:
    try:
        start, end = date.fromisoformat(inp["start_date"]), date.fromisoformat(inp["end_date"])
    except ValueError as e:
        raise ToolError(f"invalid date: {e}")
    if end <= start:
        raise ToolError("end_date must be after start_date")
    if start < datetime.now(TIMEZONE).date():
        raise ToolError("start_date is in the past")
    return start, end


def _car(car_id: str):
    car = get_erp().get_car(car_id)
    if not car:
        raise ToolError(f"unknown car_id {car_id}")
    return car


async def _run_tool(name: str, inp: dict, customer_id: str, reply: AgentReply) -> dict:
    erp = get_erp()
    if name == "search_available_cars":
        start, end = _dates(inp)
        cat = inp.get("category", "").strip().lower()
        cars = [c for c in erp.available_cars(start, end) if not cat or cat in c.category.lower()]
        return {
            "currency": erp.currency,
            "available": [{**c.public_dict(), "quote": pricing.quote(customer_id, c, start, end)} for c in cars],
            "note": "" if cars else "No cars free for these dates/filter. Suggest nearby dates or another category.",
        }
    if name == "get_price_quote":
        start, end = _dates(inp)
        car = _car(inp["car_id"])
        if not erp.is_available(car.id, start, end):
            return {"available": False}
        return {"available": True, "currency": erp.currency, **pricing.quote(customer_id, car, start, end)}
    if name == "evaluate_customer_offer":
        start, end = _dates(inp)
        car = _car(inp["car_id"])
        return {"currency": erp.currency,
                **pricing.evaluate_offer(customer_id, car, start, end, float(inp["offered_total"]))}
    if name == "send_car_photos":
        car = _car(inp["car_id"])
        if not car.photos:
            return {"sent": 0, "note": "no photos on file for this car"}
        for i, url in enumerate(car.photos[:4]):
            reply.photos.append((url, car.name if i == 0 else ""))
        return {"sent": min(len(car.photos), 4)}
    if name == "submit_booking_request":
        start, end = _dates(inp)
        car = _car(inp["car_id"])
        total = pricing.booking_price(customer_id, car, start, end)
        result = erp.create_booking(BookingRequest(
            car_id=car.id, start_date=start, end_date=end, customer_name=inp["customer_name"],
            customer_phone=customer_id, total_price=total, pickup_location=inp["pickup_location"],
            dropoff_location=inp["dropoff_location"], notes=inp.get("notes", "")))
        if result.ok:
            await notify.notify("booking_request", customer_id, f"طلب حجز من {inp['customer_name']}: {car.name}", {
                "رقم الحجز": result.booking_ref, "من": start.isoformat(), "إلى": end.isoformat(),
                "المبلغ": f"{total} {erp.currency}", "الاستلام": inp["pickup_location"],
                "التسليم": inp["dropoff_location"], "ملاحظات": inp.get("notes", "") or "-"})
        return {"ok": result.ok, "status": "pending_team_confirmation" if result.ok else "failed",
                "request_ref": result.booking_ref, "total_price": total, "currency": erp.currency,
                "deposit": car.deposit, "message": result.message}
    if name == "notify_team":
        await notify.notify(inp["kind"], customer_id, inp["summary"])
        return {"notified": True}
    raise ToolError(f"unknown tool {name}")


# ---------------------------------------------------------------- message building
def _user_content(msg: IncomingMessage) -> list[dict]:
    now = datetime.now(TIMEZONE)
    content: list[dict] = [{
        "type": "text",
        "text": f"<context>now: {now:%Y-%m-%d %A %H:%M} | customer WhatsApp name: {msg.customer_name or 'unknown'}</context>",
    }]
    for data, mime in msg.media:
        b64 = base64.standard_b64encode(data).decode()
        if mime in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
        elif mime == "application/pdf":
            content.append({"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}})
        else:
            content.append({"type": "text", "text": f"[customer sent a file of type {mime} that cannot be opened]"})
    content.append({"type": "text", "text": msg.text or "[no text]"})
    return content


def _text_of(blocks) -> str:
    return "\n".join(b.text for b in blocks if b.type == "text").strip()


# ---------------------------------------------------------------- main entry
async def handle_message(msg: IncomingMessage) -> AgentReply:
    messages = store.load_messages(msg.customer_id)
    messages.append({"role": "user", "content": _user_content(msg)})
    reply = AgentReply(text="")

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
                output_config={"effort": config.CLAUDE_EFFORT},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Keep every block (thinking, fallback, tool_use) so the history stays valid.
            messages.append({"role": "assistant", "content": [b.to_dict() for b in response.content]})

            if response.stop_reason == "refusal":
                reply.text = FALLBACK_REPLY
                await notify.notify("human_needed", msg.customer_id, "البوت لم يستطع الرد على رسالة العميل")
                break
            if response.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                reply.text = _text_of(response.content)
                break

            results = []
            for tu in tool_uses:
                try:
                    out = await _run_tool(tu.name, dict(tu.input), msg.customer_id, reply)
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": json.dumps(out, ensure_ascii=False, default=str)})
                except Exception as e:  # report to the model so it can recover
                    log.warning("tool %s failed: %s", tu.name, e)
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                    "content": str(e) if isinstance(e, ToolError) else "internal error"})
            messages.append({"role": "user", "content": results})
        else:
            reply.text = FALLBACK_REPLY
    except anthropic.APIError:
        log.exception("Claude API error")
        # Do not save a half-finished turn; the customer's next message retries cleanly.
        return AgentReply(text=FALLBACK_REPLY)

    if not reply.text and not reply.photos:
        reply.text = FALLBACK_REPLY
    store.save_messages(msg.customer_id, messages, msg.customer_name)
    return reply
