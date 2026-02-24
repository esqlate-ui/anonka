# 🎭 Anonka — Анонимный Telegram-бот

Полноценный анонимный чат с Premium-подпиской, оплатой через TON и Telegram Stars, веб-панелью администратора с просмотром всех чатов.

---

## 🚀 Деплой на Railway (рекомендуется)

1. Зайди на [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Добавь PostgreSQL: **+ New → Database → PostgreSQL**
3. В Settings → Variables добавь:

| Переменная | Значение |
|---|---|
| `DATABASE_URL` | скопируй из PostgreSQL сервиса |
| `WEBHOOK_HOST` | твой домен Railway (Settings → Domains) |
| `BOT_TOKEN` | уже вписан в config.py |
| `PORT` | 8080 |

4. Deploy → готово!

---

## 🛠 Локальная разработка

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://user:pass@localhost/anonka
python main.py
```

Без `WEBHOOK_HOST` бот автоматически запустится в режиме **polling**.

---

## 🌐 Админ-панель

Адрес: `https://your-app.railway.app/admin`  
Пароль: **admin2625**

### Возможности:
- 📊 Дашборд с графиками и статистикой
- 🔴 Онлайн-мониторинг (обновляется каждые 10 сек)
- 👥 Управление пользователями (бан/разбан, выдача Premium)
- 💬 **Просмотр всех чатов** — текст, медиа, файлы, голосовые
- ⚠️ Обработка жалоб (бан / отклонить)
- 💰 История платежей (Stars + TON)
- 📢 Рассылка (всем / Premium / бесплатным)
- 🔥 Управление горячими темами
- 🎟 Создание промокодов

---

## 💎 Тарифы

| | ⚡ Базовый | 🔥 Про | 👑 VIP |
|---|---|---|---|
| Telegram Stars | 50 ⭐ | 125 ⭐ | 300 ⭐ |
| TON | 0.5 TON | 1.2 TON | 2.5 TON |
| Без рекламы | ✅ | ✅ | ✅ |
| Фильтр по полу | ✅ | ✅ | ✅ |
| Приоритет в очереди | — | ✅ | ✅ ×10 |
| Фильтр по интересам | — | ✅ | ✅ |
| Анонимные подарки | — | ✅ | ✅ |
| Горячие темы | — | ✅ | ✅ |
| Stories 24ч | — | — | ✅ |
| VIP значок | — | — | ✅ |

---

## 💎 TON оплата

Кошелёк: `UQDZwUwWPTFJ58IwPQGs0BKXxLTKM_-r6A6sEN8YDfq5HSOY`

**Без TON API ключа:** пользователь нажимает "Я оплатил" → тебе приходит уведомление в Telegram → ты подтверждаешь одной кнопкой.

**С TON API ключом** (от toncenter.com): проверка автоматическая. Добавь `TON_API_KEY` в переменные Railway.

---

## 📱 Команды бота

| Команда | Описание |
|---|---|
| /start | Начало / профиль |
| /premium | Тарифы |
| /profile | Профиль |

### Команды администратора (только ты):
| Команда | Описание |
|---|---|
| /admin | Ссылка на панель |
| /stats | Быстрая статистика |
| /ban <id> [причина] | Заблокировать |
| /unban <id> | Разблокировать |
| /grant <id> <план> <дней> | Выдать Premium |
| /promo <код> <план> <дней> <кол-во> | Создать промокод |
| /broadcast <текст> | Рассылка |

---

## 📁 Структура

```
anonka/
├── main.py                 # Точка входа + API
├── config/config.py        # Настройки (токен, кошелёк и т.д.)
├── database/db.py          # Схема БД + все запросы
├── bot/
│   ├── handlers/
│   │   ├── main.py         # Чат, поиск, профиль
│   │   ├── payments.py     # TON + Stars оплата
│   │   └── admin.py        # Команды администратора
│   └── keyboards/
│       └── keyboards.py    # Клавиатуры
├── admin/
│   └── panel.html          # Веб-панель
├── requirements.txt
├── Dockerfile
└── .env.example
```
