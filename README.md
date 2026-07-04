<p align="center">
  <img src="https://img.shields.io/badge/Version-3.13.0--nexus-8b5cf6?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Status-Alpha-orange?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Hysteria-2-ff6b35?style=for-the-badge" alt="Hysteria">
  <img src="https://img.shields.io/badge/DB-PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">FreeLink</h1>

<p align="center">
  <b>Multi-server VPN management panel with subscription system</b><br><br>
  <a href="#english"><img src="https://img.shields.io/badge/English-blue?style=for-the-badge" alt="English"></a>
  <a href="#русский"><img src="https://img.shields.io/badge/Русский-red?style=for-the-badge" alt="Русский"></a>
</p>

---

<a id="english"></a>

# English

> **ALPHA VERSION** — This project is in active development. APIs, features, and configuration may change without notice.

## Features

| Feature | Description |
|---------|-------------|
| **Multi-server** | Main server + unlimited remote nodes via SSH |
| **Subscriptions** | One URL for all servers (Hysteria2, Clash, v2rayN, Happ) |
| **Telegram Bot** | User management, notifications, VPN links |
| **Mini App** | Mobile admin panel for Telegram |
| **Web Panel** | Admin dashboard with real-time metrics |
| **Auto-deploy** | One-click server setup via SSH |
| **Traffic tracking** | Per-user traffic across all nodes (PostgreSQL) |
| **Online detection** | Traffic-change based: compares consecutive snapshots per (user, node) |
| **Plans** | Flexible subscription system with auto-expiry |
| **Speed limits** | Per-user bandwidth control |
| **Auth server** | External Hysteria auth for multi-node setups |
| **Traffic history** | JSON-based charts with period selection |

---

## Quick Start

### Requirements

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- PostgreSQL
- Domain with DNS pointing to server
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
git clone https://github.com/R3G1ST/FreeLink.git /opt/freelink
cd /opt/freelink
chmod +x install.sh
sudo ./install.sh
```

The installer will ask for:
- Domain name
- Server IP
- Telegram Bot Token
- Telegram Admin ID

### After Installation

1. Open `https://your-domain.com`
2. Login: `admin`
3. Password: `admin123`
4. **Change password immediately!**

---

## Update

```bash
cd /opt/freelink
sudo ./update.sh
```

---

## Architecture

```
                         +-----------------+
                         |   Telegram Bot  |
                         |    (bot.py)     |
                         +--------+--------+
                                  |
                         +--------v--------+
                         |    FastAPI       |
          +------------>|    (api.py)      |<------------+
          |             +--------+--------+             |
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   |  Auth Server |       |  PostgreSQL  |       |  Online       |
   |  (auth.py)   |       |  (db.py)     |       |  Detector     |
   |  :8001       |       |  snapshots   |       |  (2s poll)    |
   +--------------+       +--------------+       +-------+-------+
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   |  Hysteria 2  |       | Node Agent   |       | Traffic Saver |
   |  (main)     |       | (node_agent) |       | (60s poll)    |
   +--------------+       +--------------+       +---------------+
```

### Data Flow (Online Detection)

```
Hysteria API (cumulative tx/rx)
       |
       v (every 2s)
online_detector.py --> PostgreSQL traffic_snapshots
       |
       v
get_online_users() --> Compare rank-1 vs rank-2 per (user, node)
       |               If tx/rx CHANGED => online
       v               Speed = delta_bytes / time_delta (bytes/sec)
api.py get_online_status()
       |
       v
/api/users, /api/online, /ws/live, Telegram Bot
```

---

## Project Structure

