"""Telegram bot implementation for BBQ zone booking."""
from __future__ import annotations

import logging
import os
from datetime import date, time
from typing import List

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .storage import Booking, BookingStore, format_slot, generate_time_slots, upcoming_dates

logger = logging.getLogger(__name__)

BOOKING_PREFIX = "BOOK"
DAY_PREFIX = "DAY"
CANCEL_PREFIX = "CANCEL"


class BookingBot:
    """Encapsulates Telegram bot setup and handlers."""

    def __init__(self, token: str, store: BookingStore | None = None) -> None:
        self.store = store or BookingStore()
        self.application: Application = (
            ApplicationBuilder()
            .token(token)
            .rate_limiter(AIORateLimiter())
            .post_init(self._post_init)
            .build()
        )

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("my", self.my_bookings))
        self.application.add_handler(CallbackQueryHandler(self.handle_callbacks))

    async def _post_init(self, application: Application) -> None:  # pragma: no cover - side effects
        logger.info("Bot initialised with username: %s", application.bot.username)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.effective_chat
        keyboard = [
            [InlineKeyboardButton("📅 Забронировать", callback_data=f"{DAY_PREFIX}:ROOT")],
            [InlineKeyboardButton("🗂 Мои брони", callback_data=f"{BOOKING_PREFIX}:LIST")],
        ]
        await update.message.reply_text(
            "Привет! Я помогу забронировать зону для шашлыка. Выберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Используйте /start для открытия меню. Команда /my покажет ваши брони."
        )

    async def my_bookings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        bookings = self.store.bookings_for_user(user.id)
        if not bookings:
            text = "У вас пока нет броней."
        else:
            lines = ["<b>Ваши брони:</b>"]
            for booking in bookings:
                lines.append(
                    f"• {booking.booking_date.strftime('%d.%m.%Y')} в {format_slot(booking.slot)}"
                )
            text = "\n".join(lines)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    async def handle_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.callback_query:
            return
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        if data.startswith(f"{DAY_PREFIX}:"):
            await self._show_days(query)
        elif data.startswith(f"{BOOKING_PREFIX}:"):
            payload = data.split(":", maxsplit=1)[1]
            if payload == "LIST":
                await self._send_my_bookings(query)
            else:
                await self._handle_slot_selection(query, payload)
        elif data.startswith(f"{CANCEL_PREFIX}:"):
            await self._cancel_booking(query, data.split(":", maxsplit=1)[1])

    async def _show_days(self, query) -> None:
        payload = (query.data or "").split(":", maxsplit=1)[1]
        if payload == "ROOT":
            keyboard = []
            for day in upcoming_dates():
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            day.strftime("%a %d.%m"),
                            callback_data=f"{DAY_PREFIX}:{day.isoformat()}",
                        )
                    ]
                )
            keyboard.append(
                [InlineKeyboardButton("⬅️ Меню", callback_data=f"{BOOKING_PREFIX}:LIST")]
            )
            await query.edit_message_text(
                "Выберите дату:", reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        selected_date = date.fromisoformat(payload)
        await query.edit_message_text(
            text=f"Доступные слоты на {selected_date.strftime('%d.%m.%Y')}:",
            reply_markup=self.build_day_keyboard(selected_date),
        )

    async def _send_my_bookings(self, query) -> None:
        user = query.from_user
        bookings = self.store.bookings_for_user(user.id)
        if not bookings:
            text = "У вас пока нет броней."
            keyboard = [
                [InlineKeyboardButton("📅 Забронировать", callback_data=f"{DAY_PREFIX}:ROOT")]
            ]
        else:
            lines = ["<b>Ваши брони:</b>"]
            keyboard = []
            for booking in bookings:
                lines.append(
                    f"• {booking.booking_date.strftime('%d.%m.%Y')} в {format_slot(booking.slot)}"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"Отменить {booking.booking_date.strftime('%d.%m')} {format_slot(booking.slot)}",
                            callback_data=f"{CANCEL_PREFIX}:{booking.key}",
                        )
                    ]
                )
        keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data=f"{DAY_PREFIX}:ROOT")])
        await query.edit_message_text(
            "\n".join(lines) if bookings else text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )

    async def _handle_slot_selection(self, query, payload: str) -> None:
        if payload == "ROOT":
            await self._show_days(query)
            return

        if payload.count("|") != 1:
            return
        day_str, slot_str = payload.split("|", maxsplit=1)
        booking_date = date.fromisoformat(day_str)
        slot = time.fromisoformat(slot_str)

        if self.store.get_booking(booking_date, slot):
            await query.edit_message_text(
                "Увы, этот слот уже занят. Попробуйте выбрать другое время.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Назад", callback_data=f"{DAY_PREFIX}:{day_str}")]]
                ),
            )
            return

        user = query.from_user
        booking = Booking(
            user_id=user.id,
            user_name=user.full_name,
            booking_date=booking_date,
            slot=slot,
        )
        self.store.add_booking(booking)

        await query.edit_message_text(
            (
                "🎉 Бронирование подтверждено!\n"
                f"Дата: {booking_date.strftime('%d.%m.%Y')}\n"
                f"Время: {format_slot(slot)}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Мои брони", callback_data=f"{BOOKING_PREFIX}:LIST")]]
            ),
        )

    async def _cancel_booking(self, query, booking_key: str) -> None:
        stored = self.store._cache.get(booking_key)
        if not stored:
            await query.edit_message_text(
                "Бронь уже была удалена.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Меню", callback_data=f"{DAY_PREFIX}:ROOT")]]
                ),
            )
            return
        booking = Booking.from_dict(stored)
        if booking.user_id != query.from_user.id:
            await query.edit_message_text("Вы не можете отменить чужую бронь.")
            return
        self.store.remove_booking(booking)
        await query.edit_message_text(
            "Бронь отменена.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Меню", callback_data=f"{DAY_PREFIX}:ROOT")]]
            ),
        )

    def build_day_keyboard(self, day: date) -> InlineKeyboardMarkup:
        buttons: List[List[InlineKeyboardButton]] = []
        for slot in generate_time_slots():
            booking = self.store.get_booking(day, slot)
            label = f"{format_slot(slot)} {'❌' if booking else '✅'}"
            buttons.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=(
                            f"{BOOKING_PREFIX}:{day.isoformat()}|{slot.strftime('%H:%M')}"
                        ),
                    )
                ]
            )
        buttons.append(
            [InlineKeyboardButton("⬅️ Дни", callback_data=f"{DAY_PREFIX}:ROOT")]
        )
        return InlineKeyboardMarkup(buttons)

    async def send_day_schedule(self, update: Update, day: date) -> None:
        slots_markup = self.build_day_keyboard(day)
        await update.effective_chat.send_message(
            text=f"Доступные слоты на {day.strftime('%d.%m.%Y')}:",
            reply_markup=slots_markup,
        )

    def run(self) -> None:  # pragma: no cover - entry point
        self.application.run_polling()


def build_bot_from_env() -> BookingBot:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN environment variable is not set")
    return BookingBot(token=token)
