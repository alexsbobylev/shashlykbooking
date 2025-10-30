"""Entry point for running the Telegram bot."""
from __future__ import annotations

from .bot import build_bot_from_env


def main() -> None:  # pragma: no cover
    bot = build_bot_from_env()
    bot.run()


if __name__ == "__main__":  # pragma: no cover
    main()
