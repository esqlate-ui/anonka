"""
Основные хэндлеры — поиск, чат, профиль, регистрация
"""
from __future__ import annotations
import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.config import config
from database import db
from bot.keyboards.keyboards import (
    main_menu, chat_kb, search_kb, gender_kb,
    interests_kb, report_kb, rate_kb, gender_filter_kb, gifts_kb
)

router = Router()
logger = logging.getLogger(__name__)

# Активные чаты: {user_id: {"session_id": int, "partner_id": int}}
active_chats: dict[int, dict] = {}

# Устанавливается из main.py после инициализации storage
# Используется в _end_chat для сброса FSM state партнёра без хендлер-контекста
_set_fsm_state_fn = None  # callable(user_id, state_val) -> coroutine


class UserStates(StatesGroup):
    reg_gender    = State()
    reg_interests = State()
    in_queue      = State()
    in_chat       = State()
    enter_promo   = State()
    write_story   = State()


# ── Утилиты ───────────────────────────────────────────────────────────────────

def badge(user: dict) -> str:
    p = user.get("premium_plan")
    if p == "vip":   return "👑 "
    if p == "pro":   return "🔥 "
    if p == "basic": return "⚡ "
    return ""


def is_premium_active(user: dict) -> bool:
    if not user.get("is_premium"):
        return False
    until = user.get("premium_until")
    if until is None:
        return True
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > now


