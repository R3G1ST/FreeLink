#!/usr/bin/env python3
import os, sys, yaml, logging, subprocess, random, string, json, secrets, requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes

sys.path.insert(0, "/opt/freelink")
import db

CONFIG_FILE = "/opt/freelink/config.yaml"
ONLINE_FILE = "/opt/freelink/online_status.json"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NAME, EXPIRE = range(2)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except:
        return None

def load_data():
    users = db.get_all_users()
    return {"servers": {}, "users": users}

def save_data(data):
    for uid, user_data in data.get("users", {}).items():
        db.save_user(uid, user_data)

def is_admin(user_id):
    config = load_config()
    if not config:
        return False
    return user_id in config.get("telegram", {}).get("admins", [])

def gen_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def gen_link(uid):
    config = load_config()
    data = load_data()
    user = data.get("users", {}).get(uid)
    if not user:
        return ""
    h = config.get("hysteria", {})
    s = config.get("server", {})
    domain = s.get("domain", "link.qmbox.ru")
    port = 443
    name = user.get("name", uid)
    password = user.get("password", h.get("user_password", ""))
    obfs = h.get("obfs_password", "")
    if obfs:
        return f"hysteria2://{name}:{password}@{domain}:{port}?sni={domain}&obfs=salamander&obfs-password={obfs}&insecure=0#{name}"
    return f"hysteria2://{name}:{password}@{domain}:{port}?sni={domain}&insecure=0#{name}"

def format_traffic(bytes_val):
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"

def get_online_status():
    try:
        db.init_db()
        return db.get_online_users(window_seconds=60)
    except Exception as e:
        logger.error(f"Failed to get online status: {e}")
        return {}

def get_server_info():
    try:
        import psutil
        info = {}
        info["cpu"] = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        info["ram_pct"] = mem.percent
        info["ram_used"] = round(mem.used / (1024**3), 1)
        info["ram_total"] = round(mem.total / (1024**3), 1)
        disk = psutil.disk_usage('/')
        info["disk_pct"] = disk.percent
        info["disk_used"] = round(disk.used / (1024**3), 1)
        info["disk_total"] = round(disk.total / (1024**3), 1)
        return info
    except:
        return {}