```
freelink/
├── api.py                  # FastAPI backend (REST + WebSocket)
├── auth.py                 # External Hysteria auth server
├── bot.py                  # Telegram bot
├── db.py                   # PostgreSQL layer (traffic_snapshots, users, nodes)
├── node_agent.py           # Remote node agent (heartbeat + traffic)
├── online_detector.py      # Online detection (2s poll, traffic-change logic)
├── save_traffic.py         # Traffic recorder (60s poll, durability)
├── traffic_history.py      # Traffic history for charts (5min poll)
├── migrate.py              # DB migration script
├── install.sh              # Installation script
├── update.sh               # Update script
├── start.sh                # Start script
├── requirements.txt        # Python dependencies
├── config.yaml             # Active config
├── config.example.yaml     # Config template
├── admins.json             # Admin accounts
├── nodes.json              # Node registry
├── sessions.json           # User sessions
├── plans.json              # Subscription plans
├── subscriptions.json      # User subscriptions
├── data.yaml               # User data (legacy)
├── data.db                 # SQLite (legacy)
├── traffic_history.json    # Traffic chart data
├── online_status.json      # Online cache (written by detector)
├── web/                    # Frontend
│   ├── index.html          # Admin panel
│   ├── miniapp.html        # Telegram Mini App
│   └── client.html         # Client portal
├── scripts/                # Helper scripts
├── backups/                # Backup directory
├── logs/                   # Log files
└── venv/                   # Python virtualenv
```

---

## Services

| Service | Description | Interval |
|---------|-------------|----------|
| `freelink-api` | Main API + WebSocket server | - |
| `freelink-auth` | External Hysteria auth | - |
| `freelink-bot` | Telegram bot | - |
| `freelink-online` | Online detector (Hysteria poll + DB snapshots) | 2s |
| `freelink-traffic` | Traffic saver (backup durability) | 60s |
| `freelink-history` | Traffic history for charts | 5min |

### Management

```bash
systemctl status freelink-api
systemctl restart freelink-api
journalctl -u freelink-api -f
```

---

## Online Detection

The system determines user online status by comparing consecutive traffic snapshots:

1. **Polling**: Hysteria API returns cumulative `tx`/`rx` for all connected users every 2 seconds
2. **Storage**: Snapshots saved to PostgreSQL `traffic_snapshots` table with `captured_at` timestamp
3. **Comparison**: For each `(user, node)` pair, compare rank-1 and rank-2 snapshots
4. **Decision**: User is online only if `tx` or `rx` **changed** between snapshots
5. **Speed**: Calculated as `delta_bytes / time_delta` in bytes/sec

This handles:
- **Main Hysteria**: Polled every 2s, many snapshots per user
- **Remote nodes**: Heartbeat every ~30s via `node_agent.py`, fewer snapshots
- **Ghost entries**: Users who disconnected but Hysteria still lists with static totals

### API Response

```json
{
  "username": {
    "online": true,
    "tx": 26644909,
    "rx": 890639108,
    "tx_speed": 68,
    "rx_speed": 67,
    "last_active": "2026-07-02T21:32:47.534477",
    "inactive_since": null
  }
}
```

