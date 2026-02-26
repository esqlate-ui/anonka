"""
Утилита рассылки — единая логика для панели и Telegram-команды
"""
import asyncio
import logging
from aiogram import Bot

logger = logging.getLogger(__name__)


async def do_broadcast(bot: Bot, text: str, user_ids: list[int]) -> tuple[int, int]:
    """
    Рассылает сообщение пользователям.
    Возвращает (sent, failed).
    """
    sent = failed = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            await asyncio.sleep(1)   # rate limit: пауза каждые 25 попыток
    logger.info(f"Broadcast done: {sent} sent, {failed} failed out of {len(user_ids)}")
    return sent, failed
