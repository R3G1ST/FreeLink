<p align="center">
  <img src="https://img.shields.io/badge/Version-3.8--alpha-8b5cf6?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Status-Alpha-orange?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Hysteria-2-ff6b35?style=for-the-badge" alt="Hysteria">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">⚡ FreeLink</h1>

<p align="center">
  <b>Multi-server VPN management panel with subscription system</b><br>
  <a href="#-features">Features</a> • <a href="#-quick-start">Quick Start</a> • <a href="#-roadmap">Roadmap</a> • <a href="#-License">License</a>
</p>

> ⚠️ **ALPHA VERSION** — This project is in active development. APIs, features, and configuration may change without notice. Use in production at your own risk.

---

## 🌐 Languages

- [English](#-features)
- [Русский](#-русский)

---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| 🖥️ **Multi-server** | Main server + unlimited remote nodes |
| 🔗 **Subscriptions** | One URL for all servers (Hysteria, Clash, v2rayN, Happ) |
| 🤖 **Telegram Bot** | User management, notifications, VPN links |
| 📱 **Mini App** | Mobile panel for iOS/Android |
| 🌐 **Web Panel** | Admin dashboard with real-time metrics |
| ⚡ **Auto-deploy** | One-click server setup via SSH |
| 📊 **Traffic** | Per-user traffic tracking across all nodes |
| 🟢 **Online** | Real-time user connection status |
| 📋 **Plans** | Flexible subscription system with auto-expiry |
| 🔒 **Security** | TLS certificates, obfuscation, session auth |

---

## 📦 Quick Start

### Requirements

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- Domain with DNS pointing to server
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
# Clone the project
git clone https://github.com/R3G1ST/FreeLink.git /opt/vpnbot
cd /opt/vpnbot

# Run installer
chmod +x install.sh
sudo ./install.sh
```

The installer will ask for:
- 🌐 Domain name
- 📍 Server IP
- 🤖 Telegram Bot Token
- 👤 Telegram Admin ID

### After Installation

1. Open `https://your-domain.com`
2. Login: `admin`
3. Password: `admin123`
4. **Change password immediately!**

---

## 🔄 Update

```bash
cd /opt/vpnbot
sudo ./update.sh
```

---

## 🌍 Русский

### 🚀 Возможности

| Возможность | Описание |
|-------------|----------|
| 🖥️ **Мульти-сервер** | Основной сервер + неограниченные ноды |
| 🔗 **Подписки** | Одна ссылка на все серверы (Hysteria, Clash, v2rayN, Happ) |
| 🤖 **Telegram Бот** | Управление пользователями, уведомления, VPN-ссылки |
| 📱 **Мини-апп** | Мобильная панель для iOS/Android |
| 🌐 **Веб-панель** | Панель администратора с метриками в реальном времени |
| ⚡ **Авто-деплой** | Настройка сервера в один клик через SSH |
| 📊 **Трафик** | Учёт трафика по пользователям на всех серверах |
| 🟢 **Онлайн** | Статус подключения в реальном времени |
| 📋 **Планы** | Гибкая система подписок с авто-истечением |
| 🔒 **Безопасность** | TLS-сертификаты, обфускация, сессионная авторизация |

### 📦 Быстрый старт

#### Требования

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- Домен с DNS-записью на сервер
- Telegram Bot Token (от [@BotFather](https://t.me/BotFather))

#### Установка

```bash
# Клонируем проект
git clone https://github.com/R3G1ST/FreeLink.git /opt/vpnbot
cd /opt/vpnbot

# Запускаем установщик
chmod +x install.sh
sudo ./install.sh
```

Установщик запросит:
- 🌐 Имя домена
- 📍 IP сервера
- 🤖 Telegram Bot Token
- 👤 Telegram Admin ID

#### После установки

1. Открой `https://ваш-домен.com`
2. Логин: `admin`
3. Пароль: `admin123`
4. **Смените пароль сразу!**

### 🔄 Обновление

```bash
cd /opt/vpnbot
sudo ./update.sh
```

---

## 📁 Project Structure

```
vpnbot/
├── api.py              # FastAPI backend
├── auth.py             # Hysteria auth server
├── bot.py              # Telegram bot
├── node_agent.py       # Remote node agent
├── online_detector.py  # Online status detection
├── save_traffic.py     # Traffic recorder
├── install.sh          # Installation script
├── update.sh           # Update script
├── requirements.txt    # Python dependencies
├── config.example.yaml # Config template
└── web/                # Frontend files
    ├── index.html      # Admin panel
    ├── miniapp.html    # Telegram Mini App
    ├── client.html     # Client portal
    └── ...
```

---

## 🛠️ Services

After installation, these services run automatically:

| Service | Description |
|---------|-------------|
| `vpnbot-api` | Main API server (port 8000) |
| `vpnbot-auth` | Hysteria auth (port 8001) |
| `vpnbot-bot` | Telegram bot |
| `vpnbot-online` | Online detection |
| `vpnbot-traffic` | Traffic recording |

Manage services:
```bash
systemctl status vpnbot-api
systemctl restart vpnbot-api
journalctl -u vpnbot-api -f
```

---

## 🗺️ Roadmap / Дорожная карта

> ⚠️ **АЛЬФА-ВЕРСИЯ** — Проект в активной разработке. API, функции и конфигурация могут изменяться без уведомления. Используйте в продакшене на свой страх и риск.

### Приоритетные задачи
- [ ] Завершить перевод EN/RU (остатки контента в модалках)
- [ ] Исправить проблемы подключения к нодам (обработка UDP файрволов)
- [ ] Добавить ограничение скорости для пользователей
- [ ] Реализовать графики истории трафика с выбором периода

### Средний приоритет
- [ ] Добавить 2FA аутентификацию для админ-панели
- [ ] Реализовать управление сессиями пользователей
- [ ] Добавить webhook уведомления (Discord, Slack)
- [ ] Создать документацию API (Swagger/OpenAPI)
- [ ] Добавить поддержку БД (PostgreSQL/MySQL) как альтернативу JSON
- [ ] Реализовать группы пользователей и массовые операции

### Низкий приоритет
- [ ] Добавить больше языков (китайский, испанский, португальский)
- [ ] Создать мобильное приложение (React Native / Flutter)
- [ ] Реализовать дашборд мониторинга пропускной способности
- [ ] Добавить гео-локацию для выбора сервера
- [ ] Создать функционал бэкапа/восстановления
- [ ] Добавить оповещения о ресурсах системы (пороги CPU/RAM/Disk)

### UI/UX
- [ ] Улучшить адаптивный дизайн для мобильных устройств
- [ ] Оптимизировать темы Dark/Light
- [ ] Добавить loading skeleton для лучшего UX
- [ ] Реализовать горячие клавиши
- [ ] Добавить экспорт отчётов в PDF/CSV
- [ ] Создать мастер первичной настройки для новых установок

---

## 📝 License

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
- [ ] Add database support (PostgreSQL/MySQL) as alternative to JSON
- [ ] Implement user groups and bulk operations

### Low Priority
- [ ] Add more languages (Chinese, Spanish, Portuguese)
- [ ] Create mobile app (React Native / Flutter)
- [ ] Implement bandwidth monitoring dashboard
- [ ] Add geo-location based server selection
- [ ] Create backup/restore functionality
- [ ] Add system resource alerts (CPU/RAM/Disk thresholds)

### UI/UX
- [ ] Responsive design improvements for mobile
- [ ] Dark/Light theme optimization
- [ ] Add loading skeletons for better UX
- [ ] Implement keyboard shortcuts
- [ ] Add export to PDF/CSV reports
- [ ] Create onboarding wizard for new installations

---

## 📝 License

[MIT License](LICENSE)

---

<p align="center">
  Made with ❤️ for the VPN community
</p>
