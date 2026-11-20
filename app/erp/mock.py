"""Test ERP backend that reads knowledge/fleet.yaml and keeps bookings in SQLite."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import date

import yaml

from app import config
from app.erp.base import BookingRequest, BookingResult, Car, ERPBackend


class MockERP(ERPBackend):
    def __init__(self) -> None:
        data = yaml.safe_load((config.KNOWLEDGE_DIR / "fleet.yaml").read_text(encoding="utf-8"))
        self.currency = data.get("currency", "USD")
        self._cars: dict[str, Car] = {}
        self._static_booked: dict[str, list[tuple[date, date]]] = {}
        for raw in data["cars"]:
            booked = [(_d(a), _d(b)) for a, b in raw.pop("booked", []) or []]
            car = Car(**raw)
            self._cars[car.id] = car
            self._static_booked[car.id] = booked
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS mock_bookings (
                ref TEXT PRIMARY KEY, car_id TEXT, start_date TEXT, end_date TEXT,
                customer_name TEXT, customer_phone TEXT, total_price REAL,
                pickup TEXT, dropoff TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        self._db.commit()

    def list_cars(self) -> list[Car]:
        return list(self._cars.values())

    def get_car(self, car_id: str) -> Car | None:
        return self._cars.get(car_id)

    def is_available(self, car_id: str, start: date, end: date) -> bool:
        if car_id not in self._cars:
            return False
        periods = list(self._static_booked.get(car_id, []))
        rows = self._db.execute(
            "SELECT start_date, end_date FROM mock_bookings WHERE car_id = ?", (car_id,)
        ).fetchall()
        periods += [(_d(a), _d(b)) for a, b in rows]
        return all(end < a or start > b for a, b in periods)

    def create_booking(self, req: BookingRequest) -> BookingResult:
        if not self.is_available(req.car_id, req.start_date, req.end_date):
            return BookingResult(ok=False, message="car is no longer available for these dates")
        ref = "BK-" + uuid.uuid4().hex[:6].upper()
        self._db.execute(
            "INSERT INTO mock_bookings (ref, car_id, start_date, end_date, customer_name, customer_phone,"
            " total_price, pickup, dropoff, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ref, req.car_id, req.start_date.isoformat(), req.end_date.isoformat(), req.customer_name,
             req.customer_phone, req.total_price, req.pickup_location, req.dropoff_location, req.notes),
        )
        self._db.commit()
        return BookingResult(ok=True, booking_ref=ref, message="booking created (mock ERP)")


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))
