"""Data storage and booking logic for BBQ zone reservations."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_DATA_FILE = Path(os.getenv("BOOKING_DATA_FILE", "data/bookings.json"))


@dataclass
class Booking:
    """Represents a single booking."""

    user_id: int
    user_name: str
    booking_date: date
    slot: time

    @property
    def key(self) -> str:
        return f"{self.booking_date.isoformat()}_{self.slot.strftime('%H%M')}"

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "Booking":
        return cls(
            user_id=int(payload["user_id"]),
            user_name=payload["user_name"],
            booking_date=datetime.strptime(payload["booking_date"], "%Y-%m-%d").date(),
            slot=datetime.strptime(payload["slot"], "%H:%M").time(),
        )

    def to_dict(self) -> Dict[str, str]:
        serialised = asdict(self)
        serialised["booking_date"] = self.booking_date.isoformat()
        serialised["slot"] = self.slot.strftime("%H:%M")
        return serialised


class BookingStore:
    """A tiny JSON-backed storage for bookings."""

    def __init__(self, path: Path = DEFAULT_DATA_FILE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, str]] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        self._cache = {key: value for key, value in payload.items()}

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as fp:
            json.dump(self._cache, fp, ensure_ascii=False, indent=2)

    def add_booking(self, booking: Booking) -> None:
        key = booking.key
        self._cache[key] = booking.to_dict()
        self._save()

    def remove_booking(self, booking: Booking) -> None:
        key = booking.key
        if key in self._cache:
            del self._cache[key]
            self._save()

    def get_booking(self, booking_date: date, slot: time) -> Optional[Booking]:
        key = f"{booking_date.isoformat()}_{slot.strftime('%H%M')}"
        payload = self._cache.get(key)
        if not payload:
            return None
        return Booking.from_dict(payload)

    def bookings_for_user(self, user_id: int) -> List[Booking]:
        bookings: List[Booking] = []
        for payload in self._cache.values():
            if int(payload["user_id"]) == user_id:
                bookings.append(Booking.from_dict(payload))
        return sorted(bookings, key=lambda b: (b.booking_date, b.slot))

    def all_bookings(self) -> Iterable[Booking]:
        for payload in self._cache.values():
            yield Booking.from_dict(payload)


def generate_time_slots(
    start_hour: int = 10,
    end_hour: int = 22,
    interval_hours: int = 2,
) -> List[time]:
    """Generate time slots between `start_hour` and `end_hour` inclusive."""

    slots: List[time] = []
    current = time(hour=start_hour)
    while current < time(hour=end_hour):
        slots.append(current)
        hour = (datetime.combine(date.today(), current) + timedelta(hours=interval_hours)).time()
        current = hour
    return slots


def upcoming_dates(days: int = 7) -> List[date]:
    today = date.today()
    return [today + timedelta(days=offset) for offset in range(days)]


def format_slot(slot: time) -> str:
    return slot.strftime("%H:%M")