def check_hysteria():
    try:
        r = subprocess.run(["/usr/bin/systemctl", "is-active", "hysteria-server"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except:
        return False

# ====== MAIN KEYBOARD ======

def get_main_keyboard():
    """Inline keyboard buttons in chat."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список", callback_data="list"),
         InlineKeyboardButton("➕ Создать", callback_data="create")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats"),
         InlineKeyboardButton("🖥 Сервер", callback_data="server")],
        [InlineKeyboardButton("🌐 Панель", web_app=WebAppInfo(url="https://link.qmbox.ru/app")),
         InlineKeyboardButton("⚙️ Сервисы", callback_data="services")],
        [InlineKeyboardButton("🧹 Очистить", callback_data="clean"),
         InlineKeyboardButton("📋 Логи", callback_data="logs")],
    ])

# ====== COMMANDS ======

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    if not is_admin(user_id):
        if query:
            await query.answer("⛔ Доступ запрещён", show_alert=True)
        else:
            await update.message.reply_text("⛔ Доступ запрещён.")
        return
    text = (
        "⚡ <b>FreeLink Manager</b>\n\n"
        "Выберите действие:"
    )
    kb = get_main_keyboard()
    if query:
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and not is_admin(query.from_user.id):
        await query.answer("⛔ Доступ запрещён", show_alert=True)
        return

    data = load_data()
    users = data.get("users", {})
    online = get_online_status()

    if not users:
        msg = "📭 Нет пользователей."
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    lines = []
    for uid, user in users.items():
        status = "🟢" if user.get("active", True) else "🔴"
        name = user.get("name", uid)
        expire = user.get("expire_date", "?")
        is_online = online.get(name, {}).get("online", False)
        online_mark = " ●" if is_online else ""
        lines.append(f"{status} <b>{name}</b>{online_mark} | до {expire}")

    text = "👥 <b>Пользователи:</b>\n\n" + "\n".join(lines)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()
    users = data.get("users", {})
    active = sum(1 for u in users.values() if u.get("active", True))
    online = get_online_status()
    online_count = sum(1 for u in online.values() if u.get("online"))
    hysteria_ok = check_hysteria()

    text = (
        f"📊 <b>Статус сервера</b>\n\n"
        f"Hysteria 2: {'🟢 Работает' if hysteria_ok else '🔴 Остановлен'}\n"
        f"Всего пользователей: {len(users)}\n"
        f"Активных: {active}\n"
        f"Онлайн: {online_count}\n"
        f"Сервер: Польша (link.qmbox.ru)"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="status")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()
    users = data.get("users", {})
    online = get_online_status()

    if not users:
        msg = "📭 Нет данных."
        if query:
            await query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    total_tx = 0
    total_rx = 0
    lines = []
    for uid, user in users.items():
        ts = user.get("traffic_saved", {})
        tx = ts.get("tx", 0)
        rx = ts.get("rx", 0)
        total_tx += tx
        total_rx += rx
        name = user.get("name", uid)
        is_online = online.get(name, {}).get("online", False)
        mark = "🟢" if is_online else "⚪"
        lines.append(f"{mark} <b>{name}</b>: ⬆{format_traffic(tx)} ⬇{format_traffic(rx)}")

    text = (
        f"📈 <b>Статистика трафика</b>\n\n"
        + "\n".join(lines) +
        f"\n\n📊 <b>Итого:</b>\n⬆ TX: {format_traffic(total_tx)}\n⬇ RX: {format_traffic(total_rx)}\n"
        f"📦 Всего: {format_traffic(total_tx + total_rx)}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    info = get_server_info()
    if not info:
        msg = "❌ Не удалось получить информацию о сервере"
        if query:
            await query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    def bar(pct):
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    text = (
        f"🖥 <b>Сервер</b>\n\n"
        f"💻 CPU: {info.get('cpu', 0)}%\n"
        f"<code>{bar(info.get('cpu', 0))}</code>\n\n"
        f"🧠 RAM: {info.get('ram_pct', 0)}% ({info.get('ram_used', 0)}/{info.get('ram_total', 0)} GB)\n"
        f"<code>{bar(info.get('ram_pct', 0))}</code>\n\n"
        f"💾 Диск: {info.get('disk_pct', 0)}% ({info.get('disk_used', 0)}/{info.get('disk_total', 0)} GB)\n"
        f"<code>{bar(info.get('disk_pct', 0))}</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="server")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        result = subprocess.run(
            ["/usr/bin/journalctl", "-u", "hysteria-server", "-n", "20", "--no-pager"],
            capture_output=True, text=True, timeout=10
        )
        logs = result.stdout.strip()
        if not logs:
            logs = "Нет логов"
        if len(logs) > 3000:
            logs = logs[-3000:]
        text = f"📋 <b>Последние логи:</b>\n\n<pre>{logs}</pre>"
    except Exception as e:
        text = f"❌ Ошибка: {e}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="logs")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ====== CREATE USER ======

async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("✏️ Введите <b>имя</b> пользователя (латиница):", parse_mode="HTML")
    else:
        await update.message.reply_text("✏️ Введите <b>имя</b> пользователя (латиница):", parse_mode="HTML")
    return NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("⚠️ Имя слишком короткое (минимум 2 символа). Попробуйте ещё раз:")
        return NAME
    context.user_data["create_name"] = name
    keyboard = [
        [InlineKeyboardButton("7 дней", callback_data="days_7"),
         InlineKeyboardButton("30 дней", callback_data="days_30")],
        [InlineKeyboardButton("90 дней", callback_data="days_90"),
         InlineKeyboardButton("365 дней", callback_data="days_365")],
        [InlineKeyboardButton("♾ Безлимит", callback_data="days_36500")],
    ]
    await update.message.reply_text(
        f"👤 Имя: <b>{name}</b>\n📅 Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return EXPIRE

async def create_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    days = int(query.data.split("_")[1])
    name = context.user_data.get("create_name", "unknown")

    data = load_data()
    uid = gen_id()
    password = secrets.token_urlsafe(16)
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    data["users"][uid] = {
        "name": name,
        "active": True,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expire_date": expire_date,
        "port": 443,
        "server": "main",
        "password": password,
        "traffic_limit": 0,
        "traffic_used": 0,
        "devices": [],
        "total_sessions": 0
    }
    save_data(data)
    link = gen_link(uid)
    data["users"][uid]["link"] = link
    save_data(data)

    await query.edit_message_text(
        f"✅ <b>Пользователь создан!</b>\n\n"
        f"👤 Имя: {name}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 До: {expire_date}\n"
        f"🔗 Ссылка:\n<code>{link}</code>",
        parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def create_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# ====== CALLBACK ROUTER ======

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Доступ запрещён", show_alert=True)
        return

    data_load = query.data

    if data_load == "back":
        await cmd_start(update, context)
        await query.answer()
    elif data_load == "list":
        await cmd_list(update, context)
        await query.answer()
    elif data_load == "status":
        await cmd_status(update, context)
        await query.answer()
    elif data_load == "stats":
        await cmd_stats(update, context)
        await query.answer()
    elif data_load == "server":
        await cmd_server(update, context)
        await query.answer()
    elif data_load == "logs":
        await cmd_logs(update, context)
        await query.answer()
    elif data_load == "services":
        await cmd_services(update, context)
        await query.answer()
    elif data_load == "clean":
        await clean_expired(query)
        await query.answer()
    elif data_load.startswith("toggle_"):
        uid = data_load.replace("toggle_", "")
        await toggle_user_cb(query, uid)
    elif data_load.startswith("delete_"):
        uid = data_load.replace("delete_", "")
        await delete_user_cb(query, uid)
    elif data_load.startswith("extend_"):
        uid = data_load.replace("extend_", "")
        await extend_user_cb(query, uid)
    elif data_load.startswith("info_"):
        uid = data_load.replace("info_", "")
        await user_info_cb(query, uid)

async def cmd_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    services = ["hysteria-server", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    lines = []
    for svc in services:
        try:
            r = subprocess.run(["/usr/bin/systemctl", "is-active", svc], capture_output=True, text=True, timeout=3)
            active = r.stdout.strip() == "active"
            icon = "🟢" if active else "🔴"
            lines.append(f"{icon} <code>{svc}</code>")
        except:
            lines.append(f"⚪ <code>{svc}</code>")

    text = "⚙️ <b>Сервисы:</b>\n\n" + "\n".join(lines)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="services")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    if query:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def clean_expired(query):
    data = load_data()
    users = data.get("users", {})
    deleted = 0
    now = datetime.now()
    for uid, user in list(users.items()):
        expire = user.get("expire_date", "")
        if expire:
            try:
                if datetime.strptime(expire, "%Y-%m-%d %H:%M") < now:
                    del data["users"][uid]
                    deleted += 1
            except:
                pass
    save_data(data)
    await query.edit_message_text(f"🧹 Удалено просроченных: <b>{deleted}</b>", parse_mode="HTML")

async def toggle_user_cb(query, uid):
    data = load_data()
    user = data.get("users", {}).get(uid)
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return
    user["active"] = not user.get("active", True)
    save_data(data)
    status = "включён" if user["active"] else "выключен"
    await query.answer(f"Пользователь {status}")
    await cmd_list(query, None)

async def delete_user_cb(query, uid):
    data = load_data()
    if uid in data.get("users", {}):
        name = data["users"][uid].get("name", uid)
        del data["users"][uid]
        save_data(data)
        await query.answer(f"Пользователь {name} удалён")
        await cmd_list(query, None)
    else:
        await query.answer("Пользователь не найден", show_alert=True)

async def extend_user_cb(query, uid):
    data = load_data()
    user = data.get("users", {}).get(uid)
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return
    try:
        current = datetime.strptime(user["expire_date"], "%Y-%m-%d %H:%M")
    except:
        current = datetime.now()
    user["expire_date"] = (current + timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    save_data(data)
    await query.answer(f"Продлено до {user['expire_date']}")

async def user_info_cb(query, uid):
    data = load_data()
    user = data.get("users", {}).get(uid)
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    ts = user.get("traffic_saved", {})
    tx = format_traffic(ts.get("tx", 0))
    rx = format_traffic(ts.get("rx", 0))
    total = format_traffic(ts.get("tx", 0) + ts.get("rx", 0))

    online = get_online_status()
    name = user.get("name", uid)
    is_online = online.get(name, {}).get("online", False)
    last_seen = online.get(name, {}).get("last_active", "—")

    status = "🟢 Активен" if user.get("active", True) else "🔴 Выключен"
    online_text = f"🟢 Онлайн (активен: {last_seen})" if is_online else "⚪ Офлайн"
    link = gen_link(uid)

    text = (
        f"👤 <b>{name}</b>\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"📊 {status}\n"
        f"📡 {online_text}\n"
        f"📅 Создан: {user.get('created', '?')}\n"
        f"📅 Истекает: {user.get('expire_date', '?')}\n"
        f"🔗 Порт: {user.get('port', 443)}\n\n"
        f"📈 <b>Трафик:</b>\n"
        f"⬆ TX: {tx}\n"
        f"⬇ RX: {rx}\n"
        f"📊 Всего: {total}\n\n"
        f"🔗 Ссылка:\n<code>{link}</code>"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 Вкл/Выкл", callback_data=f"toggle_{uid}"),
         InlineKeyboardButton("⏰ +30 дней", callback_data=f"extend_{uid}")],
        [InlineKeyboardButton("❌ Удалить", callback_data=f"delete_{uid}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="list")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

# ====== MAIN ======

def main():
    db.init_db()
    config = load_config()
    if not config:
        logger.error("Cannot load config.yaml")
        return

    token = config.get("telegram", {}).get("token")
    if not token:
        logger.error("Telegram token not found")
        return

    app_builder = Application.builder().token(token).build()

    create_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern="^create$"),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            EXPIRE: [CallbackQueryHandler(create_days_callback, pattern="^days_")],
        },
        fallbacks=[CommandHandler("cancel", create_cancel)],
    )

    app_builder.add_handler(create_conv)
    app_builder.add_handler(CommandHandler("start", cmd_start))
    app_builder.add_handler(CommandHandler("stats", cmd_stats))
    app_builder.add_handler(CommandHandler("server", cmd_server))
    app_builder.add_handler(CommandHandler("logs", cmd_logs))
    app_builder.add_handler(CallbackQueryHandler(button_callback))

    # Notify about expiring users every 6 hours
    async def notify_expiring(context: ContextTypes.DEFAULT_TYPE):
        data = load_data()
        admins = config.get("telegram", {}).get("admins", [])
        now = datetime.now()
        for uid, user in data.get("users", {}).items():
            expire_str = user.get("expire_date", "")
            if not expire_str:
                continue
            try:
                expire_dt = datetime.strptime(expire_str, "%Y-%m-%d %H:%M")
                days_left = (expire_dt - now).days
                if days_left in (0, 1, 3):
                    for admin_id in admins:
                        try:
                            await context.bot.send_message(
                                admin_id,
                                f"⚠️ <b>{user.get('name', uid)}</b> — подписка истекает через {days_left} дн.\n"
                                f"📅 До: {expire_str}",
                                parse_mode="HTML"
                            )
                        except:
                            pass
            except:
                pass

    job_queue = app_builder.job_queue
    if job_queue:
        job_queue.run_repeating(notify_expiring, interval=21600, first=60)

    logger.info("Bot started")
    app_builder.run_polling()

if __name__ == "__main__":
    main()