- `tx_speed` / `rx_speed`: bytes/sec (real throughput, not raw delta)
- `last_active`: timestamp of most recent snapshot
- `inactive_since`: set when user stops transferring data (>5 min idle)

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users` | GET | User list with online, traffic, speed |
| `/api/user/{uid}` | GET | Single user detail |
| `/api/online` | GET | Online status for all users |
| `/api/status` | GET | Dashboard summary |
| `/api/server-info` | GET | System metrics (CPU/RAM/Disk) |
| `/api/live-traffic` | GET | Online users with speed data |
| `/api/traffic-history` | GET | Historical traffic for charts |
| `/api/nodes` | GET | Node list with status |
| `/api/node/heartbeat` | POST | Remote node heartbeat |
| `/api/node/register` | POST | Register new node |
| `/ws/live` | WebSocket | Real-time traffic + online updates |
| `/s/{token}` | GET | Client self-service portal |
| `/api/client/sub/{token}` | GET | Client subscription data |

---

## Roadmap

### High Priority
- [ ] Complete EN/RU translation (remaining modal content)
- [ ] Fix node connectivity issues (UDP firewall handling)
- [ ] Add speed limit enforcement per user
- [ ] Implement traffic history charts with period selection

### Medium Priority
- [ ] Add 2FA authentication for admin panel
- [ ] Implement user session management
- [ ] Add webhook notifications (Discord, Slack)
- [ ] Create REST API documentation (Swagger/OpenAPI)
- [ ] Implement user groups and bulk operations

### Low Priority
- [ ] Add more languages (Chinese, Spanish, Portuguese)
- [ ] Create mobile app (React Native / Flutter)
- [ ] Implement bandwidth monitoring dashboard
- [ ] Add geo-location based server selection
- [ ] Create backup/restore functionality
- [ ] Add system resource alerts (CPU/RAM/Disk thresholds)

---

## License

[MIT License](LICENSE)

---

<p align="center">
  Made with care for the VPN community
</p>

---

<a id="русский"></a>

# Русский

> **АЛЬФА-ВЕРСИЯ** — Проект в активной разработке. API, функции и конфигурация могут изменяться без уведомления.

## Возможности

| Возможность | Описание |
|-------------|----------|
| **Мульти-сервер** | Основной сервер + неограниченные ноды через SSH |
| **Подписки** | Одна ссылка на все серверы (Hysteria2, Clash, v2rayN, Happ) |
| **Telegram Бот** | Управление пользователями, уведомления, VPN-ссылки |
| **Мини-апп** | Мобильная панель для Telegram |
| **Веб-панель** | Панель администратора с метриками в реальном времени |
| **Авто-деплой** | Настройка сервера в один клик через SSH |
| **Учёт трафика** | Трафик по пользователям на всех нодах (PostgreSQL) |
| **Онлайн-детект** | По изменению трафика: сравнивает снапшоты per (user, node) |
| **Планы** | Гибкая система подписок с авто-истечением |
| **Ограничение скорости** | Контроль пропускной способности per user |
| **Auth-сервер** | Внешняя авторизация Hysteria для мульти-нод |
| **История трафика** | Графики на JSON с выбором периода |

---

## Быстрый старт

### Требования

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- PostgreSQL
- Домен с DNS-записью на сервер
- Telegram Bot Token (от [@BotFather](https://t.me/BotFather))

### Установка

```bash
git clone https://github.com/R3G1ST/FreeLink.git /opt/freelink
cd /opt/freelink
chmod +x install.sh
sudo ./install.sh
```

Установщик запросит:
- Имя домена
- IP сервера
- Telegram Bot Token
- Telegram Admin ID

### После установки

1. Открой `https://ваш-домен.com`
2. Логин: `admin`
3. Пароль: `admin123`
4. **Смените пароль сразу!**

---

## Обновление

```bash
cd /opt/freelink
sudo ./update.sh
```

---

## Архитектура

```
                         +-----------------+
                         |  Telegram Бот   |
                         |    (bot.py)     |
                         +--------+--------+
                                  |
                         +--------v--------+
                         |    FastAPI       |
          +------------>|    (api.py)      |<------------+
          |             +--------+--------+             |
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   | Auth-сервер  |       |  PostgreSQL  |       |   Онлайн-     |
   |  (auth.py)   |       |  (db.py)     |       |   детектор    |
   |  :8001       |       |  снапшоты    |       |  (опрос 2с)   |
   +--------------+       +--------------+       +-------+-------+
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   |  Hysteria 2  |       |  Node Agent  |       | Traffic Saver |
   |  (main)     |       | (node_agent) |       | (опрос 60с)   |
   +--------------+       +--------------+       +---------------+
```

### Поток данных (Онлайн-детект)

```
Hysteria API (кумулятивные tx/rx)
       |
       v (каждые 2с)
online_detector.py --> PostgreSQL traffic_snapshots
       |
       v
get_online_users() --> Сравнивает rank-1 vs rank-2 per (user, node)
       |               Если tx/rx ИЗМЕНИЛИСЬ => онлайн
       v               Скорость = delta_bytes / time_delta (байт/с)
api.py get_online_status()
       |
       v
/api/users, /api/online, /ws/live, Telegram Бот
```

---

## Структура проекта

