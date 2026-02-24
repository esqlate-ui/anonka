"""
Anonka Bot — точка входа
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.config import config
from database import db
from bot.handlers import main as h_main
from bot.handlers import payments as h_pay
from bot.handlers import admin as h_admin

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger(__name__)


# ── JSON helper ───────────────────────────────────────────────────────────────

def jr(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json", status=status
    )


# ── Webhook ───────────────────────────────────────────────────────────────────

async def webhook_handler(request: web.Request) -> web.Response:
    from aiogram.types import Update
    data = await request.json()
    update = Update(**data)
    await request.app["dp"].feed_update(request.app["bot"], update)
    return web.Response(status=200)


# ── API ───────────────────────────────────────────────────────────────────────

async def api_stats(r):     return jr(await db.get_stats())

async def api_users(r):
    p = int(r.rel_url.query.get("page", 1))
    f = r.rel_url.query.get("filter", "all")
    s = r.rel_url.query.get("search") or None
    plan = None if f in ("all","") else f
    banned = True if f == "banned" else None
    if f == "banned": plan = None
    users, total = await db.get_users_list(50, (p-1)*50, s, plan, banned)
    return jr({"users": users, "total": total})

async def api_chats(r):
    p = int(r.rel_url.query.get("page", 1))
    f = r.rel_url.query.get("filter", "all")
    uid = r.rel_url.query.get("user_id")
    uid = int(uid) if uid else None
    sessions, total = await db.get_sessions_list(50, (p-1)*50, None if f=="all" else f, uid)
    return jr({"sessions": sessions, "total": total})

async def api_chat_messages(r):
    sid = int(r.rel_url.query.get("session_id", 0))
    msgs = await db.get_session_messages(sid)
    return jr({"messages": msgs})

async def api_reports(r):
    s = r.rel_url.query.get("status", "pending")
    rows, total = await db.get_reports_list(50, 0, s)
    return jr({"reports": rows, "total": total})

async def api_payments(r):
    prov = r.rel_url.query.get("provider") or None
    rows, total = await db.get_payments_list(50, 0, prov)
    return jr({"payments": rows, "total": total})

async def api_realtime(r):
    async with db.pool().acquire() as c:
        queue  = await c.fetchval("SELECT COUNT(*) FROM search_queue")
        active = await c.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE status='active'")
        online = await c.fetchval("SELECT COUNT(*) FROM users WHERE last_active>NOW()-INTERVAL '5 minutes'")
        live   = await c.fetch("SELECT id,user_a,user_b,started_at FROM chat_sessions WHERE status='active' ORDER BY started_at DESC LIMIT 20")
    return jr({"queue":queue,"active_chats":active,"online":online,"live":[dict(x) for x in live]})

async def api_ban(r):
    d = await r.json()
    await db.ban_user(int(d["user_id"]), d.get("reason","Бан из панели"))
    return jr({"success":True})

async def api_unban(r):
    d = await r.json()
    await db.unban_user(int(d["user_id"]))
    return jr({"success":True})

async def api_grant(r):
    d = await r.json()
    await db.activate_plan(int(d["user_id"]), d["plan"], int(d.get("days",30)))
    return jr({"success":True})

async def api_report_action(r):
    d = await r.json()
    action = d.get("action","dismiss")
    status = "banned" if action=="ban" else "dismissed"
    async with db.pool().acquire() as c:
        await c.execute("UPDATE reports SET status=$2,reviewed_at=NOW() WHERE id=$1", d["report_id"], status)
        if action=="ban":
            rep = await c.fetchrow("SELECT reported_id FROM reports WHERE id=$1", d["report_id"])
            if rep:
                await db.ban_user(rep["reported_id"], "Бан по жалобе")
    return jr({"success":True})

async def api_broadcast(r):
    d = await r.json()
    async with db.pool().acquire() as c:
        total = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=FALSE")
        await c.execute("INSERT INTO broadcasts(text,audience,total_users,status) VALUES($1,$2,$3,'pending')",
                        d["text"], d.get("audience","all"), total)
    # Запускаем рассылку фоново
    asyncio.create_task(_do_broadcast(r.app["bot"], d["text"], d.get("audience","all")))
    return jr({"success":True,"total":total})

async def _do_broadcast(bot: Bot, text: str, audience: str):
    async with db.pool().acquire() as c:
        if audience == "premium":
            users = await c.fetch("SELECT id FROM users WHERE is_banned=FALSE AND is_premium=TRUE")
        elif audience == "free":
            users = await c.fetch("SELECT id FROM users WHERE is_banned=FALSE AND is_premium=FALSE")
        else:
            users = await c.fetch("SELECT id FROM users WHERE is_banned=FALSE")
    sent = 0
    for row in users:
        try:
            await bot.send_message(row["id"], text)
            sent += 1
        except Exception:
            pass
        if sent % 30 == 0:
            await asyncio.sleep(1)
    logger.info(f"Broadcast done: {sent}/{len(users)}")

async def api_topics(r):
    async with db.pool().acquire() as c:
        rows = await c.fetch("SELECT * FROM hot_topics ORDER BY created_at")
    return jr({"topics":[dict(x) for x in rows]})

async def api_topics_add(r):
    d = await r.json()
    async with db.pool().acquire() as c:
        await c.execute("INSERT INTO hot_topics(text) VALUES($1)", d["text"])
    return jr({"success":True})

async def api_topics_delete(r):
    d = await r.json()
    async with db.pool().acquire() as c:
        await c.execute("DELETE FROM hot_topics WHERE id=$1", d["id"])
    return jr({"success":True})

async def api_topics_toggle(r):
    d = await r.json()
    async with db.pool().acquire() as c:
        await c.execute("UPDATE hot_topics SET is_active=$2 WHERE id=$1", d["id"], d["active"])
    return jr({"success":True})

async def api_promo_list(r):
    async with db.pool().acquire() as c:
        rows = await c.fetch("SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT 100")
    return jr({"promos":[dict(x) for x in rows]})

async def api_promo_create(r):
    d = await r.json()
    ok = await db.create_promo(d["code"], d["plan"], int(d["days"]), int(d["max_uses"]))
    return jr({"success":ok})

async def admin_page(r):
    p = Path(__file__).parent / "admin" / "panel.html"
    return web.FileResponse(p)


# ── Matchmaking ───────────────────────────────────────────────────────────────

_mm_running = True

async def matchmaking_loop(bot: Bot):
    from bot.handlers.main import active_chats, UserStates
    from bot.keyboards.keyboards import chat_kb
    logger.info("🔁 Matchmaking loop запущен")
    while _mm_running:
        try:
            async with db.pool().acquire() as c:
                queue = await c.fetch(
                    "SELECT sq.user_id, sq.gender_filter, u.gender, sq.is_premium "
                    "FROM search_queue sq JOIN users u ON u.id=sq.user_id "
                    "WHERE u.is_banned=FALSE ORDER BY sq.is_premium DESC, sq.added_at ASC"
                )
            paired = set()
            for row in queue:
                uid = row["user_id"]
                if uid in paired or uid in active_chats:
                    continue
                partner_id = await db.find_partner(uid, row["gender_filter"], row["gender"])
                if partner_id and partner_id not in paired and partner_id not in active_chats:
                    # Получаем FSM storage для смены состояния
                    dp = bot._session and None  # just for reference
                    session_id = await db.create_session(uid, partner_id)
                    active_chats[uid] = {"session_id": session_id, "partner_id": partner_id}
                    active_chats[partner_id] = {"session_id": session_id, "partner_id": uid}
                    paired.update([uid, partner_id])

                    msg = ("✅ *Собеседник найден!*\n\n"
                           "Начинай писать — он тебя услышит 🎭\n"
                           "_Ты полностью анонимен_")
                    try:
                        await bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=chat_kb())
                        await bot.send_message(partner_id, msg, parse_mode="Markdown", reply_markup=chat_kb())
                    except Exception as e:
                        logger.warning(f"Ошибка при уведомлении пары {uid}/{partner_id}: {e}")
                        active_chats.pop(uid, None)
                        active_chats.pop(partner_id, None)
                        await db.end_session(session_id)
        except Exception as e:
            logger.error(f"Matchmaking error: {e}")
        await asyncio.sleep(3)

def stop_matchmaking():
    global _mm_running
    _mm_running = False


# ── Background tasks ──────────────────────────────────────────────────────────

async def daily_cleanup():
    """Сброс дневных лимитов и истёкших подписок каждый час"""
    while True:
        try:
            await db.reset_daily()
            await db.expire_plans()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(3600)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def on_startup(app: web.Application):
    logger.info("🚀 Запуск Anonka...")
    await db.init(config.DB_DSN)
    logger.info("✅ БД подключена")

    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]
    dp.include_router(h_main.router)
    dp.include_router(h_pay.router)
    dp.include_router(h_admin.router)

    if config.WEBHOOK_HOST:
        wh = config.WEBHOOK_HOST + config.WEBHOOK_PATH
        await bot.set_webhook(wh, allowed_updates=["message","callback_query","pre_checkout_query"])
        logger.info(f"✅ Webhook: {wh}")
    else:
        # Polling mode для локальной разработки
        asyncio.create_task(dp.start_polling(bot))
        logger.info("✅ Polling запущен")

    asyncio.create_task(matchmaking_loop(bot))
    asyncio.create_task(daily_cleanup())
    logger.info("✅ Все фоновые задачи запущены")


async def on_shutdown(app: web.Application):
    stop_matchmaking()
    bot: Bot = app["bot"]
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    await db.close()
    await bot.session.close()
    logger.info("👋 Остановлен.")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    storage = MemoryStorage()
    bot = Bot(token=config.BOT_TOKEN)
    dp  = Dispatcher(storage=storage)

    app = web.Application()
    app["bot"] = bot
    app["dp"]  = dp

    # Webhook
    app.router.add_post(config.WEBHOOK_PATH, webhook_handler)

    # Admin panel
    app.router.add_get("/admin",  admin_page)
    app.router.add_get("/admin/", admin_page)

    # API (используется панелью)
    app.router.add_get("/stats",          api_stats)
    app.router.add_get("/users",          api_users)
    app.router.add_get("/chats",          api_chats)
    app.router.add_get("/chat_messages",  api_chat_messages)
    app.router.add_get("/reports",        api_reports)
    app.router.add_get("/payments",       api_payments)
    app.router.add_get("/realtime",       api_realtime)
    app.router.add_get("/topics",         api_topics)
    app.router.add_get("/promos",         api_promo_list)

    app.router.add_post("/users/ban",           api_ban)
    app.router.add_post("/users/unban",         api_unban)
    app.router.add_post("/users/grant-premium", api_grant)
    app.router.add_post("/reports/dismiss",     api_report_action)
    app.router.add_post("/broadcast",           api_broadcast)
    app.router.add_post("/topics/add",          api_topics_add)
    app.router.add_post("/topics/delete",       api_topics_delete)
    app.router.add_post("/topics/toggle",       api_topics_toggle)
    app.router.add_post("/promo",               api_promo_create)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host=config.WEB_HOST, port=config.WEB_PORT)
