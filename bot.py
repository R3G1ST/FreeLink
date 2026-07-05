#!/usr/bin/env python3
import os, sys, yaml, logging, subprocess, random, string, json, secrets, requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.insert(0, "/opt/freelink")
import db

CONFIG_FILE = "/opt/freelink/config.yaml"
ONLINE_FILE = "/opt/freelink/online_status.json"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NAME, EXPIRE, PROTOCOL = range(3)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception:
        return None

def load_data():
    users = db.get_all_users()
    return {"servers": {}, "users": users}

def save_data(data):
    for uid, user_data in data.get("users", {}).items():
        db.save_user(uid, user_data)

def is_admin(user_id):
    # Check environment variable first
    admin_ids_str = os.environ.get("TELEGRAM_ADMIN_IDS", "")
    if admin_ids_str:
        try:
            admin_ids = [int(x.strip()) for x in admin_ids_str.split(",")]
            if user_id in admin_ids:
                return True
        except ValueError:
            pass
    
    # Fallback to config
    config = load_config()
    if not config:
        return False
    return user_id in config.get("telegram", {}).get("admins", [])

def gen_id():
    return secrets.token_hex(4)

def gen_link(uid):
    config = load_config()
    data = load_data()
    user = data.get("users", {}).get(uid)
    if not user:
        return ""
    protocol = user.get("protocol", "hysteria2")

    if protocol == "wireguard":
        import wireguard
        privkey = user.get("wg_private_key", "")
        wg_ip = user.get("wg_address", "")
        if privkey and wg_ip:
            return wireguard.generate_client_uri(privkey, wg_ip, user.get("name", uid))
        return ""

    h = config.get("hysteria", {}) if config else {}
    s = config.get("server", {}) if config else {}
    domain = os.environ.get("DOMAIN", s.get("domain", "link.qmbox.ru"))
    port = 8443
    name = user.get("name", uid)
    password = user.get("password", os.environ.get("HYSTERIA_USER_PASSWORD", ""))
    obfs = os.environ.get("HYSTERIA_OBFS_PASSWORD", "")
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
    except Exception:
        return {}

