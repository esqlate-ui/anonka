"""
База данных — полная схема с логированием сообщений
"""
from __future__ import annotations
import asyncpg
from typing import Optional
from datetime import datetime

_pool: Optional[asyncpg.Pool] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    gender          TEXT CHECK (gender IN ('male','female',NULL)),
    interests       TEXT[] DEFAULT '{}',
    is_banned       BOOLEAN DEFAULT FALSE,
    ban_reason      TEXT,
    warn_count      INT DEFAULT 0,
    is_premium      BOOLEAN DEFAULT FALSE,
    premium_plan    TEXT CHECK (premium_plan IN ('basic','pro','vip',NULL)),
    premium_until   TIMESTAMPTZ,
    rating          FLOAT DEFAULT 5.0,
    rating_count    INT DEFAULT 0,
    total_chats     INT DEFAULT 0,
    total_messages  INT DEFAULT 0,
    daily_chats     INT DEFAULT 0,
    daily_reset     DATE DEFAULT CURRENT_DATE,
    chats_since_ad  INT DEFAULT 0,
    xp              INT DEFAULT 0,
    achievements    TEXT[] DEFAULT '{}',
    referral_code   TEXT UNIQUE,
    referred_by     BIGINT REFERENCES users(id),
    referral_count  INT DEFAULT 0,
    last_active     TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              BIGSERIAL PRIMARY KEY,
    user_a          BIGINT REFERENCES users(id),
    user_b          BIGINT REFERENCES users(id),
    topic           TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    messages_count  INT DEFAULT 0,
    ended_by        BIGINT,
    status          TEXT DEFAULT 'active' CHECK (status IN ('active','ended'))
);

