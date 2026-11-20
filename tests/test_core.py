"""Offline tests (no Claude / WhatsApp calls).  Run:  python -m pytest -q"""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app import pricing, store  # noqa: E402
from app.erp import get_erp  # noqa: E402
from app.erp.base import BookingRequest  # noqa: E402

START = date.today() + timedelta(days=30)


def test_fleet_loads_and_floor_hidden():
    erp = get_erp()
    car = erp.get_car("C002")
    assert car and car.daily_price == 45
    assert "min_daily_price" not in car.public_dict()


def test_duration_discount():
    car = get_erp().get_car("C002")
    q = pricing.quote("c1", car, START, START + timedelta(days=7))
    assert q["duration_discount_percent"] == 10
    assert q["total_price"] == 284  # ceil(45*7*0.9)


def test_negotiation_never_below_floor():
    car = get_erp().get_car("C002")
    end = START + timedelta(days=3)  # list 135, floor 111
    seen = []
    for _ in range(10):
        r = pricing.evaluate_offer("c2", car, START, end, 50)
        seen.append(r)
        if r["decision"] == "final_price":
            break
    assert seen[-1]["decision"] == "final_price"
    assert seen[-1]["counter_total"] == 111
    counters = [r["counter_total"] for r in seen]
    assert counters == sorted(counters, reverse=True) and min(counters) >= 111
    assert pricing.booking_price("c2", car, START, end) == 111


def test_reasonable_offer_accepted():
    car = get_erp().get_car("C002")
    end = START + timedelta(days=3)
    r = pricing.evaluate_offer("c3", car, START, end, 130)  # first step price is 127
    assert r["decision"] == "accept" and r["agreed_total"] == 130
    assert pricing.booking_price("c3", car, START, end) == 130


def test_booking_blocks_availability():
    erp = get_erp()
    s, e = START + timedelta(days=100), START + timedelta(days=103)
    assert erp.is_available("C004", s, e)
    res = erp.create_booking(BookingRequest("C004", s, e, "Ali", "905", 330))
    assert res.ok and res.booking_ref.startswith("BK-")
    assert not erp.is_available("C004", s + timedelta(days=1), e + timedelta(days=1))
    assert not erp.create_booking(BookingRequest("C004", s, e, "B", "906", 330)).ok


def test_dedupe():
    assert store.mark_processed("wamid.1")
    assert not store.mark_processed("wamid.1")
