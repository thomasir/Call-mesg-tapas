# ⚡ TAPAS CONTROL PANEL

> Telegram SMS · Call · WhatsApp OTP Bomber Bot

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/thomasir/Call-mesg-tapas)

---

## 🚀 Deploy to Heroku

1. Click the **Deploy to Heroku** button above
2. Fill in the required environment variables:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | Your Telegram numeric User ID (get from [@userinfobot](https://t.me/userinfobot)) |
| `LOG_CHANNEL_ID` | Telegram channel ID for logs (e.g. `-1001234567890`) |
| `CHANNEL_USERNAME` | Force-join channel username without `@` (leave blank to disable) |
| `CHANNEL_LINK` | Force-join channel invite link (leave blank to disable) |

3. Click **Deploy App**
4. After deploy → go to **Resources** tab → enable the `worker` dyno

---

## ⚙️ Stack

- **Runtime**: Python 3.12.6
- **Stack**: heroku-26
- **Dyno**: Standard-2X
- **Database**: PostgreSQL (auto-provisioned)
- **Bot mode**: Long polling (worker dyno)

---

## 📦 Features

- 📱 SMS bombing via real OTP APIs
- 💬 WhatsApp OTP bombing
- 📞 Voice call OTP bombing
- 🔄 Auto-retry with circuit breaker
- 🌐 UA rotation (15 agents)
- ⚡ Zero-delay async pipeline
- 🗃️ PostgreSQL persistent storage (Heroku) / SQLite (local)
- 👑 Owner panel with premium plans
- 🔑 Redeem code system
