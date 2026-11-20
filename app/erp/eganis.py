"""Connector for the company's eganis ERP.

Not implemented yet: the eganis API documentation (endpoints, auth, field
names) is needed first. Each method below says what it must do; the bot
keeps working on the mock backend (ERP_BACKEND=mock) until this is filled in.
"""
from __future__ import annotations

from datetime import date

from app import config
from app.erp.base import BookingRequest, BookingResult, Car, ERPBackend


class EganisERP(ERPBackend):
    def __init__(self) -> None:
        if not config.EGANIS_BASE_URL or not config.EGANIS_API_KEY:
            raise RuntimeError("EGANIS_BASE_URL and EGANIS_API_KEY must be set for ERP_BACKEND=eganis")
        self.base_url = config.EGANIS_BASE_URL.rstrip("/")

    def list_cars(self) -> list[Car]:
        # TODO: GET the fleet from eganis and map each vehicle to Car(...).
        # min_daily_price may live in eganis or stay in a local file.
        raise NotImplementedError("eganis: list_cars needs the API docs")

    def get_car(self, car_id: str) -> Car | None:
        raise NotImplementedError("eganis: get_car needs the API docs")

    def is_available(self, car_id: str, start: date, end: date) -> bool:
        # TODO: query eganis availability / reservations for this vehicle and period.
        raise NotImplementedError("eganis: is_available needs the API docs")

    def create_booking(self, req: BookingRequest) -> BookingResult:
        # TODO: POST a reservation (customer + vehicle + dates + price) and return its reference.
        raise NotImplementedError("eganis: create_booking needs the API docs")
