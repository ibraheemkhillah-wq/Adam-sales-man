"""The interface every ERP backend implements.

The sales agent only talks to this interface, so switching from the mock
backend to the real eganis system means writing one class (see eganis.py)
without touching the bot.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Car:
    id: str
    name: str
    year: int
    category: str
    transmission: str
    fuel: str
    seats: int
    daily_price: float
    min_daily_price: float  # negotiation floor - never shown to the model
    deposit: float
    photos: list[str] = field(default_factory=list)

    def public_dict(self) -> dict:
        """What the model is allowed to see (no floor price)."""
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "category": self.category,
            "transmission": self.transmission,
            "fuel": self.fuel,
            "seats": self.seats,
            "daily_price": self.daily_price,
            "deposit": self.deposit,
            "photos_available": len(self.photos),
        }


@dataclass
class BookingRequest:
    car_id: str
    start_date: date
    end_date: date
    customer_name: str
    customer_phone: str
    total_price: float
    pickup_location: str = ""
    dropoff_location: str = ""
    notes: str = ""


@dataclass
class BookingResult:
    ok: bool
    booking_ref: str = ""
    message: str = ""


class ERPBackend(ABC):
    currency: str = "USD"

    @abstractmethod
    def list_cars(self) -> list[Car]: ...

    @abstractmethod
    def get_car(self, car_id: str) -> Car | None: ...

    @abstractmethod
    def is_available(self, car_id: str, start: date, end: date) -> bool: ...

    @abstractmethod
    def create_booking(self, req: BookingRequest) -> BookingResult: ...

    def available_cars(self, start: date, end: date) -> list[Car]:
        return [c for c in self.list_cars() if self.is_available(c.id, start, end)]
