from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

INTERESTS_LIST = ["🎮 Игры", "🎵 Музыка", "🎬 Кино", "📚 Книги", "🏋️ Спорт", "✈️ Путешествия", "🍕 Еда", "💻 Технологии"]

GIFTS_DATA = {
    "rose":    {"emoji": "🌹", "name": "Роза",      "price_stars": 10, "msg": "🌹 Тебе подарили розу!"},
    "fire":    {"emoji": "🔥", "name": "Огонь",     "price_stars": 15, "msg": "🔥 Ты — огонь!"},
    "crown":   {"emoji": "👑", "name": "Корона",    "price_stars": 25, "msg": "👑 Ты — король/королева!"},
    "heart":   {"emoji": "💖", "name": "Сердце",    "price_stars": 20, "msg": "💖 Тебя любят!"},
    "diamond": {"emoji": "💎", "name": "Бриллиант", "price_stars": 50, "msg": "💎 Ты — бриллиант!"},
    "unicorn": {"emoji": "🦄", "name": "Единорог",  "price_stars": 35, "msg": "🦄 Ты уникален/уникальна!"},
}


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Найти собеседника")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💎 Premium")],
        [KeyboardButton(text="🔥 Горячие темы"), KeyboardButton(text="📖 Истории")],
    ], resize_keyboard=True)


def chat_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭ Следующий"), KeyboardButton(text="⏹ Стоп")],
        [KeyboardButton(text="🎁 Подарок"), KeyboardButton(text="⚠️ Пожаловаться")],
    ], resize_keyboard=True)


def search_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ Отменить поиск")],
    ], resize_keyboard=True)


def gender_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👨 Мужской"), KeyboardButton(text="👩 Женский")],
        [KeyboardButton(text="🤷 Не указывать")],
    ], resize_keyboard=True)


def interests_kb(selected: list = None) -> InlineKeyboardMarkup:
    selected = selected or []
    b = InlineKeyboardBuilder()
    for item in INTERESTS_LIST:
        check = "✅ " if item in selected else ""
        b.button(text=f"{check}{item}", callback_data=f"int:{item}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="✅ Готово", callback_data="int:done"))
    return b.as_markup()


def gender_filter_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👨 Парень",  callback_data="gf:male"),
        InlineKeyboardButton(text="👩 Девушка", callback_data="gf:female"),
        InlineKeyboardButton(text="🎲 Любой",   callback_data="gf:any"),
    )
    return b.as_markup()


def report_kb(session_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🤬 Оскорбления",   callback_data=f"rep:{session_id}:Оскорбления"))
    b.row(InlineKeyboardButton(text="🔞 18+ контент",   callback_data=f"rep:{session_id}:18+"))
    b.row(InlineKeyboardButton(text="🤖 Спам/реклама",  callback_data=f"rep:{session_id}:Спам"))
    b.row(InlineKeyboardButton(text="❌ Отмена",         callback_data="rep:cancel"))
    return b.as_markup()


def rate_kb(session_id: int, partner_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👍 Хорошо", callback_data=f"rate:1:{session_id}:{partner_id}"),
        InlineKeyboardButton(text="👎 Плохо",  callback_data=f"rate:-1:{session_id}:{partner_id}"),
    )
    return b.as_markup()


def gifts_kb(session_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, g in GIFTS_DATA.items():
        b.button(text=f"{g['emoji']} {g['name']}", callback_data=f"gift:{key}:{session_id}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="gifts:close"))
    return b.as_markup()


def plans_kb() -> InlineKeyboardMarkup:
    from config.config import config
    b = InlineKeyboardBuilder()
    for plan_id, p in config.PLANS.items():
        badge = f" · {p.get('badge','')}" if p.get("badge") else ""
        b.row(InlineKeyboardButton(
            text=f"{p['emoji']} {p['name']}{badge}",
            callback_data=f"plan:{plan_id}"
        ))
    b.row(InlineKeyboardButton(text="🎟 Промокод", callback_data="promo:enter"))
    return b.as_markup()


def plan_pay_kb(plan_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay:stars:{plan_id}"))
    b.row(InlineKeyboardButton(text="💎 TON",            callback_data=f"pay:ton:{plan_id}"))
    b.row(InlineKeyboardButton(text="◀️ Назад",           callback_data="premium:show"))
    return b.as_markup()