```
freelink/
├── api.py                  # FastAPI бэкенд (REST + WebSocket)
├── auth.py                 # Внешний auth-сервер Hysteria
├── bot.py                  # Telegram бот
├── db.py                   # PostgreSQL (traffic_snapshots, users, nodes)
├── node_agent.py           # Агент удалённых нод (heartbeat + трафик)
├── online_detector.py      # Онлайн-детект (опрос 2с, сравнение трафика)
├── save_traffic.py         # Запись трафика (опрос 60с, дублирование)
├── traffic_history.py      # История трафика для графиков (опрос 5мин)
├── migrate.py              # Миграция БД
├── install.sh              # Скрипт установки
├── update.sh               # Скрипт обновления
├── start.sh                # Скрипт запуска
├── requirements.txt        # Python зависимости
├── config.yaml             # Активный конфиг
├── config.example.yaml     # Шаблон конфига
├── admins.json             # Аккаунты администраторов
├── nodes.json              # Реестр нод
├── sessions.json           # Сессии пользователей
├── plans.json              # Планы подписок
├── subscriptions.json      # Подписки пользователей
├── data.yaml               # Данные пользователей (legacy)
├── data.db                 # SQLite (legacy)
├── traffic_history.json    # Данные для графиков трафика
├── online_status.json      # Кэш онлайн (пишется детектором)
├── web/                    # Фронтенд
│   ├── index.html          # Панель администратора
│   ├── miniapp.html        # Telegram Мини-апп
│   └── client.html         # Портал клиента
├── scripts/                # Вспомогательные скрипты
├── backups/                # Директория бэкапов
├── logs/                   # Файлы логов
└── venv/                   # Python virtualenv
```

---

## Сервисы

| Сервис | Описание | Интервал |
|--------|----------|----------|
| `freelink-api` | Основной API + WebSocket | - |
| `freelink-auth` | Внешняя авторизация Hysteria | - |
| `freelink-bot` | Telegram бот | - |
| `freelink-online` | Онлайн-детектор (опрос Hysteria + снапшоты в БД) | 2с |
| `freelink-traffic` | Запись трафика (дублирование для надёжности) | 60с |
| `freelink-history` | История трафика для графиков | 5мин |

### Управление

```bash
systemctl status freelink-api
systemctl restart freelink-api
journalctl -u freelink-api -f
```

---

## Онлайн-детект

Система определяет статус онлайн по сравнению последовательных снапшотов трафика:

1. **Опрос**: Hysteria API возвращает кумулятивные `tx`/`rx` для всех подключённых пользователей каждые 2 секунды
2. **Хранение**: Снапшоты сохраняются в PostgreSQL таблицу `traffic_snapshots` с таймстампом `captured_at`
3. **Сравнение**: Для каждой пары `(user, node)` сравниваются rank-1 и rank-2 снапшоты
4. **Решение**: Пользователь онлайн только если `tx` или `rx` **изменились** между снапшотами
5. **Скорость**: Вычисляется как `delta_bytes / time_delta` в байтах/сек

Обрабатывает:
- **Основной Hysteria**: Опрос каждые 2с, много снапшотов на пользователя
- **Удалённые ноды**: Heartbeat каждые ~30с через `node_agent.py`, меньше снапшотов
- **Призраки**: Пользователи отключились, но Hysteria всё ещё выдаёт их со статичными totals

### Ответ API

```json
{
  "username": {
    "online": true,
    "tx": 26644909,
    "rx": 890639108,
    "tx_speed": 68,
    "rx_speed": 67,
    "last_active": "2026-07-02T21:32:47.534477",
    "inactive_since": null
  }
}
```

- `tx_speed` / `rx_speed`: байты/сек (реальная пропускная способность, не сырая дельта)
- `last_active`: таймстамп последнего снапшота
- `inactive_since`: устанавливается когда пользователь прекращает передачу данных (>5 мин idle)

---

## API Эндпоинты