CREATE TABLE IF NOT EXISTS messages_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT REFERENCES chat_sessions(id),
    sender_id       BIGINT REFERENCES users(id),
    msg_type        TEXT,
    text_content    TEXT,
    file_id         TEXT,
    file_unique_id  TEXT,
    caption         TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS search_queue (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id),
    gender_filter   TEXT,
    interests_filter TEXT[] DEFAULT '{}',
    is_premium      BOOLEAN DEFAULT FALSE,
    added_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT REFERENCES users(id),
    provider        TEXT NOT NULL,
    plan            TEXT NOT NULL,
    payment_ref     TEXT,
    amount          TEXT,
    status          TEXT DEFAULT 'pending' CHECK (status IN ('pending','confirmed','failed')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    confirmed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL PRIMARY KEY,
    reporter_id     BIGINT REFERENCES users(id),
    reported_id     BIGINT REFERENCES users(id),
    session_id      BIGINT REFERENCES chat_sessions(id),
    reason          TEXT,
    status          TEXT DEFAULT 'pending' CHECK (status IN ('pending','reviewed','banned','dismissed')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ratings (
    id              BIGSERIAL PRIMARY KEY,
    rater_id        BIGINT REFERENCES users(id),
    rated_id        BIGINT REFERENCES users(id),
    session_id      BIGINT REFERENCES chat_sessions(id),
    value           INT CHECK (value IN (1,-1)),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(rater_id, session_id)
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id              BIGSERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,
    plan            TEXT NOT NULL,
    days            INT NOT NULL DEFAULT 30,
    max_uses        INT DEFAULT 1,
    uses            INT DEFAULT 0,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_uses (
    id              BIGSERIAL PRIMARY KEY,
    code            TEXT NOT NULL,
    user_id         BIGINT REFERENCES users(id),
    used_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(code, user_id)
);

CREATE TABLE IF NOT EXISTS gifts (
    id              BIGSERIAL PRIMARY KEY,
    sender_id       BIGINT REFERENCES users(id),
    recipient_id    BIGINT REFERENCES users(id),
    session_id      BIGINT REFERENCES chat_sessions(id),
    gift_key        TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stories (
    id              BIGSERIAL PRIMARY KEY,
    author_id       BIGINT REFERENCES users(id),
    text            TEXT NOT NULL,
    likes           INT DEFAULT 0,
    expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_likes (
    story_id        BIGINT REFERENCES stories(id),
    user_id         BIGINT REFERENCES users(id),
    PRIMARY KEY(story_id, user_id)
);

CREATE TABLE IF NOT EXISTS hot_topics (
    id              BIGSERIAL PRIMARY KEY,
    text            TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id              BIGSERIAL PRIMARY KEY,
    text            TEXT,
    audience        TEXT DEFAULT 'all',
    sent_to         INT DEFAULT 0,
    total_users     INT DEFAULT 0,
    status          TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS warnings (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT REFERENCES users(id),
    reason          TEXT,
    given_by        BIGINT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_last_active  ON users(last_active);
CREATE INDEX IF NOT EXISTS idx_users_premium      ON users(is_premium);
CREATE INDEX IF NOT EXISTS idx_sessions_status    ON chat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_users     ON chat_sessions(user_a, user_b);
CREATE INDEX IF NOT EXISTS idx_messages_session   ON messages_log(session_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_reports_status     ON reports(status);
CREATE INDEX IF NOT EXISTS idx_payments_user      ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_queue_premium      ON search_queue(is_premium, added_at);
"""


async def init(dsn: str):
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    async with _pool.acquire() as c:
        await c.execute(SCHEMA)


async def close():
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    return _pool


# ── Пользователи ──────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str, first_name: str, ref_code: str = None) -> dict:
    import hashlib
    async with _pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if row:
            await c.execute(
                "UPDATE users SET last_active=NOW(), username=$2, first_name=$3 WHERE id=$1",
                user_id, username or "", first_name or "Аноним"
            )
            # Возвращаем свежую строку (после UPDATE)
            return dict(await c.fetchrow("SELECT * FROM users WHERE id=$1", user_id))

        ref = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
        referred_by = None
        if ref_code:
            rb = await c.fetchval("SELECT id FROM users WHERE referral_code=$1", ref_code)
            referred_by = rb if rb != user_id else None  # защита от самореферала

        await c.execute(
            "INSERT INTO users (id,username,first_name,referral_code,referred_by) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
            user_id, username or "", first_name or "Аноним", ref, referred_by
        )

        if referred_by:
            await c.execute(
                "UPDATE users SET referral_count=referral_count+1, is_premium=TRUE, premium_plan='basic', "
                "premium_until=COALESCE(premium_until,NOW())+INTERVAL '3 days' WHERE id=$1",
                referred_by
            )
        return dict(await c.fetchrow("SELECT * FROM users WHERE id=$1", user_id))


async def get_user(user_id: int) -> Optional[dict]:
    async with _pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        return dict(row) if row else None


_ALLOWED_USER_COLUMNS = {
    "gender", "interests", "is_banned", "ban_reason", "warn_count",
    "is_premium", "premium_plan", "premium_until", "rating", "rating_count",
    "total_chats", "total_messages", "daily_chats", "daily_reset",
    "chats_since_ad", "xp", "achievements", "referral_count", "last_active",
    "username", "first_name",
}

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    invalid = set(kwargs) - _ALLOWED_USER_COLUMNS
    if invalid:
        raise ValueError(f"update_user: недопустимые колонки: {invalid}")
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(kwargs))
    async with _pool.acquire() as c:
        await c.execute(f"UPDATE users SET {sets} WHERE id=$1", user_id, *kwargs.values())


async def ban_user(user_id: int, reason: str = "Нарушение правил"):
    async with _pool.acquire() as c:
        await c.execute("UPDATE users SET is_banned=TRUE, ban_reason=$2 WHERE id=$1", user_id, reason)


async def unban_user(user_id: int):
    async with _pool.acquire() as c:
        await c.execute("UPDATE users SET is_banned=FALSE, ban_reason=NULL WHERE id=$1", user_id)


async def activate_plan(user_id: int, plan: str, days: int):
    async with _pool.acquire() as c:
        await c.execute(
            "UPDATE users SET is_premium=TRUE, premium_plan=$2, "
            "premium_until=GREATEST(COALESCE(premium_until,NOW()),NOW())+($3*INTERVAL '1 day') WHERE id=$1",
            user_id, plan, days
        )


async def expire_plans():
    async with _pool.acquire() as c:
        await c.execute(
            "UPDATE users SET is_premium=FALSE, premium_plan=NULL, premium_until=NULL "
            "WHERE is_premium=TRUE AND premium_until IS NOT NULL AND premium_until < NOW()"
        )


async def reset_daily():
    async with _pool.acquire() as c:
        await c.execute(
            "UPDATE users SET daily_chats=0, daily_reset=CURRENT_DATE WHERE daily_reset < CURRENT_DATE"
        )


# ── Очередь ───────────────────────────────────────────────────────────────────

async def add_to_queue(user_id: int, gender_filter: str = None, interests: list = None, is_premium: bool = False):
    async with _pool.acquire() as c:
        # ON CONFLICT DO UPDATE обновляет фильтры но НЕ сбивает added_at
        # чтобы пользователь не терял место в очереди при повторном вызове
        await c.execute(
            "INSERT INTO search_queue(user_id,gender_filter,interests_filter,is_premium) VALUES($1,$2,$3,$4) "
            "ON CONFLICT(user_id) DO UPDATE SET gender_filter=$2,interests_filter=$3,is_premium=$4",
            user_id, gender_filter, interests or [], is_premium
        )


async def remove_from_queue(user_id: int):
    async with _pool.acquire() as c:
        await c.execute("DELETE FROM search_queue WHERE user_id=$1", user_id)


async def in_queue(user_id: int) -> bool:
    async with _pool.acquire() as c:
        return bool(await c.fetchval("SELECT 1 FROM search_queue WHERE user_id=$1", user_id))


async def find_partner(user_id: int, gender_filter: str = None, user_gender: str = None,
                        exclude_ids: list = None) -> Optional[int]:
    """
    Ищет партнёра в очереди.
    - gender_filter: какой пол ищет текущий пользователь (фильтрует u.gender партнёра)
    - user_gender:   пол текущего пользователя (проверяем, что партнёр ищет именно такой пол)
    - exclude_ids:   уже спаренные в текущей итерации маtчмейкинга
    """
    async with _pool.acquire() as c:
        exclude = list(exclude_ids or [])
        row = await c.fetchrow(
            "SELECT sq.user_id FROM search_queue sq JOIN users u ON u.id=sq.user_id "
            "WHERE sq.user_id != $1 AND u.is_banned = FALSE "
            "AND NOT (sq.user_id = ANY($4::bigint[])) "
            "AND ($2::text IS NULL OR u.gender = $2::text) "
            "AND ($3::text IS NULL OR sq.gender_filter IS NULL OR sq.gender_filter = $3::text) "
            "ORDER BY sq.is_premium DESC, sq.added_at ASC LIMIT 1",
            user_id, gender_filter, user_gender, exclude
        )
        return row["user_id"] if row else None


async def create_session(user_a: int, user_b: int, topic: str = None) -> int:
    async with _pool.acquire() as c:
        sid = await c.fetchval(
            "INSERT INTO chat_sessions(user_a,user_b,topic) VALUES($1,$2,$3) RETURNING id",
            user_a, user_b, topic
        )
        await c.execute("DELETE FROM search_queue WHERE user_id=$1 OR user_id=$2", user_a, user_b)
        await c.execute(
            "UPDATE users SET total_chats=total_chats+1, daily_chats=daily_chats+1, "
            "chats_since_ad=chats_since_ad+1, last_active=NOW() WHERE id=$1 OR id=$2",
            user_a, user_b
        )
        return sid


async def end_session(session_id: int, ended_by: int = None):
    async with _pool.acquire() as c:
        await c.execute(
            "UPDATE chat_sessions SET status='ended',ended_at=NOW(),ended_by=$2 WHERE id=$1",
            session_id, ended_by
        )


async def get_active_session(user_id: int) -> Optional[dict]:
    async with _pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT * FROM chat_sessions WHERE (user_a=$1 OR user_b=$1) AND status='active' "
            "ORDER BY started_at DESC LIMIT 1",
            user_id
        )
        return dict(row) if row else None


async def end_stale_sessions():
    """Завершает активные сессии, которые не имеют обоих пользователей в active_chats.
    Вызывается при старте для очистки после падения."""
    async with _pool.acquire() as c:
        await c.execute(
            "UPDATE chat_sessions SET status='ended', ended_at=NOW() WHERE status='active'"
        )


# ── Логирование сообщений ─────────────────────────────────────────────────────

async def log_message(session_id: int, sender_id: int, msg_type: str,
                       text: str = None, file_id: str = None,
                       file_unique_id: str = None, caption: str = None):
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO messages_log(session_id,sender_id,msg_type,text_content,file_id,file_unique_id,caption) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            session_id, sender_id, msg_type, text, file_id, file_unique_id, caption
        )
        await c.execute(
            "UPDATE chat_sessions SET messages_count=messages_count+1 WHERE id=$1",
            session_id
        )
        await c.execute("UPDATE users SET total_messages=total_messages+1 WHERE id=$1", sender_id)


async def get_session_messages(session_id: int) -> list:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            "SELECT ml.*, u.username, u.first_name FROM messages_log ml "
            "JOIN users u ON u.id=ml.sender_id WHERE ml.session_id=$1 ORDER BY ml.sent_at",
            session_id
        )
        return [dict(r) for r in rows]


# ── Жалобы ────────────────────────────────────────────────────────────────────

async def add_report(reporter: int, reported: int, session_id: int, reason: str):
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO reports(reporter_id,reported_id,session_id,reason) VALUES($1,$2,$3,$4)",
            reporter, reported, session_id, reason
        )


# ── Рейтинг ───────────────────────────────────────────────────────────────────

async def rate_user(rater_id: int, rated_id: int, session_id: int, value: int):
    async with _pool.acquire() as c:
        try:
            await c.execute(
                "INSERT INTO ratings(rater_id,rated_id,session_id,value) VALUES($1,$2,$3,$4)",
                rater_id, rated_id, session_id, value
            )
        except asyncpg.UniqueViolationError:
            return
        score = 10.0 if value == 1 else 1.0
        await c.execute(
            "UPDATE users SET rating=ROUND(((rating*rating_count+$2)/(rating_count+1))::numeric,2), "
            "rating_count=rating_count+1 WHERE id=$1",
            rated_id, score
        )


# ── Оплата ────────────────────────────────────────────────────────────────────

async def create_payment(user_id: int, plan: str, provider: str, amount: str) -> int:
    async with _pool.acquire() as c:
        return await c.fetchval(
            "INSERT INTO payments(user_id,plan,provider,amount) VALUES($1,$2,$3,$4) RETURNING id",
            user_id, plan, provider, amount
        )


async def confirm_payment(payment_id: int, ref: str = None):
    from config.config import config
    async with _pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM payments WHERE id=$1", payment_id)
        if not row:
            return
        await c.execute(
            "UPDATE payments SET status='confirmed',payment_ref=$2,confirmed_at=NOW() WHERE id=$1",
            payment_id, ref
        )
        days = config.PLANS.get(row["plan"], {}).get("days", 30)
        await activate_plan(row["user_id"], row["plan"], days)


async def get_pending_payment(user_id: int, provider: str) -> Optional[dict]:
    async with _pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT * FROM payments WHERE user_id=$1 AND provider=$2 AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            user_id, provider
        )
        return dict(row) if row else None


# ── Промокоды ─────────────────────────────────────────────────────────────────

async def use_promo(code: str, user_id: int) -> dict:
    async with _pool.acquire() as c:
        async with c.transaction():
            # SELECT FOR UPDATE блокирует строку на время транзакции — исключает race condition
            promo = await c.fetchrow(
                "SELECT * FROM promo_codes WHERE code=$1 AND (expires_at IS NULL OR expires_at>NOW()) AND uses<max_uses FOR UPDATE",
                code.upper()
            )
            if not promo:
                return {"ok": False, "error": "Промокод не найден или истёк"}
            used = await c.fetchval("SELECT 1 FROM promo_uses WHERE code=$1 AND user_id=$2", code.upper(), user_id)
            if used:
                return {"ok": False, "error": "Ты уже использовал этот промокод"}
            await c.execute("UPDATE promo_codes SET uses=uses+1 WHERE code=$1", code.upper())
            await c.execute("INSERT INTO promo_uses(code,user_id) VALUES($1,$2)", code.upper(), user_id)
            await activate_plan(user_id, promo["plan"], promo["days"])
            return {"ok": True, "plan": promo["plan"], "days": promo["days"]}


async def create_promo(code: str, plan: str, days: int, max_uses: int, expires_days: int = 30) -> bool:
    async with _pool.acquire() as c:
        try:
            await c.execute(
                "INSERT INTO promo_codes(code,plan,days,max_uses,expires_at) VALUES($1,$2,$3,$4,NOW()+$5*INTERVAL '1 day')",
                code.upper(), plan, days, max_uses, expires_days
            )
            return True
        except Exception:
            return False


# ── Достижения ────────────────────────────────────────────────────────────────

ACHIEVEMENTS = {
    "first_chat":  ("🎯", "Первый контакт",   "Провёл первый диалог",      10),
    "chat_10":     ("💬", "Болтун",            "10 диалогов",               25),
    "chat_50":     ("🗣", "Разговорчивый",     "50 диалогов",               75),
    "chat_100":    ("🌟", "Звезда общения",    "100 диалогов",             150),
    "chat_500":    ("🏆", "Мастер диалога",    "500 диалогов",             500),
    "rating_high": ("❤️", "Любимчик",          "Рейтинг выше 8.0",         100),
    "referral_5":  ("👥", "Рекрутёр",          "Пригласил 5 друзей",        50),
    "premium":     ("💎", "Премиум",           "Оформил подписку",          30),
    "vip":         ("👑", "VIP статус",        "Достиг VIP",                80),
}


async def check_achievements(user_id: int) -> list:
    async with _pool.acquire() as c:
        user = await c.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if not user:
            return []
        existing = set(user["achievements"] or [])
        new = []
        checks = {
            "first_chat":  user["total_chats"] >= 1,
            "chat_10":     user["total_chats"] >= 10,
            "chat_50":     user["total_chats"] >= 50,
            "chat_100":    user["total_chats"] >= 100,
            "chat_500":    user["total_chats"] >= 500,
            "rating_high": float(user["rating"] or 0) >= 8.0,
            "referral_5":  user["referral_count"] >= 5,
            "premium":     user.get("is_premium"),
            "vip":         user.get("premium_plan") == "vip",
        }
        for code, cond in checks.items():
            if cond and code not in existing:
                new.append(code)
        if new:
            xp = sum(ACHIEVEMENTS[k][3] for k in new)
            await c.execute(
                "UPDATE users SET achievements=achievements||$2::text[], xp=xp+$3 WHERE id=$1",
                user_id, new, xp
            )
        return new


# ── Статистика ────────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    async with _pool.acquire() as c:
        total_users     = await c.fetchval("SELECT COUNT(*) FROM users") or 0
        active_today    = await c.fetchval("SELECT COUNT(*) FROM users WHERE last_active>NOW()-INTERVAL '24h'") or 0
        online_now      = await c.fetchval("SELECT COUNT(*) FROM users WHERE last_active>NOW()-INTERVAL '5m'") or 0
        total_chats     = await c.fetchval("SELECT COUNT(*) FROM chat_sessions") or 0
        chats_today     = await c.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE started_at>NOW()-INTERVAL '24h'") or 0
        active_chats    = await c.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE status='active'") or 0
        queue_size      = await c.fetchval("SELECT COUNT(*) FROM search_queue") or 0
        premium_users   = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_premium=TRUE") or 0
        pending_reports = await c.fetchval("SELECT COUNT(*) FROM reports WHERE status='pending'") or 0
        rev_stars       = await c.fetchval("SELECT COALESCE(SUM(1),0) FROM payments WHERE provider='stars' AND status='confirmed'") or 0
        rev_ton         = await c.fetchval("SELECT COUNT(*) FROM payments WHERE provider='ton' AND status='confirmed'") or 0
        total_messages  = await c.fetchval("SELECT COUNT(*) FROM messages_log") or 0

        daily_users = await c.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM users "
            "WHERE created_at>NOW()-INTERVAL '7 days' GROUP BY day ORDER BY day"
        )
        daily_chats_data = await c.fetch(
            "SELECT DATE(started_at) as day, COUNT(*) as cnt FROM chat_sessions "
            "WHERE started_at>NOW()-INTERVAL '7 days' GROUP BY day ORDER BY day"
        )
        return {
            "total_users": total_users, "active_today": active_today, "online_now": online_now,
            "total_chats": total_chats, "chats_today": chats_today, "active_chats": active_chats,
            "queue_size": queue_size, "premium_users": premium_users, "pending_reports": pending_reports,
            "payments_stars": rev_stars, "payments_ton": rev_ton, "total_messages": total_messages,
            "daily_users": [{"day": str(r["day"]), "count": r["cnt"]} for r in daily_users],
            "daily_chats": [{"day": str(r["day"]), "count": r["cnt"]} for r in daily_chats_data],
        }


async def get_users_list(limit=50, offset=0, search=None, plan=None, banned=None):
    async with _pool.acquire() as c:
        conds, params, i = [], [], 1
        if search:
            conds.append(f"(username ILIKE ${i} OR first_name ILIKE ${i} OR id::text ILIKE ${i})")
            params.append(f"%{search}%"); i += 1
        if plan:
            conds.append(f"premium_plan=${i}"); params.append(plan); i += 1
        if banned is not None:
            conds.append(f"is_banned=${i}"); params.append(banned); i += 1
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = await c.fetch(
            f"SELECT id,username,first_name,is_premium,premium_plan,premium_until,rating,total_chats,"
            f"total_messages,xp,is_banned,ban_reason,referral_count,created_at,last_active "
            f"FROM users {where} ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}", *params
        )
        total = await c.fetchval(f"SELECT COUNT(*) FROM users {where}", *params)
        return [dict(r) for r in rows], total


async def get_sessions_list(limit=50, offset=0, status=None, user_id=None):
    async with _pool.acquire() as c:
        conds, params, i = [], [], 1
        if status and status != "all":
            conds.append(f"cs.status=${i}"); params.append(status); i += 1
        if user_id:
            conds.append(f"(cs.user_a=${i} OR cs.user_b=${i})"); params.append(user_id); i += 1
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = await c.fetch(
            f"SELECT cs.*, ua.username as username_a, ub.username as username_b, "
            f"ua.first_name as name_a, ub.first_name as name_b "
            f"FROM chat_sessions cs "
            f"LEFT JOIN users ua ON ua.id=cs.user_a "
            f"LEFT JOIN users ub ON ub.id=cs.user_b "
            f"{where} ORDER BY cs.started_at DESC LIMIT {limit} OFFSET {offset}", *params
        )
        total = await c.fetchval(f"SELECT COUNT(*) FROM chat_sessions cs {where}", *params)
        return [dict(r) for r in rows], total


async def get_reports_list(limit=50, offset=0, status="pending"):
    async with _pool.acquire() as c:
        if status and status != "all":
            rows = await c.fetch(
                "SELECT r.*,u1.username as reporter_name,u2.username as reported_name "
                "FROM reports r LEFT JOIN users u1 ON u1.id=r.reporter_id "
                "LEFT JOIN users u2 ON u2.id=r.reported_id "
                "WHERE r.status=$1 ORDER BY r.created_at DESC LIMIT $2 OFFSET $3",
                status, limit, offset
            )
            total = await c.fetchval("SELECT COUNT(*) FROM reports r WHERE r.status=$1", status)
        else:
            rows = await c.fetch(
                "SELECT r.*,u1.username as reporter_name,u2.username as reported_name "
                "FROM reports r LEFT JOIN users u1 ON u1.id=r.reporter_id "
                "LEFT JOIN users u2 ON u2.id=r.reported_id "
                "ORDER BY r.created_at DESC LIMIT $1 OFFSET $2",
                limit, offset
            )
            total = await c.fetchval("SELECT COUNT(*) FROM reports r")
        return [dict(r) for r in rows], total


async def get_payments_list(limit=50, offset=0, provider=None):
    async with _pool.acquire() as c:
        if provider:
            rows = await c.fetch(
                "SELECT p.*,u.username,u.first_name FROM payments p "
                "LEFT JOIN users u ON u.id=p.user_id "
                "WHERE p.provider=$1 ORDER BY p.created_at DESC LIMIT $2 OFFSET $3",
                provider, limit, offset
            )
            total = await c.fetchval("SELECT COUNT(*) FROM payments p WHERE p.provider=$1", provider)
        else:
            rows = await c.fetch(
                "SELECT p.*,u.username,u.first_name FROM payments p "
                "LEFT JOIN users u ON u.id=p.user_id "
                "ORDER BY p.created_at DESC LIMIT $1 OFFSET $2",
                limit, offset
            )
            total = await c.fetchval("SELECT COUNT(*) FROM payments p")
        return [dict(r) for r in rows], total
