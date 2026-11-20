"""Price quotes and negotiation, enforced in code.

The model never sees a car's floor price. It asks these functions for a quote
or to evaluate a customer's offer, and gets back what it may say. A booking is
always created at the price recorded here, never at a price the model types.
"""
from __future__ import annotations

import math
from datetime import date

import yaml

from app import config, store
from app.erp.base import Car

_rules = yaml.safe_load((config.KNOWLEDGE_DIR / "pricing.yaml").read_text(encoding="utf-8"))
STEPS = max(1, int(_rules.get("negotiation", {}).get("steps", 3)))


def rental_days(start: date, end: date) -> int:
    return max(1, (end - start).days)


def _duration_discount(days: int) -> int:
    pct = 0
    for rule in sorted(_rules.get("duration_discounts", []), key=lambda r: r["min_days"]):
        if days >= rule["min_days"]:
            pct = rule["percent"]
    return pct


def _prices(car: Car, days: int) -> tuple[float, float, int]:
    """(list_total after duration discount, floor_total, discount_percent)."""
    pct = _duration_discount(days)
    list_total = math.ceil(car.daily_price * days * (100 - pct) / 100)
    floor_total = min(list_total, math.ceil(car.min_daily_price * days))
    return list_total, floor_total, pct


def _price_at_step(list_total: float, floor_total: float, step: int) -> float:
    step = min(step, STEPS)
    return math.ceil(list_total - (list_total - floor_total) * step / STEPS)


def quote(customer_id: str, car: Car, start: date, end: date) -> dict:
    days = rental_days(start, end)
    list_total, floor_total, pct = _prices(car, days)
    step, agreed = store.get_negotiation(customer_id, car.id, start.isoformat(), end.isoformat())
    current = agreed if agreed is not None else _price_at_step(list_total, floor_total, step)
    return {
        "car": car.name,
        "days": days,
        "daily_price": car.daily_price,
        "duration_discount_percent": pct,
        "total_price": current,
        "deposit": car.deposit,
        "price_already_agreed": agreed is not None,
    }


def evaluate_offer(customer_id: str, car: Car, start: date, end: date, offered_total: float) -> dict:
    s, e = start.isoformat(), end.isoformat()
    days = rental_days(start, end)
    list_total, floor_total, _ = _prices(car, days)
    step, agreed = store.get_negotiation(customer_id, car.id, s, e)

    if agreed is not None and offered_total >= agreed:
        return {"decision": "accept", "agreed_total": agreed, "note": "price was already agreed"}

    current = _price_at_step(list_total, floor_total, step)
    if offered_total >= current:
        agreed = math.ceil(offered_total)
        store.set_negotiation(customer_id, car.id, s, e, step, agreed)
        return {"decision": "accept", "agreed_total": agreed}

    if step >= STEPS:
        store.set_negotiation(customer_id, car.id, s, e, step, floor_total)
        return {
            "decision": "final_price",
            "counter_total": floor_total,
            "note": "This is the lowest possible price. Do not offer anything lower; you may offer "
                    "non-price value instead (free delivery, extra driver) only if company info allows it.",
        }

    step += 1
    counter = _price_at_step(list_total, floor_total, step)
    if offered_total >= counter:
        agreed = math.ceil(offered_total)
        store.set_negotiation(customer_id, car.id, s, e, step, agreed)
        return {"decision": "accept", "agreed_total": agreed}
    is_last = step >= STEPS
    store.set_negotiation(customer_id, car.id, s, e, step, counter if is_last else None)
    return {
        "decision": "counter_offer",
        "counter_total": counter,
        "concessions_left": STEPS - step,
        "note": "Present the counter offer as a special favour. Do not mention how many concessions are left.",
    }


def booking_price(customer_id: str, car: Car, start: date, end: date) -> float:
    """The price a booking is created at: the agreed price, else the current step price."""
    s, e = start.isoformat(), end.isoformat()
    step, agreed = store.get_negotiation(customer_id, car.id, s, e)
    if agreed is not None:
        return agreed
    list_total, floor_total, _ = _prices(car, rental_days(start, end))
    return _price_at_step(list_total, floor_total, step)
