"""
Хэндлеры администратора
"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command

from config.config import config
from database import db
from bot.keyboards.keyboards import main_menu

router = Router()
logger = logging.getLogger(__name__)


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    url = f"{config.WEBHOOK_HOST}/admin" if config.WEBHOOK_HOST else "http://localhost:8080/admin"
    await message.answer(
        f"👑 *Панель администратора*\n\n"
        f"🔗 Веб-панель: {url}\n\n"
        f"Команды:\n"
        f"/stats — статистика\n"
        f"/ban <id> [причина] — заблокировать\n"
        f"/unban <id> — разблокировать\n"
        f"/grant <id> <план> <дней> — выдать Premium\n"
        f"/promo <код> <план> <дней> <кол-во> — промокод\n"
        f"/broadcast <текст> — рассылка всем",
        parse_mode="Markdown"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    s = await db.get_stats()
    await message.answer(
        f"📊 *Статистика Anonka*\n\n"
        f"👤 Всего пользователей: *{s['total_users']}*\n"
        f"🟢 Онлайн сейчас: *{s['online_now']}*\n"
        f"📅 Активны сегодня: *{s['active_today']}*\n"
        f"💎 Премиум: *{s['premium_users']}*\n\n"
        f"💬 Всего диалогов: *{s['total_chats']}*\n"
        f"💬 Сегодня: *{s['chats_today']}*\n"
        f"🔴 Активных сейчас: *{s['active_chats']}*\n"
        f"⏳ В очереди: *{s['queue_size']}*\n"
        f"✉️ Сообщений всего: *{s['total_messages']}*\n\n"
        f"⚠️ Жалоб на рассмотрении: *{s['pending_reports']}*\n\n"
        f"💰 Оплат Stars: *{s['payments_stars']}*\n"
        f"💰 Оплат TON: *{s['payments_ton']}*",
        parse_mode="Markdown"
    )


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Использование: /ban <user_id> [причина]")
        return
    try:
        uid = int(args[1])
        reason = args[2] if len(args) > 2 else "Нарушение правил"
        await db.ban_user(uid, reason)
        await message.answer(f"✅ Пользователь {uid} заблокирован.")
        try:
            await bot.send_message(uid, f"🚫 Ваш аккаунт заблокирован.\nПричина: {reason}")
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Неверный ID.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban <user_id>")
        return
    try:
        uid = int(args[1])
        await db.unban_user(uid)
        await message.answer(f"✅ Пользователь {uid} разблокирован.")
        try:
            await bot.send_message(uid, "✅ Ваш аккаунт разблокирован!")
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Неверный ID.")


@router.message(Command("grant"))
async def cmd_grant(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("Использование: /grant <user_id> <basic|pro|vip> <дней>")
        return
    try:
        uid, plan, days = int(args[1]), args[2], int(args[3])
        if plan not in config.PLANS:
            await message.answer("❌ Неверный план. Варианты: basic, pro, vip")
            return
        await db.activate_plan(uid, plan, days)
        p = config.PLANS[plan]
        await message.answer(f"✅ Пользователю {uid} выдан *{p['name']}* на {days} дней.", parse_mode="Markdown")
        try:
            await bot.send_message(uid, f"🎁 Администратор выдал вам *{p['name']}* на {days} дней! 🎉", parse_mode="Markdown")
        except Exception:
            pass
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("promo"))
async def cmd_promo(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 5:
        await message.answer("Использование: /promo <код> <план> <дней> <кол-во>")
        return
    try:
        code, plan, days, uses = args[1], args[2], int(args[3]), int(args[4])
        ok = await db.create_promo(code, plan, days, uses)
        if ok:
            await message.answer(f"✅ Промокод *{code.upper()}* создан!\nТариф: {plan}, дней: {days}, использований: {uses}", parse_mode="Markdown")
        else:
            await message.answer("❌ Такой промокод уже существует.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        await message.answer("Использование: /broadcast <текст>")
        return
    msg_text = text[1]
    async with db.pool().acquire() as c:
        users = await c.fetch("SELECT id FROM users WHERE is_banned=FALSE")
    total = len(users)
    await message.answer(f"📢 Начинаю рассылку {total} пользователям...")
    import asyncio
    sent, failed = 0, 0
    for i, row in enumerate(users, 1):
        try:
            await bot.send_message(row["id"], msg_text)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:          # пауза каждые 25 попыток независимо от успеха
            await asyncio.sleep(1)
    await message.answer(f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}")