| Эндпоинт | Метод | Описание |
|-----------|-------|----------|
| `/api/users` | GET | Список пользователей с онлайн, трафиком, скоростью |
| `/api/user/{uid}` | GET | Детали одного пользователя |
| `/api/online` | GET | Онлайн-статус всех пользователей |
| `/api/status` | GET | Сводка дашборда |
| `/api/server-info` | GET | Метрики системы (CPU/RAM/Disk) |
| `/api/live-traffic` | GET | Онлайн-пользователи со скоростью |
| `/api/traffic-history` | GET | История трафика для графиков |
| `/api/nodes` | GET | Список нод со статусом |
| `/api/node/heartbeat` | POST | Heartbeat удалённой ноды |
| `/api/node/register` | POST | Регистрация новой ноды |
| `/ws/live` | WebSocket | Трафик + онлайн в реальном времени |
| `/s/{token}` | GET | Портал самообслуживания клиента |
| `/api/client/sub/{token}` | GET | Данные подписки клиента |

---

## Дорожная карта

### Высокий приоритет
- [ ] Завершить перевод EN/RU (остатки контента в модалках)
- [ ] Исправить проблемы подключения к нодам (обработка UDP файрволов)
- [ ] Добавить ограничение скорости для пользователей
- [ ] Реализовать графики истории трафика с выбором периода

### Средний приоритет
- [ ] Добавить 2FA аутентификацию для админ-панели
- [ ] Реализовать управление сессиями пользователей
- [ ] Добавить webhook уведомления (Discord, Slack)
- [ ] Создать документацию API (Swagger/OpenAPI)
- [ ] Реализовать группы пользователей и массовые операции

### Низкий приоритет
- [ ] Добавить больше языков (китайский, испанский, португальский)
- [ ] Создать мобильное приложение (React Native / Flutter)
- [ ] Реализовать дашборд мониторинга пропускной способности
- [ ] Добавить гео-локацию для выбора сервера
- [ ] Создать функционал бэкапа/восстановления
- [ ] Добавить оповещения о ресурсах системы (пороги CPU/RAM/Disk)

---

## Changelog

### v3.13.0-nexus (2026-07-04)

#### Features
- **DNS Logging** — автоматическое логирование DNS-запросов VPN-клиентов через dnsmasq
- **Structured Logs** — единая страница логов с фильтрами в стиле панели
- **Real-time Logs** — WebSocket + poll обновляют логи каждые 1-3 секунды
- **CSV Export** — экспорт логов в CSV файл
- **Server Selector** — выбор сервера на дашборде для просмотра статистики нод
- **Widget Drag & Drop** — свободное перемещение виджетов на дашборде
- **Widget Customization** — включение/выключение виджетов, сохранение в localStorage
- **16 Dashboard Widgets** — процессор, RAM, диск, сеть, аптайм, Hysteria, ноды, топ и др.
- **Node Stats on Dashboard** — CPU/RAM/Disk удалённых нод отображаются в реальном времени
- **Improved Traffic Display** — формат "5 ГБ 340 МБ" вместо "5.3 ГБ"
- **Traffic Aggregation** — трафик суммируется со всех нод

#### Bug Fixes
- **WebSocket Auth** — исправлена авторизация WebSocket через localStorage
- **DNS Filter** — фильтр DNS теперь работает (исправлена корреляция IP)
- **Node Data** — ноды отправляют RAM/Disk GB значения
- **Session Token** — добавлен эндпоинт `/api/session-token` для получения токена
- **Panel Style Filters** — фильтры логов в стиле панели (.fgr/.fb классы)

#### Infrastructure
- **dnsmasq** — DNS-сервер с логированием запросов
- **freelink-dns** — systemd сервис для DNS-наблюдателя
- **DNS Watcher** — мониторинг DNS-логов и привязка к VPN-пользователям

### v3.12.0-aurora (2026-07-04)

#### Features
- **Device Limit** — ограничение количества устройств на аккаунт (max_devices)
- **Connection Tracking** — полная история подключений (IP, время, длительность, нода)
- **Auth Hardening** — блокировка просроченных и неактивных пользователей на уровне auth
- **User Modal Tabs** — модалка пользователя разбита на 5 вкладок: Инфо, Скорость, Трафик, Устройства, Действия
- **Settings Page** — кнопки Очистить/Перезапуск/Экспорт/Отчёт перенесены в Настройки
- **Node Names** — история подключений показывает имена нод вместо ID