async def notify_achievements(bot: Bot, user_id: int):
    new = await db.check_achievements(user_id)
    for code in new:
        emoji, name, desc, xp = db.ACHIEVEMENTS.get(code, ("🏆", code, "", 0))
        try:
            await bot.send_message(
                user_id,
                f"🏆 *Новое достижение!*\n\n{emoji} *{name}*\n_{desc}_\n+{xp} XP",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def show_ad(bot: Bot, user_id: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    try:
        await bot.send_message(
            user_id,
            "💬 *Реклама*\n\nОбщайся без ограничений — оформи *Anonka Premium* и забудь про рекламу! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💎 Узнать о Premium", callback_data="premium:show")
            ]])
        )
    except Exception:
        pass


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, bot: Bot):
    uid = message.from_user.id

    # Если был в очереди — убираем
    await db.remove_from_queue(uid)

    # Если был в чате — завершаем сессию и уведомляем партнёра
    if uid in active_chats:
        info       = active_chats.pop(uid)
        partner_id = info["partner_id"]
        await db.end_session(info["session_id"], ended_by=uid)
        active_chats.pop(partner_id, None)
        # Сбрасываем FSM state партнёра
        if _set_fsm_state_fn is not None:
            await _set_fsm_state_fn(partner_id, None)
        try:
            await bot.send_message(
                partner_id,
                "❌ Собеседник покинул чат.",
                reply_markup=main_menu()
            )
        except Exception:
            pass

    await state.clear()

    args = command.args or ""
    ref  = args if args and not args.startswith("premium") else None

    user = await db.get_or_create_user(
        uid,
        message.from_user.username or "",
        message.from_user.first_name or "Аноним",
        ref
    )

    if user["is_banned"]:
        await message.answer(
            f"🚫 Ваш аккаунт заблокирован.\nПричина: {user.get('ban_reason') or 'нарушение правил'}"
        )
        return

    if user.get("gender") is not None:
        b        = badge(user)
        plan_txt = f"\n💎 Тариф: *{user['premium_plan'].upper()}*" if user.get("premium_plan") else ""
        await message.answer(
            f"👋 С возвращением, {b}*{message.from_user.first_name}*!\n\n"
            f"⭐ Рейтинг: *{user['rating']:.1f}* | 💬 Диалогов: *{user['total_chats']}* | ⚡ XP: *{user['xp']}*"
            f"{plan_txt}",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    await message.answer(
        "👋 Добро пожаловать в *Anonka*!\n\n"
        "🎭 Анонимный чат — никто не знает кто ты.\n"
        "Только твои слова.\n\n"
        "Укажи свой пол для начала:",
        parse_mode="Markdown", reply_markup=gender_kb()
    )
    await state.set_state(UserStates.reg_gender)


# ── Регистрация ───────────────────────────────────────────────────────────────

@router.message(UserStates.reg_gender)
async def reg_gender(message: Message, state: FSMContext):
    gmap = {"👨 Мужской": "male", "👩 Женский": "female", "🤷 Не указывать": None}
    if message.text not in gmap:
        await message.answer("Выбери вариант ↓", reply_markup=gender_kb())
        return
    await db.update_user(message.from_user.id, gender=gmap[message.text])
    await state.update_data(sel_interests=[])
    await message.answer(
        "🎯 Выбери интересы — будем подбирать похожих собеседников.\n_(можно пропустить — Готово)_",
        parse_mode="Markdown", reply_markup=interests_kb([])
    )
    await state.set_state(UserStates.reg_interests)


@router.callback_query(UserStates.reg_interests, F.data.startswith("int:"))
async def reg_interests(callback: CallbackQuery, state: FSMContext):
    val  = callback.data[4:]
    data = await state.get_data()
    sel  = data.get("sel_interests", [])
    if val == "done":
        await db.update_user(callback.from_user.id, interests=sel)
        await state.clear()
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "✅ *Готово! Ты зарегистрирован в Anonka.*\n\n"
            "Нажми *🔍 Найти собеседника* чтобы начать!",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return
    if val in sel:
        sel.remove(val)
    else:
        sel.append(val)
    await state.update_data(sel_interests=sel)
    await callback.message.edit_reply_markup(reply_markup=interests_kb(sel))
    await callback.answer()


# ── Поиск ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "🔍 Найти собеседника")
async def start_search(message: Message, state: FSMContext, bot: Bot):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Нажми /start")
        return
    if user["is_banned"]:
        await message.answer("🚫 Вы заблокированы.")
        return
    if message.from_user.id in active_chats:
        await message.answer("⚠️ Ты уже в чате! Нажми ⏹ Стоп.", reply_markup=chat_kb())
        return
    if await db.in_queue(message.from_user.id):
        await message.answer("⏳ Ты уже в поиске...", reply_markup=search_kb())
        return

    # Проверка дневного лимита для бесплатных
    if not is_premium_active(user):
        if user.get("daily_chats", 0) >= config.FREE_DAILY_CHATS:
            await message.answer(
                f"⚠️ Ты достиг дневного лимита *{config.FREE_DAILY_CHATS} диалогов*.\n\n"
                f"Оформи Premium для безлимитного общения! 💎",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            return

    premium = is_premium_active(user)
    if premium:
        await message.answer("🔍 Кого ищем?", reply_markup=gender_filter_kb())
        await state.set_state(UserStates.in_queue)
        await state.update_data(waiting_gf=True)
    else:
        await _begin_search(message.from_user.id, state, bot, user, gender_filter=None)


@router.callback_query(UserStates.in_queue, F.data.startswith("gf:"))
async def gender_filter_chosen(callback: CallbackQuery, state: FSMContext, bot: Bot):
    gf            = callback.data[3:]
    gender_filter = None if gf == "any" else gf
    user          = await db.get_user(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _begin_search(callback.from_user.id, state, bot, user, gender_filter=gender_filter)


async def _begin_search(user_id: int, state: FSMContext, bot: Bot,
                         user: dict, gender_filter: str = None):
    premium = is_premium_active(user)
    await db.add_to_queue(
        user_id,
        gender_filter=gender_filter,
        interests=user.get("interests", []),
        is_premium=premium
    )
    await state.set_state(UserStates.in_queue)
    await state.update_data(gender_filter=gender_filter)
    await bot.send_message(
        user_id,
        "🔍 *Ищем собеседника...*\nПодожди немного.",
        parse_mode="Markdown", reply_markup=search_kb()
    )


@router.message(F.text == "❌ Отменить поиск")
async def cancel_search(message: Message, state: FSMContext):
    await db.remove_from_queue(message.from_user.id)
    await state.clear()
    await message.answer("❌ Поиск отменён.", reply_markup=main_menu())


# ── Сообщения в чате ──────────────────────────────────────────────────────────

@router.message(UserStates.in_chat)
async def chat_message(message: Message, state: FSMContext, bot: Bot):
    uid  = message.from_user.id
    info = active_chats.get(uid)
    if not info:
        # Состояние зависло — сбрасываем
        await state.clear()
        await message.answer("❌ Чат завершён.", reply_markup=main_menu())
        return

    partner_id = info["partner_id"]
    session_id = info["session_id"]

    # ── Управляющие кнопки ────────────────────────────────────────────────────
    if message.text == "⏹ Стоп":
        await _end_chat(uid, partner_id, session_id, bot, state, ended_by=uid)
        return
    if message.text == "⏭ Следующий":
        await _end_chat(uid, partner_id, session_id, bot, state, ended_by=uid)
        await asyncio.sleep(0.3)
        user = await db.get_user(uid)
        if user:
            # Проверяем дневной лимит перед следующим поиском
            if not is_premium_active(user) and user.get("daily_chats", 0) >= config.FREE_DAILY_CHATS:
                await bot.send_message(
                    uid,
                    f"⚠️ Достигнут дневной лимит *{config.FREE_DAILY_CHATS} диалогов*.\n\n"
                    "Оформи Premium для безлимитного общения! 💎",
                    parse_mode="Markdown", reply_markup=main_menu()
                )
            else:
                await _begin_search(uid, state, bot, user)
        return
    if message.text == "⚠️ Пожаловаться":
        await message.answer("⚠️ *Причина жалобы:*", parse_mode="Markdown",
                             reply_markup=report_kb(session_id))
        return
    if message.text == "🎁 Подарок":
        user = await db.get_user(uid)
        if not user or not is_premium_active(user) or user.get("premium_plan") not in ("pro", "vip"):
            await message.answer(
                "🎁 Подарки доступны с тарифа *Про* и выше.", parse_mode="Markdown"
            )
            return
        await message.answer(
            "🎁 *Выбери анонимный подарок:*\n_Собеседник не узнает от кого_",
            parse_mode="Markdown", reply_markup=gifts_kb(session_id)
        )
        return

    # ── Пересылка медиа ───────────────────────────────────────────────────────
    try:
        if message.text:
            await db.log_message(session_id, uid, "text", text=message.text)
            await bot.send_message(partner_id, message.text)
        elif message.photo:
            f = message.photo[-1]
            await db.log_message(session_id, uid, "photo",
                                  file_id=f.file_id, file_unique_id=f.file_unique_id,
                                  caption=message.caption)
            await bot.send_photo(partner_id, f.file_id, caption=message.caption or "")
        elif message.video:
            await db.log_message(session_id, uid, "video",
                                  file_id=message.video.file_id,
                                  file_unique_id=message.video.file_unique_id,
                                  caption=message.caption)
            await bot.send_video(partner_id, message.video.file_id, caption=message.caption or "")
        elif message.voice:
            await db.log_message(session_id, uid, "voice",
                                  file_id=message.voice.file_id,
                                  file_unique_id=message.voice.file_unique_id)
            await bot.send_voice(partner_id, message.voice.file_id)
        elif message.video_note:
            await db.log_message(session_id, uid, "video_note",
                                  file_id=message.video_note.file_id,
                                  file_unique_id=message.video_note.file_unique_id)
            await bot.send_video_note(partner_id, message.video_note.file_id)
        elif message.sticker:
            await db.log_message(session_id, uid, "sticker",
                                  file_id=message.sticker.file_id,
                                  file_unique_id=message.sticker.file_unique_id)
            await bot.send_sticker(partner_id, message.sticker.file_id)
        elif message.document:
            await db.log_message(session_id, uid, "document",
                                  file_id=message.document.file_id,
                                  file_unique_id=message.document.file_unique_id,
                                  caption=message.caption)
            await bot.send_document(partner_id, message.document.file_id, caption=message.caption or "")
        elif message.audio:
            await db.log_message(session_id, uid, "audio",
                                  file_id=message.audio.file_id,
                                  file_unique_id=message.audio.file_unique_id,
                                  caption=message.caption)
            await bot.send_audio(partner_id, message.audio.file_id, caption=message.caption or "")
        elif message.animation:
            await db.log_message(session_id, uid, "animation",
                                  file_id=message.animation.file_id,
                                  file_unique_id=message.animation.file_unique_id)
            await bot.send_animation(partner_id, message.animation.file_id)
        else:
            await message.answer("⚠️ Этот тип файла не поддерживается.")
    except Exception as e:
        logger.warning(f"Ошибка пересылки {uid}→{partner_id}: {e}")
        await message.answer("❌ Собеседник недоступен.")
        await _end_chat(uid, partner_id, session_id, bot, state, ended_by=uid, silent=True)


async def _end_chat(uid: int, partner_id: int, session_id: int,
                    bot: Bot, state: FSMContext,
                    ended_by: int = None, silent: bool = False):
    """Завершает чат для обоих участников, сбрасывает FSM state у партнёра."""
    await db.end_session(session_id, ended_by)
    active_chats.pop(uid, None)
    active_chats.pop(partner_id, None)

    # Сбрасываем state инициатора через контекст
    await state.clear()

    # Сбрасываем state партнёра напрямую через storage (если функция зарегистрирована)
    if _set_fsm_state_fn is not None:
        await _set_fsm_state_fn(partner_id, None)

    # Уведомляем инициатора
    try:
        await bot.send_message(
            uid, "💬 *Диалог завершён.*\nОцени собеседника:",
            parse_mode="Markdown", reply_markup=rate_kb(session_id, partner_id)
        )
        await asyncio.sleep(0.3)
        await bot.send_message(uid, "Что дальше?", reply_markup=main_menu())
    except Exception:
        pass

    # Уведомляем партнёра
    if not silent:
        try:
            await bot.send_message(
                partner_id, "💬 *Собеседник завершил диалог.*\nОцени его:",
                parse_mode="Markdown", reply_markup=rate_kb(session_id, uid)
            )
            await asyncio.sleep(0.3)
            await bot.send_message(partner_id, "Что дальше?", reply_markup=main_menu())
        except Exception:
            pass

    # Достижения и реклама
    await notify_achievements(bot, uid)
    try:
        user = await db.get_user(uid)
        if user and not is_premium_active(user):
            chats_since = user.get("chats_since_ad", 0)
            if chats_since > 0 and chats_since % config.AD_EVERY_N_CHATS == 0:
                await show_ad(bot, uid)
                # Сбрасываем счётчик после показа
                await db.update_user(uid, chats_since_ad=0)
    except Exception:
        pass


# ── Жалобы ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rep:"))
async def handle_report(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if parts[1] == "cancel":
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    session_id  = int(parts[1])
    reason      = parts[2]
    info        = active_chats.get(callback.from_user.id)
    if not info:
        await callback.answer("Сессия не найдена.", show_alert=True)
        return
    reported_id = info["partner_id"]
    await db.add_report(callback.from_user.id, reported_id, session_id, reason)
    await callback.answer("✅ Жалоба отправлена. Спасибо!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


# ── Оценки ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rate:"))
async def handle_rate(callback: CallbackQuery):
    _, value, session_id, partner_id = callback.data.split(":")
    await db.rate_user(
        callback.from_user.id, int(partner_id), int(session_id), int(value)
    )
    txt = "👍 Оценка отправлена!" if int(value) == 1 else "👎 Оценка отправлена!"
    await callback.answer(txt)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ── Подарки ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gift:"))
async def handle_gift(callback: CallbackQuery, bot: Bot):
    from bot.keyboards.keyboards import GIFTS_DATA
    _, key, session_id = callback.data.split(":")
    info = active_chats.get(callback.from_user.id)
    if not info:
        await callback.answer("Ты не в чате!", show_alert=True)
        return
    gift = GIFTS_DATA.get(key)
    if not gift:
        return
    await db.log_message(
        int(session_id), callback.from_user.id, "gift",
        text=f"[Подарок: {gift['emoji']} {gift['name']}]"
    )
    async with db.pool().acquire() as c:
        await c.execute(
            "INSERT INTO gifts(sender_id,recipient_id,session_id,gift_key) VALUES($1,$2,$3,$4)",
            callback.from_user.id, info["partner_id"], int(session_id), key
        )
    try:
        await bot.send_message(info["partner_id"], gift["msg"])
    except Exception:
        pass
    await callback.answer(f"{gift['emoji']} Подарок отправлен!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "gifts:close")
async def close_gifts(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass


# ── Профиль ───────────────────────────────────────────────────────────────────

@router.message(F.text == "👤 Профиль")
@router.message(Command("profile"))
async def show_profile(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Нажми /start")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    b          = badge(user)
    plan_str   = user["premium_plan"].upper() if user.get("premium_plan") else "Бесплатный"
    until_str  = (
        f"\n📅 До: *{user['premium_until'].strftime('%d.%m.%Y')}*"
        if user.get("premium_until") else ""
    )
    gender_str = {"male": "👨 Мужской", "female": "👩 Женский"}.get(user.get("gender"), "🤷 Не указан")
    interests  = ", ".join(user.get("interests") or []) or "Не выбраны"
    ref        = f"https://t.me/{config.BOT_USERNAME}?start={user['referral_code']}" if config.BOT_USERNAME else "не задан BOT_USERNAME"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🏆 Достижения",   callback_data="achievements:show"))
    kb.row(InlineKeyboardButton(text="⚙️ Изменить профиль", callback_data="profile:edit"))

    await message.answer(
        f"{b}*Твой профиль*\n\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎯 Интересы: {interests}\n\n"
        f"⭐ Рейтинг: *{user['rating']:.1f}* / 10\n"
        f"💬 Диалогов: *{user['total_chats']}*\n"
        f"✉️ Сообщений: *{user['total_messages']}*\n"
        f"⚡ XP: *{user['xp']}*\n\n"
        f"💎 Тариф: *{plan_str}*{until_str}\n\n"
        f"👥 Рефералов: *{user['referral_count']}* _(+3 дня Premium за каждого)_\n"
        f"🔗 Приглашай друзей:\n`{ref}`",
        parse_mode="Markdown", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "profile:edit")
async def profile_edit(callback: CallbackQuery, state: FSMContext, bot: Bot):
    uid = callback.from_user.id
    # Нельзя редактировать профиль пока в чате или поиске
    if uid in active_chats:
        await callback.answer("❌ Сначала выйди из чата (⏹ Стоп)", show_alert=True)
        return
    await db.remove_from_queue(uid)
    await callback.message.answer("Укажи новый пол:", reply_markup=gender_kb())
    await state.set_state(UserStates.reg_gender)
    await callback.answer()


@router.callback_query(F.data == "achievements:show")
async def show_achievements(callback: CallbackQuery):
    user  = await db.get_user(callback.from_user.id)
    owned = set(user.get("achievements") or [])
    text  = f"🏆 *Достижения*\n\n⚡ XP: *{user['xp']}*\n\n"
    for code, (emoji, name, desc, xp) in db.ACHIEVEMENTS.items():
        if code in owned:
            text += f"{emoji} *{name}* ✅\n_{desc}_\n\n"
        else:
            text += f"🔒 {name} _(+{xp} XP)_\n\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back:main"))
    await callback.message.edit_text(text[:4000], parse_mode="Markdown", reply_markup=kb.as_markup())


# ── Premium ───────────────────────────────────────────────────────────────────

@router.message(F.text == "💎 Premium")
@router.message(Command("premium"))
async def show_premium_menu(message: Message):
    await _premium_msg(message)


@router.callback_query(F.data == "premium:show")
async def premium_callback(callback: CallbackQuery):
    await _premium_msg(callback.message, edit=True)
    await callback.answer()


async def _premium_msg(message: Message, edit: bool = False):
    text = "💎 *Anonka Premium*\n\nВыбери тариф:\n\n"
    for plan_id, p in config.PLANS.items():
        badge_str = f" `[{p.get('badge','')}]`" if p.get("badge") else ""
        feats     = "\n".join(f"  ✓ {f}" for f in p["features"])
        text += f"{p['emoji']} *{p['name']}*{badge_str}\n⭐ {p['stars']} Stars | 💎 {p['ton']} TON\n{feats}\n\n"
    try:
        if edit:
            await message.edit_text(text, parse_mode="Markdown", reply_markup=plans_kb())
        else:
            await message.answer(text, parse_mode="Markdown", reply_markup=plans_kb())
    except Exception:
        await message.answer(text, parse_mode="Markdown", reply_markup=plans_kb())


from bot.keyboards.keyboards import plans_kb


@router.callback_query(F.data.startswith("plan:"))
async def select_plan(callback: CallbackQuery):
    plan_id = callback.data[5:]
    p = config.PLANS.get(plan_id)
    if not p:
        return
    feats = "\n".join(f"✅ {f}" for f in p["features"])
    text = (
        f"{p['emoji']} *{p['name']}*\n\n{feats}\n\n"
        f"💰 Стоимость:\n"
        f"⭐ *{p['stars']} Telegram Stars*\n"
        f"💎 *{p['ton']} TON*\n\n"
        f"Выбери способ оплаты:"
    )
    from bot.keyboards.keyboards import plan_pay_kb
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=plan_pay_kb(plan_id))


# ── Горячие темы ──────────────────────────────────────────────────────────────

@router.message(F.text == "🔥 Горячие темы")
async def show_hot_topics(message: Message):
    import random
    from datetime import datetime
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    async with db.pool().acquire() as c:
        rows = await c.fetch("SELECT text FROM hot_topics WHERE is_active=TRUE")
    topics = [r["text"] for r in rows]
    if not topics:
        topics = ["💭 Расскажи о своей мечте", "🌙 Чего ты боишься?", "🎯 Твоя главная цель"]
    seed  = int(datetime.now().strftime("%Y%m%d"))
    rng   = random.Random(seed)
    daily = rng.sample(topics, min(5, len(topics)))

    kb = InlineKeyboardBuilder()
    for i in range(len(daily)):
        kb.row(InlineKeyboardButton(text=f"🔥 Тема {i+1}", callback_data=f"topic:{i}"))
    text = "🔥 *Горячие темы дня*\n\n"
    for i, t in enumerate(daily):
        text += f"*{i+1}.* {t}\n\n"
    text += "_Про и VIP: нажми на тему чтобы начать поиск по ней_"
    await message.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("topic:"))
async def search_by_topic(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = await db.get_user(callback.from_user.id)
    if not is_premium_active(user) or user.get("premium_plan") not in ("pro", "vip"):
        await callback.answer("🔥 Горячие темы — только для Про и VIP", show_alert=True)
        return
    import random
    from datetime import datetime
    async with db.pool().acquire() as c:
        rows = await c.fetch("SELECT text FROM hot_topics WHERE is_active=TRUE")
    topics = [r["text"] for r in rows]
    if not topics:
        topics = ["💭 Расскажи о своей мечте"]
    seed  = int(datetime.now().strftime("%Y%m%d"))
    rng   = random.Random(seed)
    daily = rng.sample(topics, min(5, len(topics)))
    idx   = int(callback.data[6:])
    topic = daily[idx] if idx < len(daily) else None
    await db.add_to_queue(
        callback.from_user.id,
        gender_filter=None,
        interests=user.get("interests", []),
        is_premium=True
    )
    await state.set_state(UserStates.in_queue)
    await state.update_data(topic=topic)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    try:
        await callback.message.edit_text(
            f"🔥 Ищем собеседника для темы:\n\n_{topic}_\n\nОжидай...",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="search:cancel")
            ]])
        )
    except Exception:
        pass


@router.callback_query(F.data == "search:cancel")
async def search_cancel_cb(callback: CallbackQuery, state: FSMContext):
    await db.remove_from_queue(callback.from_user.id)
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("❌ Поиск отменён.", reply_markup=main_menu())


# ── Истории ───────────────────────────────────────────────────────────────────

@router.message(F.text == "📖 Истории")
async def show_stories(message: Message):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    async with db.pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id,text,likes FROM stories "
            "WHERE expires_at>NOW() ORDER BY likes DESC,created_at DESC LIMIT 5"
        )
    kb = InlineKeyboardBuilder()
    if not rows:
        kb.row(InlineKeyboardButton(text="✍️ Написать (VIP)", callback_data="story:write"))
        await message.answer("📖 *Stories*\n\nПока нет историй. Будь первым!",
                             parse_mode="Markdown", reply_markup=kb.as_markup())
        return
    text = "📖 *Анонимные истории* _(24ч)_\n\n"
    for r in rows:
        text += f"*#{r['id']}* — {r['text'][:200]}\n❤️ {r['likes']}\n\n"
        kb.row(InlineKeyboardButton(text=f"❤️ #{r['id']}", callback_data=f"story:like:{r['id']}"))
    kb.row(InlineKeyboardButton(text="✍️ Написать (VIP)", callback_data="story:write"))
    await message.answer(text[:4000], parse_mode="Markdown", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("story:"))
