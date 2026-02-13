from __future__ import annotations

import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ReservationRequest(Base):
    __tablename__ = "reservation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_name: Mapped[str] = mapped_column(String(255))
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    time: Mapped[str] = mapped_column(String(5))  # HH:MM
    party_size: Mapped[int] = mapped_column(Integer)
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    # pending → searching → booked                          (immediate success)
    # pending → searching → waiting → polling → booked      (sniper success)
    # pending → searching → waiting → polling → failed       (sniper timeout)
    # pending → searching → no_availability                  (no open time, nothing found)
    # any → cancelled
    venue_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="")
    booking_open_time: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True, default=None
    )
    poll_attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_poll_duration_secs: Mapped[int] = mapped_column(Integer, default=300)
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    subscriptions: Mapped[List["NotificationSubscription"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    bookings: Mapped[List["Booking"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    logs: Mapped[List["ActivityLog"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("reservation_requests.id"))
    platform: Mapped[str] = mapped_column(String(50))  # resy | opentable
    subscribed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    search_date: Mapped[str] = mapped_column(String(10))
    search_time: Mapped[str] = mapped_column(String(5))
    search_party_size: Mapped[int] = mapped_column(Integer)
    restaurant_name: Mapped[str] = mapped_column(String(255), default="")
    venue_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    request: Mapped["ReservationRequest"] = relationship(back_populates="subscriptions")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("reservation_requests.id"))
    platform: Mapped[str] = mapped_column(String(50))
    confirmation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    restaurant_name: Mapped[str] = mapped_column(String(255))
    date: Mapped[str] = mapped_column(String(10))
    time: Mapped[str] = mapped_column(String(5))
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="confirmed")
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    request: Mapped["ReservationRequest"] = relationship(back_populates="bookings")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reservation_requests.id"), nullable=True
    )
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    action: Mapped[str] = mapped_column(String(100))
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string

    request: Mapped[Optional["ReservationRequest"]] = relationship(back_populates="logs")