#### Bug Fixes
- **Happ Error 39** — `/sub/` добавлен в публичные эндпоинты
- **PostgreSQL Compatibility** — `make_interval` заменён на `INTERVAL` синтаксис
- **Auth Date Format** — поддержка форматов `HH:MM` и `HH:MM:SS` для expire_date
- **Device Count** — дедупликация подключений с одного IP в течение 5 минут

---

### v3.11.0-supernova (2026-07-04)

#### Security Fixes (Critical)
- **SQL Injection** — whitelist для `update_user_field` в `db.py`
- **Telegram Auth** — HMAC-проверка подписи `initData`
- **Session Fixation** — валидация токена перед установкой cookie
- **Path Traversal** — regex-валидация имён бэкапов
- **Tarball Slip** — проверка имён файлов при распаковке
- **Node Registration** — проверка `NODE_API_KEY` из env
- **SSH Policy** — заменён `AutoAddPolicy` на `WarningPolicy`
- **Cookie Security** — добавлен `secure=True` на все cookies
- **Rate Limiting** — `/api/auth` защищён `5 req/min`
- **GeoIP SSRF** — валидация IP через `ipaddress.ip_address()`
- **Password Export** — удалены пароли из `/api/export`
- **CORS** — `allow_headers` ограничен `Content-Type, Authorization`
- **Weak Crypto** — `gen_id()` заменён на `secrets.token_hex()`
- **Password Verify** — поддержка legacy SHA-256 + bcrypt

#### Security Fixes (High)
- **Environment Variables** — все секреты вынесены в `.env`
- **File Permissions** — `.env` и `admins.json` → `chmod 600`
- **Obfs Password** — заменён хардкод на env var в deploy-скриптах
- **Bare Except** — все `except:` заменены на `except Exception:`
- **RBAC** — проверка роли admin/editor на `/api/clean`, `/api/restart`, `/api/logs`
- **Nginx Headers** — X-Frame-Options, HSTS, X-Content-Type-Options
- **Nginx SSL** — `ssl_prefer_server_ciphers`, `ssl_session_cache`
- **Backup Security** — TLS приватные ключи исключены из архивов
- **Systemd** — `EnvironmentFile=/opt/freelink/.env` во все сервисы

#### Database
- **Indexes** — добавлены индексы: `users(name)`, `users(active)`, `users(expire_date)`, `sessions(expires)`, `subscriptions(uid)`, `audit_log(time)`
- **Session Management** — атомарные SQL-операции вместо read-modify-write

#### UI/UX (Admin Panel)
- **User Modal Tabs** — модалка пользователя разбита на 4 вкладки: Инфо, Скорость, Трафик, Действия
- **User Modal Logo** — SVG-логотип FreeLink вместо иконки пользователя
- **Speed Tab** — кнопки быстрого выбора: 5/10/20/50/100 Мбит/с
- **Extend Modal** — быстрые кнопки: 7/14/30/90/180/365 дн + Бесконечно
- **Settings Page** — кнопки Очистить/Перезапуск/Экспорт/Отчёт перенесены из Пользователей
- **Users Page** — добавлена кнопка «Обновить» для обновления статистики
- **Search Compact** — поле поиска уменьшено, фильтры прижаты вправо
- **Navigation** — «Настройки» добавлен в сайдбар

#### Bug Fixes
- **Login Fix** — `verify_pw()` поддерживает legacy SHA-256 хеши
- **Node Heartbeat** — исправлен middleware, пропускает `/api/node/*`
- **IP in User Modal** — поле IP теперь отображается из БД
- **Bare Except** — исправлены во всех Python-файлах
- **Resource Monitor** — чтение токена из env vars вместо config.yaml

---

## Лицензия

[MIT License](LICENSE)

---

<p align="center">
  Сделано с заботой для VPN-сообщества
</p>