async def story_actions(callback: CallbackQuery, state: FSMContext):
    parts  = callback.data.split(":")
    action = parts[1]
    if action == "like":
        story_id = int(parts[2])
        try:
            async with db.pool().acquire() as c:
                await c.execute("INSERT INTO story_likes(story_id, user_id) VALUES($1,$2)", story_id, callback.from_user.id)
                await c.execute("UPDATE stories SET likes=likes+1 WHERE id=$1", story_id)
            await callback.answer("❤️ Лайкнуто!")
        except Exception:
            await callback.answer("Ты уже лайкал эту историю", show_alert=True)
    elif action == "write":
        user = await db.get_user(callback.from_user.id)
        if not is_premium_active(user) or user.get("premium_plan") != "vip":
            await callback.answer("✍️ Писать Stories — только VIP", show_alert=True)
            return
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await callback.message.answer(
            "✍️ *Напиши свою историю:*\n_Она будет видна 24 часа анонимно. Макс. 500 символов._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="back:main")
            ]])
        )
        await state.set_state(UserStates.write_story)
        await callback.answer()


@router.message(UserStates.write_story)
async def save_story(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not is_premium_active(user) or user.get("premium_plan") != "vip":
        await message.answer("❌ Нет прав.", reply_markup=main_menu())
        return
    async with db.pool().acquire() as c:
        await c.execute(
            "INSERT INTO stories(author_id,text,expires_at) VALUES($1,$2,NOW()+INTERVAL '24 hours')",
            message.from_user.id, message.text[:500]
        )
    await message.answer("✅ *История опубликована!* Она будет видна 24 часа.",
                         parse_mode="Markdown", reply_markup=main_menu())


# ── Промокод ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "promo:enter")
async def promo_enter(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer(
        "🎟 *Введи промокод:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="back:main")
        ]])
    )
    await state.set_state(UserStates.enter_promo)
    await callback.answer()


@router.message(UserStates.enter_promo)
async def process_promo(message: Message, state: FSMContext):
    await state.clear()
    result = await db.use_promo(message.text.strip(), message.from_user.id)
    if result["ok"]:
        p = config.PLANS.get(result["plan"], {})
        await message.answer(
            f"✅ *Промокод активирован!*\n\nТариф: *{p.get('name','?')}* на {result['days']} дней",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    else:
        await message.answer(f"❌ {result['error']}", reply_markup=main_menu())


# ── Misc ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back:main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Главное меню", reply_markup=main_menu())
