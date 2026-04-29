# Swiggy Bot 🛵

A conversational commerce bot that lets users order food and groceries from Swiggy, and configure intelligent auto-restock schedules — entirely within Telegram or WhatsApp, no app switching required.

**Phase 1:** Telegram (live) · **Phase 2:** WhatsApp (pending WABA approval)

---

## Features

### Phase 1 — Telegram MVP
- **Food Ordering** — Search restaurants, browse menus, build a cart, and pay via Razorpay link — all in chat
- **Grocery Ordering** — Search Swiggy Instamart products with unit and quantity selection
- **Auto-Restock Schedules** — Set up recurring grocery orders with flexible frequency (daily / weekly / monthly / every Monday / 1st of every month)
- **Multiple Schedules** — Up to 10 named schedules per user, each on its own cadence
- **Pre-Order Reminders** — Configurable reminder N hours before each scheduled order with OK / Edit / Skip / Pause options
- **Schedule Controls** — Skip, Pause, Resume, Cancel, or Delay any schedule at any time
- **Order History** — View last 5 orders with live status
- **Razorpay Payments** — UPI, cards, net banking, and wallets via inline payment links

### Phase 2 — WhatsApp + Enrichment
- WhatsApp channel via Meta Cloud API (WABA approval in progress)
- Reorder Shortcuts — one-tap repeat from order history
- Dineout Table Reservations
- Price Drop Alerts — threshold-based Instamart price monitoring
- Spend & Budget Tracker — weekly summaries, monthly budget with 80% warning
- WhatsApp Pay (UPI native)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Framework | FastAPI (Python 3.12) |
| Telegram | python-telegram-bot v21 |
| WhatsApp (Phase 2) | Meta Cloud API via httpx |
| Task Queue | Celery + Redis |
| Database | PostgreSQL + SQLAlchemy (async) |
| Migrations | Alembic |
| Session Cache | Redis (30-min TTL) |
| Payments | Razorpay (Phase 1) + WhatsApp Pay (Phase 2) |
| Swiggy APIs | Builders Club MCP (Food, Instamart, Dineout) |
| Infrastructure | AWS EC2 + RDS |

---

## Architecture

```
User (Telegram / WhatsApp)
        │
        ▼
  Webhook Handler (FastAPI)
        │
        ▼
  ConversationManager  ◄──  Redis Session (30-min TTL)
  (State Machine)
        │
   ┌────┴────────────────┐
   ▼                     ▼
MessagingAdapter     Swiggy MCP Services
(Telegram / WhatsApp)   Food · Instamart · Dineout
        │
        ▼
  PostgreSQL (orders, schedules, users, price_alerts)
        │
        ▼
  Celery Beat ──► Workers
                  ├─ Reminders       (every 15 min)
                  ├─ Auto-orders     (every 5 min)
                  ├─ Price alerts    (every 6 hours)
                  └─ Weekly summary  (Monday 9am IST)
```

The `MessagingAdapter` is a platform-agnostic interface — `TelegramAdapter` and `WhatsAppAdapter` both implement the same contract. Switching channels is a single config flag change, not a rewrite.

---

## Project Structure

```
swiggy-bot/
├── src/
│   ├── adapters/          # MessagingAdapter base + Telegram + WhatsApp
│   ├── api/               # FastAPI app, Telegram/WhatsApp/Razorpay webhooks
│   ├── bot/
│   │   ├── conversation.py      # State machine & dispatcher
│   │   └── handlers/            # onboarding, food_order, grocery_order, schedules, payment
│   ├── models/            # SQLAlchemy models — User, Schedule, Order, PriceAlert
│   ├── services/          # Swiggy MCP clients, Razorpay, Redis session
│   └── tasks/             # Celery — reminders, auto_order, price_alerts
├── alembic/               # Database migrations
├── config/
│   └── settings.py        # Pydantic settings via .env
├── tests/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Getting Started

### Prerequisites
- Docker & Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/botfather)
- Swiggy Builders Club MCP credentials
- Razorpay account (test keys work for development)

### 1. Clone & configure

```bash
git clone https://github.com/zucc12309/Swiggy-bot.git
cd Swiggy-bot
cp .env.example .env
```

Edit `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=your_token_here
SWIGGY_MCP_TOKEN=your_mcp_token
RAZORPAY_KEY_ID=your_key
RAZORPAY_KEY_SECRET=your_secret
```

### 2. Start all services

```bash
docker-compose up --build
```

This starts:
- **api** — FastAPI on port 8000
- **worker** — Celery worker (4 concurrent)
- **beat** — Celery beat scheduler
- **db** — PostgreSQL on port 5432
- **redis** — Redis on port 6379

### 3. Run migrations

```bash
docker-compose exec api alembic upgrade head
```

### 4. Register the Telegram webhook

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://your-domain.com/webhook/telegram"
```

For local development, use [ngrok](https://ngrok.com):

```bash
ngrok http 8000
# then set webhook to your ngrok URL
```

### 5. Health check

```bash
curl http://localhost:8000/health
# {"status": "ok", "platform": "telegram"}
```

---

## Bot Commands

| Command | Action |
|---------|--------|
| `/start` | Onboarding or return to main menu |
| `/menu` | Show main menu |
| `/orders` | View last 5 orders |
| `/schedules` | List and manage auto-restock schedules |
| `/settings` | Update address, reminders, payment method |
| `/help` | Command reference |
| `/cancel` | Exit current flow |

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `SWIGGY_MCP_TOKEN` | Swiggy Builders Club API token |
| `RAZORPAY_KEY_ID` | Razorpay key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay secret |
| `MESSAGING_PLATFORM` | `telegram` or `whatsapp` |

---

## Swiggy Builders Club

This project integrates with the [Swiggy Builders Club MCP APIs](https://mcp.swiggy.com/builders):

- **Food MCP** — Restaurant search, menu, order placement, order status
- **Instamart MCP** — Product search, stock check, grocery order placement
- **Dineout MCP** — Restaurant search, table reservation (Phase 2)

All API calls are authenticated via Bearer token and routed through a static AWS Elastic IP for whitelist compliance.

---

## Roadmap

| Phase | Status |
|-------|--------|
| Phase 1 — Telegram MVP (Food, Grocery, Auto-Restock, Payments) | ✅ Built |
| Phase 2 — WhatsApp + Reorder Shortcuts + Dineout + Price Alerts + Budget Tracker | 🔄 In Progress |
| Phase 3 — AI suggestions, Smart substitutions, Hindi support | 📋 Planned |
| Phase 4 — Family cart, Group ordering, Swiggy One integration | 📋 Planned |

---

## License

Private — Swiggy Builders Club integration. Not for public redistribution.