def check_hysteria():
    try:
        r = subprocess.run(["/usr/bin/systemctl", "is-active", "hysteria-server"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False

# ====== MAIN KEYBOARD ======

def get_main_keyboard():
    """Reply keyboard — bottom buttons on mobile."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📋 Список"), KeyboardButton("➕ Создать")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("🖥 Сервер")],
        [KeyboardButton("🚀 Панель")],
        [KeyboardButton("⚙️ Сервисы"), KeyboardButton("🧹 Очистить")],
    ], resize_keyboard=True)

# ====== COMMANDS ======

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    text = "⚡ <b>FreeLink Manager</b>\n\nВыберите действие:"
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    users = data.get("users", {})
    online = get_online_status()

    if not users:
        await update.message.reply_text("📭 Нет пользователей.", reply_markup=get_main_keyboard())
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
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    users = data.get("users", {})
    online = get_online_status()

    if not users:
        await update.message.reply_text("📭 Нет данных.", reply_markup=get_main_keyboard())
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
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

async def cmd_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = get_server_info()
    if not info:
        await update.message.reply_text("❌ Не удалось получить информацию о сервере", reply_markup=get_main_keyboard())
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
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

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
    context.user_data["create_protos"] = ["hysteria2"]
    keyboard = [
        [InlineKeyboardButton("⚡ Hysteria2 ✅", callback_data="proto_hysteria2")],
        [InlineKeyboardButton("🔒 WireGuard", callback_data="proto_wireguard")],
        [InlineKeyboardButton("✅ Готово", callback_data="proto_done")],
    ]
    await update.message.reply_text(
        f"👤 Имя: <b>{name}</b>\n🔌 Выберите протоколы (нажмите для включения/выключения):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return PROTOCOL

async def create_protocol_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "proto_done":
        protos = context.user_data.get("create_protos", ["hysteria2"])
        if not protos:
            protos = ["hysteria2"]
        context.user_data["create_protocols"] = ",".join(protos)
        proto_labels = []
        for p in protos:
            proto_labels.append("⚡ Hysteria2" if p == "hysteria2" else "🔒 WireGuard")
        keyboard = [
            [InlineKeyboardButton("7 дней", callback_data="days_7"),
             InlineKeyboardButton("30 дней", callback_data="days_30")],
            [InlineKeyboardButton("90 дней", callback_data="days_90"),
             InlineKeyboardButton("365 дней", callback_data="days_365")],
            [InlineKeyboardButton("♾ Безлимит", callback_data="days_36500")],
        ]
        await query.edit_message_text(
            f"👤 Имя: <b>{context.user_data.get('create_name', '')}</b>\n"
            f"🔌 Протоколы: <b>{' + '.join(proto_labels)}</b>\n"
            f"📅 Выберите срок подписки:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return EXPIRE

    # Toggle protocol
    proto = data.replace("proto_", "")
    protos = context.user_data.get("create_protos", ["hysteria2"])
    if proto in protos:
        protos.remove(proto)
    else:
        protos.append(proto)
    if not protos:
        protos = ["hysteria2"]
    context.user_data["create_protos"] = protos

    # Rebuild keyboard with checkmarks
    h2_on = "✅" if "hysteria2" in protos else ""
    wg_on = "✅" if "wireguard" in protos else ""
    keyboard = [
        [InlineKeyboardButton(f"⚡ Hysteria2 {h2_on}", callback_data="proto_hysteria2")],
        [InlineKeyboardButton(f"🔒 WireGuard {wg_on}", callback_data="proto_wireguard")],
        [InlineKeyboardButton("✅ Готово", callback_data="proto_done")],
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    return PROTOCOL

async def create_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    days = int(query.data.split("_")[1])
    name = context.user_data.get("create_name", "unknown")
    protocols = context.user_data.get("create_protocols", "hysteria2")
    proto_list = [p.strip() for p in protocols.split(",") if p.strip()]

    data = load_data()
    uid = gen_id()
    password = secrets.token_urlsafe(16)
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    user_data = {
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
        "total_sessions": 0,
        "protocols": protocols,
        "protocol": proto_list[0] if proto_list else "hysteria2"
    }

    if "wireguard" in proto_list:
        import wireguard
        user_data = wireguard.setup_user_wg(user_data)

    data["users"][uid] = user_data
    save_data(data)
    link = gen_link(uid)
    data["users"][uid]["link"] = link
    save_data(data)

    proto_labels = []
    for p in proto_list:
        proto_labels.append("⚡ Hysteria2" if p == "hysteria2" else "🔒 WireGuard")
    wg_info = ""
    if "wireguard" in proto_list:
        wg_info = f"\n🌐 WG IP: {user_data.get('wg_address', '')}"
    await query.edit_message_text(
        f"✅ <b>Пользователь создан!</b>\n\n"
        f"👤 Имя: {name}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 До: {expire_date}\n"
        f"🔌 Протоколы: {' + '.join(proto_labels)}{wg_info}\n"
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
    print(f"[BOT] button_callback: data={query.data}, user_id={query.from_user.id}", flush=True)
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
    services = ["hysteria-server", "xray", "wg-quick@wg0", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    lines = []
    for svc in services:
        try:
            r = subprocess.run(["/usr/bin/systemctl", "is-active", svc], capture_output=True, text=True, timeout=3)
            active = r.stdout.strip() == "active"
            icon = "🟢" if active else "🔴"
            lines.append(f"{icon} <code>{svc}</code>")
        except Exception:
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
            except Exception:
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
    except Exception:
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
    
    # Read Telegram token from environment variable
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        # Fallback to config for backward compatibility
        token = config.get("telegram", {}).get("token") if config else None
    if not token:
        logger.error("Telegram token not found. Set TELEGRAM_TOKEN in .env")
        return

    # Read admin IDs from environment variable
    admin_ids_str = os.environ.get("TELEGRAM_ADMIN_IDS", "")
    if admin_ids_str:
        try:
            admin_ids = [int(x.strip()) for x in admin_ids_str.split(",")]
            if config:
                config.setdefault("telegram", {})["admins"] = admin_ids
        except ValueError:
            logger.error("Invalid TELEGRAM_ADMIN_IDS format")

    app_builder = Application.builder().token(token).build()

    create_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern="^create$"),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            PROTOCOL: [CallbackQueryHandler(create_protocol_callback, pattern="^proto_")],
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

    # Reply keyboard text handler
    async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text if update.message else ""
        user_id = update.effective_user.id
        if not is_admin(user_id):
            return
        if text == "📋 Список":
            await cmd_list(update, context)
        elif text == "➕ Создать":
            await create_start(update, context)
        elif text == "📊 Статистика":
            await cmd_stats(update, context)
        elif text == "🖥 Сервер":
            await cmd_server(update, context)
        elif text == "🚀 Панель":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Mini App", web_app=WebAppInfo(url="https://link.qmbox.ru/app"))],
                [InlineKeyboardButton("🔗 Открыть в браузере", url="https://link.qmbox.ru/app")]
            ])
            await update.message.reply_text(
                "Выберите способ открытия:",
                reply_markup=keyboard
            )
        elif text == "⚙️ Сервисы":
            await cmd_services(update, context)
        elif text == "🧹 Очистить":
            data = load_data()
            deleted = 0
            now = datetime.now()
            for uid, user_data in list(data.get("users", {}).items()):
                expire = user_data.get("expire_date", "")
                if expire:
                    try:
                        if datetime.strptime(expire, "%Y-%m-%d %H:%M") < now:
                            del data["users"][uid]
                            deleted += 1
                    except Exception:
                        pass
            save_data(data)
            await update.message.reply_text(f"🧹 Удалено просроченных: {deleted}", reply_markup=get_main_keyboard())

    app_builder.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

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
                        except Exception:
                            pass
            except Exception:
                pass

    job_queue = app_builder.job_queue
    if job_queue:
        job_queue.run_repeating(notify_expiring, interval=21600, first=60)

    logger.info("Bot started")
    app_builder.run_polling()

if __name__ == "__main__":
    main()
