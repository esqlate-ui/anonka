"""
Хэндлеры оплаты — TON и Telegram Stars
"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice

from config.config import config
from database import db
from bot.keyboards.keyboards import main_menu

router = Router()
logger = logging.getLogger(__name__)


# ── Stars ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars(callback: CallbackQuery, bot: Bot):
    plan_id = callback.data[10:]
    p = config.PLANS.get(plan_id)
    if not p:
        return
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Anonka {p['name']}",
        description=f"Подписка {p['name']} на 30 дней\n" + "\n".join(f"✓ {f}" for f in p["features"][:4]),
        payload=f"premium_{plan_id}_{callback.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"Anonka {p['name']}", amount=p["stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def stars_paid(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    if len(parts) < 2 or parts[0] != "premium":
        return
    plan_id = parts[1]
    p = config.PLANS.get(plan_id)
    if not p:
        return

    pay_id = await db.create_payment(
        message.from_user.id, plan_id, "stars",
        f"{p['stars']} Stars"
    )
    await db.confirm_payment(pay_id, ref=message.successful_payment.telegram_payment_charge_id)

    await message.answer(
        f"🎉 *Оплата прошла!*\n\n"
        f"Подписка *{p['name']}* активирована на 30 дней 🚀\n"
        f"Все возможности уже доступны!",
        parse_mode="Markdown", reply_markup=main_menu()
    )
    logger.info(f"Stars payment confirmed: user={message.from_user.id} plan={plan_id}")


# ── TON ───────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay:ton:"))
async def pay_ton(callback: CallbackQuery, bot: Bot):
    plan_id = callback.data[8:]
    p = config.PLANS.get(plan_id)
    if not p:
        return

    # Создаём pending платёж
    pay_id = await db.create_payment(callback.from_user.id, plan_id, "ton", f"{p['ton']} TON")

    # Уникальный комментарий для идентификации платежа
    comment = f"anonka_{pay_id}"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="✅ Я оплатил",
        callback_data=f"ton:check:{pay_id}"
    ))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"ton:cancel:{pay_id}"))

    await callback.message.edit_text(
        f"💎 *Оплата через TON*\n\n"
        f"Тариф: *{p['name']}* — *{p['ton']} TON*\n\n"
        f"1️⃣ Открой Tonkeeper / любой TON кошелёк\n"
        f"2️⃣ Отправь *{p['ton']} TON* на адрес:\n"
        f"`{config.TON_WALLET}`\n\n"
        f"3️⃣ В поле *комментарий* укажи:\n"
        f"`{comment}`\n\n"
        f"⚠️ *Комментарий обязателен* — по нему система определяет платёж!\n\n"
        f"После отправки нажми *✅ Я оплатил*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ton:check:"))
async def ton_check(callback: CallbackQuery, bot: Bot):
    pay_id = int(callback.data[10:])

    # Если есть TON API ключ — проверяем автоматически
    if config.TON_API_KEY:
        confirmed = await _check_ton_tx(pay_id)
        if confirmed:
            await db.confirm_payment(pay_id)
            async with db.pool().acquire() as c:
                row = await c.fetchrow("SELECT plan FROM payments WHERE id=$1", pay_id)
            p = config.PLANS.get(row["plan"], {})
            await callback.message.edit_text(
                f"✅ *Оплата подтверждена!*\n\nПодписка *{p.get('name','?')}* активирована 🎉",
                parse_mode="Markdown"
            )
            await callback.message.answer("Главное меню", reply_markup=main_menu())
            return
        else:
            await callback.answer(
                "⏳ Транзакция ещё не найдена. Подождите 1-2 минуты и попробуйте снова.",
                show_alert=True
            )
    else:
        # Без API ключа — отправляем на ручную проверку администратору
        async with db.pool().acquire() as c:
            row = await c.fetchrow(
                "SELECT p.*, u.username, u.first_name FROM payments p "
                "JOIN users u ON u.id=p.user_id WHERE p.id=$1", pay_id
            )
        if not row:
            await callback.answer("Платёж не найден.", show_alert=True)
            return

        # Уведомляем всех админов
        for admin_id in config.ADMIN_IDS:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            from aiogram.types import InlineKeyboardButton
            kb = InlineKeyboardBuilder()
            kb.row(
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin:ton:confirm:{pay_id}"),
                InlineKeyboardButton(text="❌ Отклонить",  callback_data=f"admin:ton:reject:{pay_id}"),
            )
            try:
                await bot.send_message(
                    admin_id,
                    f"💎 *Новый TON платёж*\n\n"
                    f"Пользователь: @{row['username'] or 'без username'} ({row['user_id']})\n"
                    f"Тариф: *{row['plan'].upper()}*\n"
                    f"Сумма: *{row['amount']}*\n"
                    f"Комментарий: `anonka_{pay_id}`",
                    parse_mode="Markdown",
                    reply_markup=kb.as_markup()
                )
            except Exception as e:
                logger.warning(f"Не удалось уведомить админа {admin_id}: {e}")

        await callback.answer(
            "📨 Запрос на проверку отправлен администратору. Обычно это занимает несколько минут.",
            show_alert=True
        )


@router.callback_query(F.data.startswith("ton:cancel:"))
async def ton_cancel(callback: CallbackQuery):
    pay_id = int(callback.data[11:])
    async with db.pool().acquire() as c:
        await c.execute("UPDATE payments SET status='failed' WHERE id=$1 AND status='pending'", pay_id)
    await callback.message.delete()
    await callback.message.answer("❌ Платёж отменён.", reply_markup=main_menu())


# Ручное подтверждение TON от админа
@router.callback_query(F.data.startswith("admin:ton:"))
async def admin_ton_decision(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    parts = callback.data.split(":")
    action, pay_id = parts[2], int(parts[3])

    if action == "confirm":
        await db.confirm_payment(pay_id)
        async with db.pool().acquire() as c:
            row = await c.fetchrow("SELECT * FROM payments WHERE id=$1", pay_id)
        p = config.PLANS.get(row["plan"], {})
        try:
            await bot.send_message(
                row["user_id"],
                f"✅ *TON оплата подтверждена!*\n\nПодписка *{p.get('name','?')}* активирована 🎉",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except Exception:
            pass
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ *Подтверждено*", parse_mode="Markdown"
        )
    else:
        async with db.pool().acquire() as c:
            await c.execute("UPDATE payments SET status='failed' WHERE id=$1", pay_id)
            row = await c.fetchrow("SELECT user_id FROM payments WHERE id=$1", pay_id)
        try:
            await bot.send_message(row["user_id"], "❌ Платёж не прошёл проверку. Обратитесь в поддержку.")
        except Exception:
            pass
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ *Отклонено*", parse_mode="Markdown"
        )
    await callback.answer()


async def _check_ton_tx(pay_id: int) -> bool:
    """Автопроверка TON транзакции по комментарию"""
    import aiohttp
    from datetime import datetime, timezone
    try:
        async with db.pool().acquire() as c:
            row = await c.fetchrow("SELECT * FROM payments WHERE id=$1", pay_id)
        if not row:
            return False
        comment = f"anonka_{pay_id}"
        amount_ton = float(row["amount"].split()[0])

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://toncenter.com/api/v2/getTransactions",
                params={"address": config.TON_WALLET, "limit": 30, "api_key": config.TON_API_KEY}
            ) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return False
        for tx in data.get("result", []):
            tx_time = datetime.fromtimestamp(tx.get("utime", 0), tz=timezone.utc)
            created = row["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if tx_time < created:
                continue
            in_msg = tx.get("in_msg", {})
            value = int(in_msg.get("value", 0)) / 1e9
            msg_text = in_msg.get("message", "")
            if comment in msg_text and abs(value - amount_ton) / amount_ton < 0.05:
                return True
    except Exception as e:
        logger.error(f"TON check error: {e}")
    return False
