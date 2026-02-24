"""
Конфигурация Anonka бота
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # ── Telegram ──────────────────────────────────────────────────────────────
    BOT_TOKEN: str       = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str    = os.getenv("BOT_USERNAME", "anonka_bezfio_bot")
    ADMIN_IDS: list      = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "8492153471").split(",") if x.strip()
    ])

    # ── База данных ────────────────────────────────────────────────────────────
    DB_DSN: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/anonka")

    # ── Webhook ────────────────────────────────────────────────────────────────
    WEBHOOK_HOST: Optional[str] = os.getenv("WEBHOOK_HOST", None)
    WEBHOOK_PATH: str           = "/webhook"
    WEB_HOST: str               = "0.0.0.0"
    WEB_PORT: int               = int(os.getenv("PORT", 8080))

    # ── TON оплата ─────────────────────────────────────────────────────────────
    TON_WALLET:  str = os.getenv("TON_WALLET", "UQDZwUwWPTFJ58IwPQGs0BKXxLTKM_-r6A6sEN8YDfq5HSOY")
    TON_API_KEY: str = os.getenv("TON_API_KEY", "")

    # ── Админ панель ───────────────────────────────────────────────────────────
    ADMIN_PANEL_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin2625")

    # ── Тарифы ────────────────────────────────────────────────────────────────
    PLANS: dict = field(default_factory=lambda: {
        "basic": {
            "name": "⚡ Базовый",
            "emoji": "⚡",
            "stars": 50,
            "ton": 0.5,
            "days": 30,
            "features": ["Без рекламы", "Безлимитные диалоги", "Фильтр по полу", "Значок ⚡ в чате"],
        },
        "pro": {
            "name": "🔥 Про",
            "emoji": "🔥",
            "stars": 125,
            "ton": 1.2,
            "days": 30,
            "badge": "ПОПУЛЯРНЫЙ",
            "features": ["Всё из Базового", "Приоритет в очереди", "Фильтр по интересам",
                         "Анонимные подарки", "Горячие темы дня", "Значок 🔥 в чате"],
        },
        "vip": {
            "name": "👑 VIP",
            "emoji": "👑",
            "stars": 300,
            "ton": 2.5,
            "days": 30,
            "badge": "МАКСИМУМ",
            "features": ["Всё из Про", "VIP значок 👑 в чате", "Анонимные истории 24ч",
                         "Приоритет ×10 в поиске", "Ранний доступ к функциям"],
        },
    })

    # ── Лимиты ────────────────────────────────────────────────────────────────
    FREE_DAILY_CHATS:  int = 20
    AD_EVERY_N_CHATS:  int = 4


config = Config()
