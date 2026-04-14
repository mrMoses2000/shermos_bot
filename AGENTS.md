# AGENTS.md — Shermos 3D Partition Visualizer v2.0

> Target model: GPT-5.4 xhigh (Codex). Reasoning effort: xhigh.

---

## ⚡ CURRENT STATUS (2026-04-14 — READ FIRST)

Phases 0-3 COMPLETE. Backend deployed, all services running.
79 tests, 91.77% coverage. Backend is DONE — **do NOT touch backend files**.

### What REMAINS — your task now:

**PHASE 4: Complete Mini App UI Redesign**

The current Mini App looks like a prototype. It needs a premium redesign inspired by Apple, Figma, and Raycast design systems. The app is a manager CMS (dashboard, orders, clients, measurements) opened inside Telegram WebView.

---

## PHASE 4 INSTRUCTIONS (READ EVERY LINE)

### Context

- Project dir: `/Users/mosesvasilenko/shermos-bot/`
- Mini App dir: `mini-app/` (React + Vite + TypeScript)
- All source files are in `mini-app/src/`
- CSS is in `mini-app/src/styles/index.css` (single file, no framework)
- Build: `cd mini-app && npm run build` — must succeed with zero errors
- The app runs inside Telegram WebView (320-430px wide, dark and light mode)
- API base URL comes from `VITE_API_BASE` env var (empty string = same origin)
- Auth: `X-Telegram-Init-Data` header from Telegram WebApp SDK

### Design System Requirements

Apply these design tokens globally. Replace ALL existing styles:

**Colors (light mode, CSS custom properties):**
```
--color-bg:            #ffffff
--color-bg-secondary:  #f8f9fa
--color-bg-tertiary:   #f1f3f5
--color-text-primary:  #111111
--color-text-secondary:#6b7280
--color-text-tertiary: #9ca3af
--color-border:        #e5e7eb
--color-border-light:  #f3f4f6
--color-accent:        #111111
--color-accent-hover:  #374151
--color-success:       #059669
--color-success-bg:    #ecfdf5
--color-warning:       #d97706
--color-warning-bg:    #fffbeb
--color-error:         #dc2626
--color-error-bg:      #fef2f2
--color-info:          #2563eb
--color-info-bg:       #eff6ff
```

**Colors (dark mode, via `@media (prefers-color-scheme: dark)` or Telegram theme):**
```
--color-bg:            #111111
--color-bg-secondary:  #1a1a1a
--color-bg-tertiary:   #222222
--color-text-primary:  #f9fafb
--color-text-secondary:#9ca3af
--color-text-tertiary: #6b7280
--color-border:        #2d2d2d
--color-border-light:  #1f1f1f
--color-accent:        #ffffff
--color-accent-hover:  #e5e7eb
```

**Typography:**
```
--font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", "Segoe UI", system-ui, sans-serif;
--font-mono: "SF Mono", "Fira Code", "Consolas", monospace;

/* Scale */
--text-xs:    12px; line-height: 1.4;
--text-sm:    13px; line-height: 1.45;
--text-base:  15px; line-height: 1.5;
--text-lg:    17px; line-height: 1.4;
--text-xl:    20px; line-height: 1.3;
--text-2xl:   24px; line-height: 1.2;
--text-3xl:   30px; line-height: 1.1;

/* Weights */
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

**Spacing (8px base grid):**
```
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
```

**Border radius:**
```
--radius-sm:  6px;
--radius-md:  10px;
--radius-lg:  14px;
--radius-xl:  20px;
--radius-full: 9999px;
```

**Shadows:**
```
--shadow-sm:  0 1px 2px rgba(0,0,0,0.04);
--shadow-md:  0 2px 8px rgba(0,0,0,0.06);
--shadow-lg:  0 4px 16px rgba(0,0,0,0.08);
```

**Transitions:**
```
--transition-fast: 120ms ease;
--transition-base: 200ms ease;
```

### Component Specifications

**1. Layout (Layout.tsx + CSS)**

Header area:
- Compact: `padding: 16px 20px 0`
- "SHERMOS" label: `text-xs`, `font-semibold`, `text-secondary`, `letter-spacing: 0.08em`, `text-transform: uppercase`
- "CMS" title: `text-2xl`, `font-bold`, `text-primary`, `margin-top: 2px`

Tab navigation:
- Horizontal scroll, `gap: 6px`, `padding: 12px 20px`
- Each tab: `padding: 8px 16px`, `border-radius: var(--radius-full)`, `text-sm`, `font-medium`
- Inactive: `bg: transparent`, `color: var(--color-text-secondary)`, no border
- Active: `bg: var(--color-accent)`, `color: #fff` (light mode) or `color: #111` (dark mode)
- Hover (inactive): `bg: var(--color-bg-tertiary)`
- Transition: `background var(--transition-fast), color var(--transition-fast)`
- Hide scrollbar: `-webkit-overflow-scrolling: touch; scrollbar-width: none;`
- Add "Цены" and "Настройки" tabs back (6 total)

Content area:
- `padding: 0 20px 32px`

**2. Dashboard page (Dashboard.tsx)**

Metric cards (3-column grid → 1 column on mobile):
- Each card: `bg: var(--color-bg)`, `border: 1px solid var(--color-border)`, `border-radius: var(--radius-md)`, `padding: 16px`
- `shadow: var(--shadow-sm)` on hover
- Label: `text-xs`, `text-secondary`, `text-transform: uppercase`, `letter-spacing: 0.04em`
- Value: `text-2xl`, `font-bold`, `text-primary`, `margin-top: 4px`
- Subtotal/change: `text-xs`, `text-secondary`

Chart (AnalyticsChart):
- Same card style wrapper
- Bars: height `6px`, `border-radius: var(--radius-full)`, `bg: var(--color-accent)`
- Bar background track: `bg: var(--color-bg-tertiary)`
- Bar label: `text-sm`, `text-secondary`, fixed width `80px`
- Bar value: `text-sm`, `font-medium`, `text-primary`

**3. Orders page (Orders.tsx + OrderTable.tsx)**

Table:
- Card wrapper: `border: 1px solid var(--color-border)`, `border-radius: var(--radius-md)`, `overflow: hidden`
- Header row: `bg: var(--color-bg-secondary)`, `text-xs`, `text-secondary`, `text-transform: uppercase`, `letter-spacing: 0.04em`, `padding: 10px 16px`
- Data rows: `padding: 12px 16px`, `border-top: 1px solid var(--color-border-light)`
- Hover row: `bg: var(--color-bg-secondary)` with `transition: var(--transition-fast)`
- Order ID: `font-mono`, `text-sm`, show first 8 chars
- Status badge: pill shape (`border-radius: var(--radius-full)`, `padding: 3px 10px`, `text-xs`, `font-medium`)
  - scheduled: `bg: var(--color-info-bg)`, `color: var(--color-info)`
  - confirmed/completed: `bg: var(--color-success-bg)`, `color: var(--color-success)`
  - cancelled/rejected: `bg: var(--color-error-bg)`, `color: var(--color-error)`
  - in_progress: `bg: var(--color-warning-bg)`, `color: var(--color-warning)`

Empty state:
- Center of page, `padding: 48px 20px`
- Icon: use emoji or SVG (e.g. 📋), `font-size: 32px`, `margin-bottom: 12px`
- Text: `text-sm`, `text-secondary`, `text-align: center`
- NO dashed border

**4. Clients page (Clients.tsx + ClientCard.tsx)**

Card grid: `display: grid`, `grid-template-columns: 1fr`, `gap: 8px`
Each card:
- `border: 1px solid var(--color-border)`, `border-radius: var(--radius-md)`, `padding: 14px 16px`
- `bg: var(--color-bg)`, hover: `bg: var(--color-bg-secondary)`, `transition: var(--transition-fast)`
- Name: `text-base`, `font-medium`, `text-primary`
- Phone/address: `text-sm`, `text-secondary`, `margin-top: 2px`
- If no phone: `text-tertiary`, italic

**5. Measurements page (Measurements.tsx + MeasurementCalendar.tsx)**

List of measurement items (similar to Clients cards):
- Each item: card with `border`, `border-radius: var(--radius-md)`, `padding: 14px 16px`
- Top row: date/time `text-base font-medium` + status badge (pill, right-aligned)
- Bottom row: address `text-sm text-secondary`
- Group measurements by date with date separator: `text-xs`, `text-secondary`, `text-transform: uppercase`, `padding: 8px 0 4px`, `letter-spacing: 0.04em`

**6. PricingEditor page (PricingEditor.tsx + PriceTable.tsx)**

Same table style as Orders. Columns: Name, Category, Price.
- Price column: `font-mono`, right-aligned
- Editable prices: in future (for now read-only is fine)

**7. Settings page (Settings.tsx)**

Simple key-value list:
- Each row: `padding: 14px 0`, `border-bottom: 1px solid var(--color-border-light)`
- Label: `text-xs`, `text-secondary`, `text-transform: uppercase`, `letter-spacing: 0.04em`
- Value: `text-sm`, `text-primary`, `margin-top: 4px`, `word-break: break-all`
- Last row: no border-bottom

**8. Spinner (Spinner.tsx)**

- Center of content area vertically and horizontally
- Size: `24px × 24px`
- Border: `2px solid var(--color-border)`
- Border-top: `2px solid var(--color-accent)`
- Animation: `spin 0.7s linear infinite`

**9. Global styles**

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-family: var(--font-family); font-size: var(--text-base); color: var(--color-text-primary); background: var(--color-bg); -webkit-font-smoothing: antialiased; }
body { min-height: 100vh; min-height: 100dvh; }
```

Telegram theme detection: check `window.Telegram?.WebApp?.colorScheme` for "dark"/"light" and set `data-theme` attribute on `<html>`.

### RULES FOR CODEX

1. **ONLY modify files inside `mini-app/src/`** — do NOT touch any Python files, run.sh, .env, or anything outside mini-app/.
2. **Replace `mini-app/src/styles/index.css` entirely** with new design system CSS using the tokens above.
3. **Update all .tsx component files** to use the new class names and structure.
4. **Keep all existing API calls and data types unchanged** — only change visual presentation.
5. **Do NOT add any new npm dependencies** — use only CSS (no Tailwind, no Chakra, no MUI).
6. **Do NOT change `mini-app/src/api/client.ts`** or `mini-app/src/hooks/useTelegram.ts`.
7. **All interactive elements must have smooth transitions** (`var(--transition-fast)` or `var(--transition-base)`).
8. **Support dark mode** via CSS custom properties + Telegram WebApp colorScheme detection.
9. **Build MUST pass**: `cd mini-app && npm run build` → zero errors, zero warnings.
10. **Test in mobile viewport**: design for 375px width primary, 430px max.
11. **DO NOT use emojis in CSS or TSX** unless specifically for empty state icons.

### File Checklist

After you finish, these files should be modified:
- [ ] `mini-app/src/styles/index.css` — complete rewrite
- [ ] `mini-app/src/App.tsx` — dark mode detection via Telegram theme
- [ ] `mini-app/src/components/Layout.tsx` — new header + tabs structure
- [ ] `mini-app/src/components/OrderTable.tsx` — new table styles
- [ ] `mini-app/src/components/OrderStatusBadge.tsx` — pill badge with status colors
- [ ] `mini-app/src/components/ClientCard.tsx` — new card layout
- [ ] `mini-app/src/components/MeasurementCalendar.tsx` — grouped list + status badges
- [ ] `mini-app/src/components/AnalyticsChart.tsx` — new bar chart style
- [ ] `mini-app/src/components/PriceTable.tsx` — consistent table style
- [ ] `mini-app/src/components/Spinner.tsx` — minimal spinner
- [ ] `mini-app/src/pages/Dashboard.tsx` — metric cards grid
- [ ] `mini-app/src/pages/Orders.tsx` — page structure
- [ ] `mini-app/src/pages/Clients.tsx` — card grid
- [ ] `mini-app/src/pages/Measurements.tsx` — grouped list
- [ ] `mini-app/src/pages/PricingEditor.tsx` — page structure
- [ ] `mini-app/src/pages/Settings.tsx` — key-value list

### Verification

Run `cd mini-app && npm run build`. Output must contain:
```
✓ built in ...ms
```
With zero errors. If TypeScript errors occur — fix them. If CSS has syntax errors — fix them.

---

### What's DONE (do not touch):

**Backend (ALL COMPLETE — DO NOT MODIFY):**
- src/bot/, src/llm/, src/queue/, src/engine/, src/render/, src/db/, src/api/, src/utils/
- src/config.py, src/models.py
- run_webhook.py, run_worker.py, run_api.py, run.sh
- migrations/ (001-010)
- GEMINI.md, .gemini/settings.json, DEPLOY.md
- 79 tests, 91.77% coverage
- All services deployed and running on server

**DO NOT touch or modify:**
- Any .py file
- run.sh, .env, .env.example
- GEMINI.md, .gemini/settings.json
- migrations/
- requirements.txt, pyproject.toml
- docker-compose.yml

---

## Original Specification (for reference)

## Task

Build a complete Telegram bot system for 3D glass partition visualization and quoting.
The system replaces an existing n8n-based orchestration with a custom Python solution.
Bias to action: implement with reasonable defaults. Do not stop to ask questions.

## Environment

You are running on **macOS** (the developer machine).
The production server is reachable via: `ssh aws-shermos1-frankfurt`
Server user: `ubuntu`. Use `sudo` for Docker and systemd commands.

**Server specs:**
- IP: 3.79.24.73 (AWS Frankfurt, eu-central-1)
- OS: Ubuntu 24.04, Python 3.12.3, Node.js 20+
- Gemini CLI: v0.36.0 installed at /usr/local/bin/gemini
- Docker: installed, `sudo` required
- Disk: 29GB total, ~10GB free (will gain ~12GB after cleanup)

**Other services running on the server (DO NOT TOUCH):**
- `music_school_app` Docker container on ports 80, 443 (Rudolf music site)
- `musikschule-tg-bot` systemd service on port 8443 (music school Telegram bot)
- `buzz-container` Docker on port 3000
- SSL cert: /etc/letsencrypt/live/musikschule-cms-bielefeld.de/

**Ports for Shermos bot:**
- Webhook server (aiohttp with SSL): port **88** (HTTPS, public — Telegram supports 443, 80, 88, 8443)
- PostgreSQL (Docker): port **5432** (local only)
- Redis (Docker): port **6379** (local only)

**Webhook strategy: Self-signed SSL certificate on IP address.**
No domain, no ngrok, no Cloudflare, no Caddy. The aiohttp server serves HTTPS
directly on port 88 using a self-signed certificate. Telegram supports this
natively when the public cert is uploaded via setWebhook API.
Server IP: 3.79.24.73 (AWS Elastic IP — does not change).
Cert valid for 10 years. Zero external dependencies.

**Development workflow:**
- ALL code is written locally on macOS in the project directory
- Git repository is initialized locally
- Code is pushed to the server via `git push production main`
- Server setup, dependency installation, and tests run via SSH

**DO NOT** write code directly on the server. Always write locally, commit, push.

## Architecture: NO SUPABASE

This project does NOT use Supabase. All data lives in a local PostgreSQL database
running in Docker on the server. Images are stored on local filesystem and sent
to Telegram as file uploads (InputFile), not URLs.

**Data storage:**
- PostgreSQL (Docker): ALL tables — orders, clients, measurements, prices, materials,
  conversation state, chat messages, processed updates, inbound/outbound events
- Local filesystem: `/data/renders/` — rendered PNG images
- Redis (Docker): queue, locks, cache

**Photo delivery to Telegram:**
- Render engine saves 4 PNG files to `/data/renders/{request_id}/`
- Worker reads local files and sends via `sendPhoto` with `multipart/form-data` upload
- After successful send, local files can be kept (for Mini App viewing) or pruned after N days

**NO Supabase SDK. NO cloud storage. NO external database.**

## Completion Criteria

The task is NOT complete until ALL of these are true:
1. Every file listed below exists with working code
2. `pytest --cov=src --cov-report=term-missing` passes with **zero failures** and **>85% coverage**
3. The Mini App frontend builds with `cd mini-app && npm run build`
4. The old n8n project is wiped from the server
5. The new project is deployed and running on the server
6. Both bots respond to `/health` or `/start`
7. Docker Compose (on server) brings up Redis + Postgres + app successfully

---

## Project Structure

```
shermos-bot/
├── run_webhook.py
├── run_worker.py
├── requirements.txt
├── pyproject.toml
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── .env.example
├── AGENTS.md
│
├── config/
│   └── app_config.json                    # COPY FROM EXISTING (materials, prices, constraints)
│
├── migrations/
│   ├── 001_processed_updates.sql
│   ├── 002_inbound_events.sql
│   ├── 003_outbound_events.sql
│   ├── 004_conversation_state.sql
│   ├── 005_chat_messages.sql
│   ├── 006_orders.sql
│   ├── 007_clients.sql
│   └── 008_measurements.sql
│
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   │
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── webhook.py
│   │   ├── telegram_sender.py
│   │   └── keyboards.py
│   │
│   ├── queue/
│   │   ├── __init__.py
│   │   ├── worker.py
│   │   └── outbox_dispatcher.py
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── executor.py
│   │   ├── prompt_builder.py
│   │   ├── actions_parser.py
│   │   ├── actions_applier.py
│   │   └── tools_schema.py
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── fsm.py
│   │   ├── render_engine.py
│   │   ├── pricing_engine.py
│   │   └── calendar_engine.py
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py                    # asyncpg pool — ALL data lives here
│   │   └── redis_client.py
│   │
│   ├── render/
│   │   ├── __init__.py
│   │   ├── create_partition.py            # COPY FROM EXISTING — DO NOT REWRITE
│   │   ├── validators.py                  # COPY FROM EXISTING — DO NOT REWRITE
│   │   └── config_manager.py             # COPY FROM EXISTING — DO NOT REWRITE
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                         # FastAPI sub-application for Mini App REST API
│   │   ├── auth.py                        # Telegram initData HMAC validation
│   │   ├── routes_orders.py
│   │   ├── routes_clients.py
│   │   ├── routes_measurements.py
│   │   ├── routes_pricing.py
│   │   ├── routes_analytics.py
│   │   └── routes_settings.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── query_parser.py
│
├── mini-app/                              # Telegram Mini App frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts                  # fetch wrapper with initData auth
│       ├── hooks/
│       │   └── useTelegram.ts
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── Orders.tsx
│       │   ├── OrderDetail.tsx
│       │   ├── Clients.tsx
│       │   ├── ClientDetail.tsx
│       │   ├── Measurements.tsx
│       │   ├── PricingEditor.tsx
│       │   └── Settings.tsx
│       ├── components/
│       │   ├── Layout.tsx
│       │   ├── OrderTable.tsx
│       │   ├── OrderStatusBadge.tsx
│       │   ├── ClientCard.tsx
│       │   ├── MeasurementCalendar.tsx
│       │   ├── PriceTable.tsx
│       │   ├── AnalyticsChart.tsx
│       │   └── Spinner.tsx
│       └── styles/
│           └── index.css
│
└── tests/
    ├── conftest.py
    ├── test_webhook.py
    ├── test_worker.py
    ├── test_render.py
    ├── test_llm_actions.py
    ├── test_fsm.py
    ├── test_pricing.py
    ├── test_api_auth.py
    └── test_api_orders.py
```

---

## FILE CONTRACTS

### 1. `src/config.py`

```python
"""
Settings loaded from .env via pydantic-settings.
Pattern: exactly like /Users/mosesvasilenko/tg_keto/src/config.py
"""
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram Client Bot
    telegram_bot_token: str                        # required
    telegram_webhook_secret: str                   # required

    # Telegram Manager Bot
    manager_bot_token: str                         # required
    manager_webhook_secret: str                    # required
    manager_chat_ids: str = ""                     # CSV: "123,456,789"

    # Webhook (HTTPS on port 88, self-signed cert)
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 88
    webhook_public_url: str = "https://3.79.24.73:88"  # used for setWebhook
    webhook_path_client: str = "/webhook/client"
    webhook_path_manager: str = "/webhook/manager"
    ssl_cert_path: str = "certs/webhook.pem"       # self-signed public cert
    ssl_key_path: str = "certs/webhook.key"        # private key

    # Render storage
    renders_dir: str = "data/renders"              # local directory for rendered PNGs

    # Local Postgres (state DB)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "shermos_bot"
    postgres_user: str = "shermos"
    postgres_password: str = "change_me"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM (Gemini CLI)
    llm_cli_command: str = "gemini"
    llm_cli_flags: str = "-p"
    max_llm_concurrency: int = 2                   # 1-10
    llm_timeout_seconds: int = 90                  # 10-300

    # Google Calendar
    gcal_calendar_id: str = "primary"
    gcal_credentials_path: str = "credentials.json"
    timezone: str = "Asia/Bishkek"

    # Behaviour
    bot_language: str = "ru"
    send_typing_indicator: bool = True
    max_context_messages: int = 20
    render_cache_ttl_seconds: int = 3600

    # Mini App
    mini_app_url: str = ""                         # URL where Mini App is hosted

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"                       # 'json' | 'text'

    @property
    def webhook_url_client(self) -> str:
        return f"{self.webhook_public_url}{self.webhook_path_client}"

    @property
    def webhook_url_manager(self) -> str:
        return f"{self.webhook_public_url}{self.webhook_path_manager}"

    @property
    def manager_chat_ids_list(self) -> list[int]:
        if not self.manager_chat_ids:
            return []
        return [int(x.strip()) for x in self.manager_chat_ids.split(",") if x.strip()]

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}

settings = Settings()
```

### 2. `src/models.py`

```python
"""
All Pydantic models for the system.
Pattern: exactly like /Users/mosesvasilenko/tg_keto/src/models.py
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

# --- Queue Job ---
class Job(BaseModel):
    update_id: int
    chat_id: int
    user_id: int
    text: str = ""
    msg_type: str = "text"                    # text | voice | photo | callback_query | command
    callback_data: str = ""
    raw_update: dict = {}
    attempt: int = 0
    received_at: datetime = Field(default_factory=datetime.utcnow)
    bot_type: str = "client"                  # client | manager

# --- LLM Actions (Gemini response contract) ---
class RenderPartitionAction(BaseModel):
    shape: str                                # Прямая | Г-образная | П-образная
    height: float                             # meters
    width_a: float                            # meters
    width_b: Optional[float] = None           # for L/U shapes
    width_c: Optional[float] = None           # for U shapes
    glass_type: str = "1"                     # 1-4 (ID from config)
    frame_color: str = "1"                    # 1-5 (ID from config)
    rows: int = 1
    cols: int = 2
    frame_thickness: float = 0.04
    add_handle: bool = False
    handle_style: str = "Современный"         # Современный | Классический
    handle_position: str = "Право"            # Лево | Центр | Право
    door_section: Optional[int] = None
    mullion_positions: Optional[dict] = None  # per-wall custom positions

class ScheduleMeasurementAction(BaseModel):
    date: str                                 # YYYY-MM-DD
    time: str                                 # HH:MM
    client_name: str
    phone: str
    address: str = ""

class UpdateClientProfileAction(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class StatePatch(BaseModel):
    mode: Optional[str] = None                # idle | collecting | confirming | rendering
    step: Optional[str] = None
    collected_params: Optional[dict] = None

class ActionsJson(BaseModel):
    reply_text: str = Field(min_length=1, max_length=4000)
    actions: Optional[dict] = None
    # actions may contain:
    #   render_partition: RenderPartitionAction dict
    #   schedule_measurement: ScheduleMeasurementAction dict
    #   update_client_profile: UpdateClientProfileAction dict
    #   state_patch: StatePatch dict

# --- Manager Bot Actions ---
class OrderStatusUpdate(BaseModel):
    order_id: str
    new_status: str                           # new | confirmed | in_progress | completed | cancelled
    note: str = ""
```

### 3. `src/bot/webhook.py`

```python
"""
aiohttp webhook handler.
Pattern: exactly like /Users/mosesvasilenko/tg_keto/src/bot/webhook.py

CRITICAL REQUIREMENTS:
- Validate X-Telegram-Bot-Api-Secret-Token header
- Parse Telegram Update JSON
- Idempotency check via INSERT ON CONFLICT DO NOTHING on processed_updates
- Insert into inbound_events for audit
- LPUSH job to Redis queue:incoming (client) or queue:manager (manager)
- Return 200 OK in < 50ms (ALWAYS return 200, even on errors)
- Two routes: /webhook/client and /webhook/manager
"""
# Implementation: aiohttp.web handlers
# handle_client_webhook(request) -> web.Response
# handle_manager_webhook(request) -> web.Response
# Both call _process_webhook(request, bot_type, secret_token)
```

### 4. `src/bot/telegram_sender.py`

```python
"""
Raw aiohttp-based Telegram Bot API client. NO external SDK.
Pattern: like /Users/mosesvasilenko/Rudolf_music_site/services/telegram-bot/src/bot.ts
but in Python with aiohttp.ClientSession.

Methods:
- send_message(token, chat_id, text, parse_mode="HTML", reply_markup=None) -> dict
- send_photo(token, chat_id, photo_path: str, caption="") -> dict
    # Sends LOCAL FILE via multipart/form-data upload
    # Uses aiohttp.FormData with open(photo_path, 'rb')
- send_media_group(token, chat_id, photo_paths: list[str], caption="") -> dict
    # Sends multiple LOCAL FILES as media group
    # Each photo is uploaded as InputFile (multipart/form-data)
    # media JSON: [{"type":"photo","media":"attach://photo0"}, ...]
    # Files attached as photo0, photo1, photo2, photo3
- send_chat_action(token, chat_id, action="typing") -> dict
- edit_message(token, chat_id, message_id, text, parse_mode="HTML") -> dict
- set_webhook(token, url, secret_token, allowed_updates, certificate_path=None) -> dict
    # If certificate_path is provided, uploads the self-signed cert as multipart/form-data
    # This is REQUIRED for self-signed certificates (Telegram needs to know the cert)
- delete_webhook(token) -> dict
- set_chat_menu_button(token, chat_id, menu_button) -> dict
- answer_callback_query(token, callback_query_id, text="") -> dict

All methods use shared aiohttp.ClientSession (created at startup, closed at shutdown).
Base URL: https://api.telegram.org/bot{token}/{method}

IMPORTANT: Photos are sent as FILE UPLOADS, not URLs.
The render engine saves PNGs to local disk, and telegram_sender uploads them directly.
"""
```

### 5. `src/bot/keyboards.py`

```python
"""
Inline keyboard builders for Telegram.

Functions:
- confirm_render_keyboard() -> dict
    Buttons: [✅ Рендерить] [❌ Отмена]
    callback_data: "confirm_render" / "cancel_render"

- confirm_measurement_keyboard(date, time) -> dict
    Buttons: [✅ Подтвердить] [❌ Отмена]

- rate_render_keyboard(order_id) -> dict
    Buttons: [⭐1] [⭐2] [⭐3] [⭐4] [⭐5]

- manager_order_keyboard(order_id) -> dict
    Buttons: [✅ Confirmed] [🔧 In Progress] [✅ Completed] [❌ Cancel]

- open_mini_app_keyboard(url) -> dict
    Buttons: [📊 Открыть CMS] (web_app type)
"""
```

### 6. `src/queue/worker.py`

```python
"""
Main worker loop.
Pattern: exactly like /Users/mosesvasilenko/tg_keto/src/queue/worker.py

CRITICAL FLOW:
1. BRPOP from redis queue:incoming (timeout=5s)
2. Deserialize Job from JSON
3. Acquire per-user lock: Redis SET NX EX 180 on lock:user:{chat_id}
   - If locked: re-enqueue with attempt++, max 5, exponential backoff
4. Mark processed_updates status='processing'
5. Load context:
   - Client profile from Supabase clients table
   - Conversation state from Postgres conversation_state
   - Last 20 messages from Postgres chat_messages
6. Handle commands (/start, /help, /status, /examples, /clear)
   - Short-circuit: send response, skip LLM
7. Build LLM prompt (prompt_builder.py)
8. Call Gemini CLI (executor.py)
9. Parse response (actions_parser.py)
10. Execute actions (actions_applier.py):
    - render_partition → render_engine.py → Supabase Storage
    - schedule_measurement → calendar_engine.py
    - update_client_profile → Supabase clients
    - state_patch → Postgres conversation_state
11. Send response to Telegram (text + photos if render)
12. Save chat messages (user + assistant) to Postgres
13. Insert outbound_event (outbox pattern)
14. Mark processed_updates status='completed'
15. Release per-user lock

ERROR HANDLING:
- LLM timeout → send fallback error message, mark failed
- Render crash → send error, mark failed
- Any exception → send "Произошла ошибка", mark failed, release lock

Also runs manager queue processing:
- Separate BRPOP on queue:manager
- Simpler flow: no LLM, just command processing
- Commands: view orders, update status, notify client
"""

# run_worker() — starts both client and manager workers + outbox dispatcher
# process_client_job(job: Job) — full pipeline above
# process_manager_job(job: Job) — simplified pipeline for manager
```

### 7. `src/queue/outbox_dispatcher.py`

```python
"""
Periodic retry loop for failed Telegram sends.
Pattern: like /Users/mosesvasilenko/tg_keto/src/engine/outbox_dispatcher.py

Every 15 seconds:
1. SELECT FROM outbound_events WHERE status='pending' AND attempts < 5 ORDER BY created_at LIMIT 20
2. For each: attempt re-send via telegram_sender
3. Success → UPDATE status='sent'
4. Failure → UPDATE attempts=attempts+1, last_attempt_at=now(), error_message=str(e)
5. After 5 attempts → UPDATE status='failed'

Run as asyncio.create_task inside run_worker.py.
"""
```

### 8. `src/llm/executor.py`

```python
"""
Gemini CLI subprocess executor.
Pattern: hybrid of tg_keto (semaphore) + Rudolf_music_site (cascading kill)

CRITICAL:
- asyncio.Semaphore(settings.max_llm_concurrency) — default K=2
- asyncio.create_subprocess_exec("gemini", "-p", prompt_text)
- cwd=project root (or configurable)
- Timeout: settings.llm_timeout_seconds (default 90s)
- On timeout: SIGTERM → wait 5s → SIGKILL
- Strip ANSI codes from output
- Filter noise lines (gemini CLI metadata)
- Return cleaned stdout as str
- Raise TimeoutError or RuntimeError on failure
- Log: t_wait_llm (time waiting for semaphore), t_exec_llm (subprocess time)

async def call_llm(prompt: str) -> str:
    ...
"""
```

### 9. `src/llm/tools_schema.py`

```python
"""
Tool definitions for Gemini function calling.
These are included in the system prompt so Gemini knows what tools are available.

TOOLS:
1. render_partition
   - Parameters: shape, height, width_a, width_b?, width_c?, glass_type,
     frame_color, rows, cols, frame_thickness, add_handle, handle_style,
     handle_position, door_section?, mullion_positions?
   - Description: Generate 3D renders of glass partition from 4 angles

2. schedule_measurement
   - Parameters: date, time, client_name, phone, address?
   - Description: Schedule on-site measurement appointment

3. update_client_profile
   - Parameters: name?, phone?, address?
   - Description: Update client contact information

Return format for tools as plain text schema for system prompt inclusion.
"""
```

### 10. `src/llm/prompt_builder.py`

```python
"""
Assembles the full prompt for Gemini.

Sections (in order):
1. SYSTEM PROMPT (Russian):
   - Role: Expert glass partition consultant for Shermos company
   - Language: Always reply in Russian
   - Available shapes: Прямая, Г-образная, П-образная
   - Available glass types: from config/app_config.json
   - Available frame colors: from config/app_config.json
   - Handle styles: Современный, Классический
   - Pricing overview
   - Instructions: collect ALL parameters before calling render_partition
   - Confirmation step: always summarize and ask "Рендерить?" before calling tool
   - Format: Telegram HTML (<b>, <i>, no markdown)
   - Max response: 500 words unless listing options

2. TOOLS SCHEMA (from tools_schema.py)

3. PROFILE CONTEXT:
   - Client: {name, phone, address} or "Новый клиент"

4. STATE CONTEXT:
   - FSM mode: idle | collecting | confirming | rendering
   - FSM step: ask_shape | ask_dimensions | ask_glass | ask_frame | etc.
   - Collected params so far: {shape: "Прямая", height: 2.5, ...}

5. CONVERSATION HISTORY:
   - Last N messages: "Клиент: ...\nАссистент: ...\n"

6. USER MESSAGE:
   - Current message text

Output contract for Gemini (included in system prompt):
```json
{
  "reply_text": "...",
  "actions": {
    "render_partition": { ... } | null,
    "schedule_measurement": { ... } | null,
    "update_client_profile": { ... } | null,
    "state_patch": { "mode": "...", "step": "...", "collected_params": {} } | null
  }
}
```
ALWAYS respond with valid JSON. No markdown fences. No explanations outside JSON.
"""
```

### 11. `src/llm/actions_parser.py`

```python
"""
Parse and validate Gemini output.
Pattern: like /Users/mosesvasilenko/tg_keto/src/llm/actions_parser.py

Steps:
1. Try json.loads(raw_output) directly
2. If fails: extract JSON from markdown fences (```json ... ```)
3. If fails: find first { ... } block using brace counting
4. Validate against ActionsJson Pydantic model
5. If render_partition in actions: validate against RenderPartitionAction
6. If schedule_measurement: validate against ScheduleMeasurementAction
7. On any error: return fallback ActionsJson(reply_text="Ошибка, попробуйте снова")

def parse_actions(raw_output: str) -> ActionsJson:
    ...
"""
```

### 12. `src/llm/actions_applier.py`

```python
"""
Execute validated actions from LLM response.

async def apply_actions(
    actions: ActionsJson,
    chat_id: int,
    client_profile: dict,
    conversation_state: dict,
    pg_pool,
    redis_client,
    settings
) -> dict:
    result = {"image_urls": None, "price": None, "calendar_event": None}

    if actions.actions:
        if "render_partition" in actions.actions:
            params = RenderPartitionAction(**actions.actions["render_partition"])
            # 1. Normalize params (query_parser.py aliases)
            # 2. Validate (validators.py)
            # 3. Generate request_id (uuid4)
            # 4. Run render (render_engine.py) — in thread pool to not block event loop
            #    → saves PNGs to /data/renders/{request_id}/
            # 5. Calculate price (pricing_engine.py)
            # 6. INSERT order into LOCAL PostgreSQL orders table
            # 7. Notify manager bot (send message to MANAGER_CHAT_IDS)
            result["render_paths"] = ...  # dict of local file paths
            result["price"] = ...

        if "schedule_measurement" in actions.actions:
            params = ScheduleMeasurementAction(**actions.actions["schedule_measurement"])
            # 1. Create Google Calendar event
            # 2. INSERT into LOCAL PostgreSQL measurements table
            result["calendar_event"] = ...

        if "update_client_profile" in actions.actions:
            params = UpdateClientProfileAction(**actions.actions["update_client_profile"])
            # UPDATE local PostgreSQL clients table

        if "state_patch" in actions.actions:
            patch = StatePatch(**actions.actions["state_patch"])
            # Validate FSM transition, upsert conversation_state

    return result
```

### 13. `src/engine/fsm.py`

```python
"""
Finite State Machine for parameter collection.

States:
- idle: no active flow
- collecting: gathering partition parameters
- confirming: showing summary, waiting for confirmation
- rendering: render in progress
- scheduling: collecting measurement details

Transitions:
- idle → collecting (user starts describing partition)
- collecting → collecting (still gathering params)
- collecting → confirming (all required params collected)
- confirming → rendering (user confirms)
- confirming → collecting (user wants changes)
- rendering → idle (render complete, sent)
- idle → scheduling (user wants measurement)
- scheduling → idle (measurement booked)

Functions:
- is_valid_transition(current_mode: str, next_mode: str) -> bool
- get_missing_params(collected_params: dict, shape: str) -> list[str]
- format_summary(collected_params: dict) -> str  # Human-readable summary in Russian
"""
```

### 14. `src/engine/render_engine.py`

```python
"""
Async wrapper around create_partition.py.

IMPORTANT: create_partition.py uses trimesh + pyrender which are synchronous
and CPU-bound. Run in asyncio thread pool executor.

async def render_partition(params: RenderPartitionAction, request_id: str, settings) -> dict:
    # 1. Convert RenderPartitionAction to the dict format expected by create_partition
    # 2. Create output directory: {settings.renders_dir}/{request_id}/
    # 3. Run generate_from_params() in thread pool:
    #    loop = asyncio.get_event_loop()
    #    result = await loop.run_in_executor(None, _sync_render, render_params, output_dir)
    # 4. Return {"render_paths": {"0deg": "/abs/path/0deg.png", "90deg": ..., "180deg": ..., "270deg": ...}}
    # NO cloud upload. Files stay on local disk. Worker sends them via Telegram file upload.

def _sync_render(params: dict) -> dict:
    # Calls render.create_partition.generate_from_params(params)
    # Returns dict with file paths
"""
```

### 15. `src/engine/pricing_engine.py`

```python
"""
Price calculation engine.
EXTRACT from existing server.py lines ~800-950 (the _calculate_price method).

def calculate_price(
    shape: str,
    height: float,
    width_a: float,
    width_b: float = 0,
    width_c: float = 0,
    glass_type: str = "1",
    frame_color: str = "1",
    rows: int = 1,
    cols: int = 2,
    add_handle: bool = False,
) -> dict:
    # 1. Calculate total area (m²) based on shape
    # 2. Base price = area * base_rate_per_sqm (from app_config.json prices)
    # 3. Glass modifier (premium glass = +15%)
    # 4. Frame color modifier (non-standard = +4%)
    # 5. Volume discount (>8 m² = -6%)
    # 6. Handle add-on (if applicable)
    # 7. Return {"total_price": float, "currency": "USD", "details": {...}}
"""
```

### 16. `src/engine/calendar_engine.py`

```python
"""
Google Calendar integration via google-api-python-client.
Pattern: async httpx wrapper around Calendar API.

async def create_measurement_event(
    date: str,           # YYYY-MM-DD
    time: str,           # HH:MM
    client_name: str,
    phone: str,
    address: str,
    settings
) -> dict:
    # 1. Parse date/time, validate (9:30-21:00, max 7 days ahead, 15-min intervals)
    # 2. Build event body (summary, description with client details, location)
    # 3. Call Google Calendar API (insert event)
    # 4. Return {"event_id": str, "html_link": str, "start": str, "end": str}

VALIDATION:
- Time must be 15-min interval (9:30, 9:45, 10:00, ...)
- Working hours: 9:30 - 21:00
- Max 7 days ahead
- Timezone: settings.timezone (Asia/Bishkek)
"""
```

### 17. `src/db/postgres.py`

```python
"""
asyncpg connection pool for local Postgres.
Pattern: like /Users/mosesvasilenko/tg_keto/src/db/postgres.py

Functions:
- create_pool(settings) -> asyncpg.Pool (min=2, max=10, timeout=30s)
- close_pool(pool)
- run_migrations(pool, migrations_dir="migrations/")
  # Reads *.sql files in order, executes each in a transaction
  # Tracks applied migrations in a _migrations table

Queries (prepared statements):
- mark_update_received(pool, update_id) -> bool
  # INSERT INTO processed_updates (telegram_update_id, status) VALUES ($1, 'received')
  # ON CONFLICT DO NOTHING RETURNING telegram_update_id
  # Returns True if inserted (new), False if conflict (duplicate)

- mark_update_status(pool, update_id, status)
  # UPDATE processed_updates SET status=$2, completed_at=now() WHERE telegram_update_id=$1

- insert_inbound_event(pool, update_id, chat_id, user_id, text, raw_update)
  # INSERT INTO inbound_events (...)

- insert_outbound_event(pool, chat_id, reply_text, reply_markup, inbound_event_id)
  # INSERT INTO outbound_events (...) RETURNING id

- mark_outbound_sent(pool, event_id)
- mark_outbound_failed(pool, event_id, error)
- get_pending_outbound(pool, limit=20) -> list

- get_conversation_state(pool, chat_id) -> dict | None
- upsert_conversation_state(pool, chat_id, mode, step, collected_params)

- insert_chat_message(pool, chat_id, role, text)
- get_chat_messages(pool, chat_id, limit=20) -> list
- clear_chat_messages(pool, chat_id)
"""
```

### 18. `src/db/redis_client.py`

```python
"""
Redis client for queue, cache, locks.
Pattern: like /Users/mosesvasilenko/tg_keto/src/db/redis_client.py

Uses redis.asyncio with connection pool.

Class RedisClient:
    def __init__(self, redis_url: str)
    async def connect()
    async def close()

    # Queue
    async def enqueue_job(self, queue_name: str, job: Job)
        # LPUSH queue_name json_serialized_job
    async def dequeue_job(self, queue_name: str, timeout: int = 5) -> Job | None
        # BRPOP queue_name timeout → parse JSON → Job

    # Per-user lock
    async def acquire_user_lock(self, chat_id: int, ttl: int = 180) -> bool
        # SET lock:user:{chat_id} 1 NX EX ttl
    async def release_user_lock(self, chat_id: int)
        # DEL lock:user:{chat_id}

    # Cache
    async def get_cached(self, key: str) -> str | None
    async def set_cached(self, key: str, value: str, ttl: int)
    async def delete_cached(self, key: str)
"""
```

### 19. `src/db/postgres.py` — EXTENDED (ALL data in one local DB)

The postgres.py from section 17 must ALSO include these queries for business data.
ALL tables are in the SAME local PostgreSQL database. No Supabase.

```python
"""
ADDITIONAL queries beyond section 17 (state tables):

# Clients
- get_client_by_chat_id(pool, chat_id) -> dict | None
- create_client(pool, chat_id, first_name, username) -> dict
- update_client(pool, chat_id, **fields) -> dict
- list_clients(pool, search=None, limit=50, offset=0) -> list
- get_client_with_orders(pool, chat_id) -> dict  # JOIN with orders

# Orders
- create_order(pool, request_id, chat_id, details_json, render_paths, price) -> dict
- get_order(pool, request_id) -> dict | None
- list_orders(pool, status=None, limit=50, offset=0, search=None) -> list
- update_order_status(pool, request_id, status, note="") -> dict
- count_orders_by_status(pool) -> dict

# Measurements
- create_measurement(pool, client_chat_id, scheduled_time, address, notes) -> dict
- list_measurements(pool, upcoming_only=True, limit=50) -> list
- confirm_measurement(pool, measurement_id) -> dict
- get_measurements_for_client(pool, chat_id) -> list

# Prices (editable via Mini App)
- get_prices(pool) -> list
- update_price(pool, price_id, **fields) -> dict
- seed_default_prices(pool)  # Called during migration if prices table is empty

# Materials (editable via Mini App)
- get_materials(pool) -> list
- update_material(pool, material_id, **fields) -> dict
- seed_default_materials(pool)  # Called during migration if materials table is empty

# Analytics (for Mini App dashboard)
- get_dashboard_stats(pool, days=30) -> dict
    # Returns: {total_orders, total_revenue, orders_today, pending_measurements}
- get_orders_by_day(pool, days=30) -> list[dict]
    # Returns: [{date: "2026-04-13", count: 5, revenue: 4200}, ...]
- get_popular_configs(pool, limit=10) -> list[dict]
    # Returns: [{shape, glass_type, frame_color, count}, ...]
- get_conversion_funnel(pool, days=30) -> dict
    # Returns: {conversations_started, params_collected, renders_requested, orders_confirmed}
"""
```

### 20. `src/api/app.py`

```python
"""
FastAPI sub-application for Mini App REST API.
Mounted on main aiohttp app at /api/ prefix.

Routes:
GET  /api/orders                  → list orders (filters: status, date range, search)
GET  /api/orders/{id}             → order detail with renders
PATCH /api/orders/{id}/status     → update order status

GET  /api/clients                 → list clients
GET  /api/clients/{chat_id}       → client detail with order history

GET  /api/measurements            → list measurements (upcoming/past)
POST /api/measurements/{id}/confirm → confirm measurement

GET  /api/pricing                 → get all prices
PATCH /api/pricing/{id}           → update price entry

GET  /api/materials               → get all materials
PATCH /api/materials/{id}         → update material

GET  /api/analytics/dashboard     → dashboard stats
GET  /api/analytics/orders-by-day → time series
GET  /api/analytics/popular-configs → popular partition configurations
GET  /api/analytics/conversion    → conversion funnel

GET  /api/settings                → bot settings
PATCH /api/settings               → update settings

All routes protected by auth.py (Telegram initData HMAC validation).
Only users in MANAGER_CHAT_IDS can access.
"""
```

### 21. `src/api/auth.py`

```python
"""
Telegram Mini App initData HMAC-SHA256 validation.

ALGORITHM:
1. Client sends: Authorization: tma <raw_init_data>
2. Parse init_data as query string
3. Extract 'hash' value, remove it from params
4. Sort remaining key=value pairs alphabetically
5. Join with newline: "auth_date=123\nquery_id=abc\nuser={...}"
6. secret_key = HMAC-SHA256(key=b"WebAppData", msg=bot_token.encode())
7. computed_hash = HMAC-SHA256(key=secret_key, msg=data_check_string.encode()).hexdigest()
8. Compare computed_hash == received_hash
9. Check auth_date is not older than 24 hours
10. Parse user JSON from validated data
11. Verify user.id is in MANAGER_CHAT_IDS

FastAPI dependency:
async def verify_telegram_auth(authorization: str = Header(...)) -> dict:
    # Returns validated user dict or raises HTTPException(401)
"""
```

### 22. Mini App Frontend (`mini-app/`)

```
Technologies:
- React 19 + TypeScript
- Vite 6+
- @tma.js/sdk-react (Telegram Mini App SDK)
- TelegramUI (native Telegram-styled components)
- Tailwind CSS (utility styles)
- Chart.js or recharts (analytics charts)
- date-fns (date formatting, Russian locale)

mini-app/package.json dependencies:
{
  "react": "^19.0.0",
  "react-dom": "^19.0.0",
  "react-router-dom": "^7.0.0",
  "@tma.js/sdk-react": "latest",
  "@telegram-apps/telegram-ui": "latest",
  "recharts": "^2.12.0",
  "date-fns": "^3.6.0",
  "tailwindcss": "^3.4.0"
}

Pages:
1. Dashboard.tsx — KPIs (orders today, revenue, pending measurements), charts
2. Orders.tsx — table with filters (status, date), search, pagination
3. OrderDetail.tsx — full order info, renders preview, price breakdown, status change
4. Clients.tsx — client list with search, order count
5. ClientDetail.tsx — client card, order history, measurements
6. Measurements.tsx — calendar view, upcoming/past, confirm/reschedule
7. PricingEditor.tsx — editable table of base prices, modifiers, add-ons
8. Settings.tsx — bot configuration (prompts, timeouts, etc.)

API Client (mini-app/src/api/client.ts):
- Uses fetch() with Authorization: tma <initData> header
- Base URL from Vite env: VITE_API_URL
- Type-safe request/response wrappers

Auth Hook (mini-app/src/hooks/useTelegram.ts):
- Initialize @tma.js/sdk-react
- Expand viewport
- Disable vertical swipes
- Return { user, initData, rawInitData, themeParams }
```

### 23. Migrations

```sql
-- 001_processed_updates.sql
CREATE TABLE IF NOT EXISTS processed_updates (
    telegram_update_id BIGINT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','completed','failed')),
    worker_id TEXT,
    bot_type TEXT NOT NULL DEFAULT 'client' CHECK (bot_type IN ('client','manager')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- 002_inbound_events.sql
CREATE TABLE IF NOT EXISTS inbound_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_update_id BIGINT NOT NULL,
    telegram_chat_id BIGINT NOT NULL,
    telegram_user_id BIGINT,
    message_text TEXT,
    msg_type TEXT DEFAULT 'text',
    bot_type TEXT NOT NULL DEFAULT 'client',
    raw_update JSONB,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inbound_chat_id ON inbound_events (telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_inbound_received ON inbound_events (received_at DESC);

-- 003_outbound_events.sql
CREATE TABLE IF NOT EXISTS outbound_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT NOT NULL,
    bot_type TEXT NOT NULL DEFAULT 'client',
    reply_text TEXT,
    reply_markup JSONB,
    media JSONB,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
    attempts INT NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT,
    inbound_event_id UUID REFERENCES inbound_events(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outbound_pending ON outbound_events (status) WHERE status = 'pending';

-- 004_conversation_state.sql
CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id BIGINT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'idle',
    step TEXT,
    collected_params JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 005_chat_messages.sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON chat_messages (chat_id, created_at DESC);

-- 006_clients.sql
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id BIGINT UNIQUE NOT NULL,
    telegram_username TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clients_chat_id ON clients (chat_id);

-- 007_orders.sql
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id TEXT UNIQUE NOT NULL,
    client_chat_id BIGINT NOT NULL REFERENCES clients(chat_id),
    details JSONB NOT NULL DEFAULT '{}',
    render_paths JSONB DEFAULT '{}',        -- {"0deg": "/data/renders/xxx/0deg.png", ...}
    total_price NUMERIC(10,2),
    currency TEXT DEFAULT 'USD',
    price_breakdown JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','confirmed','in_progress','completed','cancelled')),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_client ON orders (client_chat_id);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders (created_at DESC);

-- 008_measurements.sql
CREATE TABLE IF NOT EXISTS measurements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_chat_id BIGINT NOT NULL REFERENCES clients(chat_id),
    scheduled_time TIMESTAMPTZ NOT NULL,
    address TEXT,
    notes TEXT,
    confirmed BOOLEAN NOT NULL DEFAULT false,
    calendar_event_id TEXT,
    calendar_html_link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_measurements_time ON measurements (scheduled_time);

-- 009_prices.sql
CREATE TABLE IF NOT EXISTS prices (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,                 -- 'base_sqm', 'modifier', 'addon'
    name TEXT NOT NULL,                     -- 'clear_glass', 'premium_glass', 'frame_surcharge', etc.
    label_ru TEXT NOT NULL,                 -- 'Прозрачное стекло', 'Цветная рамка', etc.
    value NUMERIC(10,2) NOT NULL,           -- price in USD or percentage
    value_type TEXT DEFAULT 'absolute' CHECK (value_type IN ('absolute','percentage')),
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed default prices during migration (INSERT IF NOT EXISTS)

-- 010_materials.sql
CREATE TABLE IF NOT EXISTS materials (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('frame','glass')),
    label_ru TEXT NOT NULL,
    color_rgba JSONB,                       -- [0.05, 0.05, 0.05, 1.0]
    roughness NUMERIC(4,3) DEFAULT 0.05,
    config_id TEXT,                          -- matches key in app_config.json ("1","2",...)
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed default materials during migration (from app_config.json)
```

ALL tables are in the SAME local PostgreSQL database.
No Supabase. No cloud database. Everything local.

### 24. `run_webhook.py`

```python
"""
Entry point for webhook server.
Serves HTTPS directly using self-signed certificate (no reverse proxy needed).

1. Create aiohttp Application
2. Add routes:
   - POST /webhook/client → webhook.handle_client_webhook
   - POST /webhook/manager → webhook.handle_manager_webhook
   - GET /health → health check handler
3. Mount FastAPI sub-app at /api/ (for Mini App REST API)
4. Create SSL context:
   ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
   ssl_context.load_cert_chain(settings.ssl_cert_path, settings.ssl_key_path)
5. on_startup:
   - Create asyncpg pool
   - Create Redis client
   - Create aiohttp.ClientSession (for Telegram API)
   - Run migrations
   - Register webhooks with Telegram (both bots)
     IMPORTANT: Upload the certificate file when calling setWebhook:
     POST https://api.telegram.org/bot{token}/setWebhook
     multipart/form-data:
       url = https://3.79.24.73:88/webhook/client
       certificate = @certs/webhook.pem  (file upload!)
       secret_token = {settings.telegram_webhook_secret}
       allowed_updates = ["message", "callback_query"]
   - Set Mini App menu button for manager bot
6. on_shutdown:
   - Close all pools/clients
7. web.run_app(app, host='0.0.0.0', port=88, ssl_context=ssl_context)

NOTE: The server listens on port 88 with HTTPS (self-signed cert).
Telegram accepts self-signed certs when the public cert is uploaded via setWebhook.
No Caddy, no nginx, no reverse proxy needed.
"""
```

### 25. `run_worker.py`

```python
"""
Entry point for worker processes.

1. Initialize:
   - asyncpg pool
   - Redis client
   - aiohttp.ClientSession
   - Supabase client
2. Start concurrent tasks:
   - client_worker_loop() — processes queue:incoming
   - manager_worker_loop() — processes queue:manager
   - outbox_dispatcher_loop() — retries pending sends every 15s
3. Graceful shutdown on SIGTERM/SIGINT
"""
```

### 26. `docker-compose.yml` (dev)

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: shermos_bot
      POSTGRES_USER: shermos
      POSTGRES_PASSWORD: change_me
    volumes: ["pg_data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shermos"]
      interval: 10s

volumes:
  redis_data:
  pg_data:
```

### 27. `docker-compose.prod.yml`

```yaml
# Adds:
# - webhook service (python run_webhook.py)
# - worker service (python run_worker.py)
# - pgbouncer (connection pooling)
# - nginx (reverse proxy, SSL termination)
# All services use .env file
# Health checks on all services
```

### 28. `requirements.txt`

```
aiohttp>=3.9,<4.0
asyncpg>=0.29,<1.0
redis>=5.0,<6.0
pydantic>=2.5,<3.0
pydantic-settings>=2.1,<3.0
httpx>=0.27,<1.0
structlog>=24.0
trimesh>=4.0
pyrender>=0.1.45
numpy>=1.24
Pillow>=10.0
google-api-python-client>=2.0
google-auth-httplib2>=0.2
google-auth-oauthlib>=1.0
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=4.0
aioresponses>=0.7

# NOTE: NO supabase SDK. All data in local PostgreSQL via asyncpg.
```

### 29. `.env.example`

```bash
# === Telegram Client Bot ===
TELEGRAM_BOT_TOKEN=your_client_bot_token
TELEGRAM_WEBHOOK_SECRET=generate_random_string_64chars

# === Telegram Manager Bot ===
MANAGER_BOT_TOKEN=your_manager_bot_token
MANAGER_WEBHOOK_SECRET=generate_another_random_string
MANAGER_CHAT_IDS=123456789,987654321

# === Webhook (HTTPS on port 88, self-signed cert) ===
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=88
WEBHOOK_PUBLIC_URL=https://3.79.24.73:88
SSL_CERT_PATH=certs/webhook.pem
SSL_KEY_PATH=certs/webhook.key

# === Render Storage ===
RENDERS_DIR=data/renders

# === PostgreSQL (Docker on server) ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=shermos_bot
POSTGRES_USER=shermos
POSTGRES_PASSWORD=change_me_in_production

# === Redis ===
REDIS_URL=redis://localhost:6379/0

# === Gemini CLI ===
LLM_CLI_COMMAND=gemini
LLM_CLI_FLAGS=-p
MAX_LLM_CONCURRENCY=2
LLM_TIMEOUT_SECONDS=90

# === Google Calendar ===
GCAL_CALENDAR_ID=primary
GCAL_CREDENTIALS_PATH=credentials.json
TIMEZONE=Asia/Bishkek

# === Mini App ===
MINI_APP_URL=https://your-mini-app.example.com

# === Logging ===
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

## EXISTING CODE TO COPY (DO NOT REWRITE)

These files must be copied from the existing project at
`/Users/mosesvasilenko/3d_visualization/` into `shermos-bot/src/render/`:

1. `utils/create_partition.py` → `src/render/create_partition.py`
2. `utils/validators.py` → `src/render/validators.py`
3. `utils/config_manager.py` → `src/render/config_manager.py`
4. `config/app_config.json` → `config/app_config.json`

These files are battle-tested and must NOT be rewritten. Only update import paths
if the module structure changes.

NOTE: `supabase_storage.py` is NOT copied — we no longer use Supabase.
Images are saved to local filesystem and sent via Telegram file upload.

---

## REFERENCE PROJECTS (read for patterns, do not copy verbatim)

1. `/Users/mosesvasilenko/tg_keto/` — Main architectural reference
   - `src/bot/webhook.py` — webhook handler pattern
   - `src/queue/worker.py` — worker loop pattern
   - `src/llm/executor.py` — Gemini CLI subprocess pattern
   - `src/db/redis_client.py` — Redis queue/lock/cache pattern
   - `src/db/postgres.py` — asyncpg pool pattern
   - `src/config.py` — pydantic-settings pattern
   - `src/models.py` — Pydantic model pattern

2. `/Users/mosesvasilenko/Rudolf_music_site/services/telegram-bot/`
   - `src/server.ts` → Webhook deduplication, pending change state machine
   - `src/gemini.ts` → Subprocess spawn with cascading SIGTERM/SIGKILL
   - `src/bot.ts` → Raw HTTP Telegram API client (no SDK)

---

## TESTING REQUIREMENTS

**Target: >85% line coverage across `src/`.** Run with:
```bash
pytest tests/ -v --cov=src --cov-report=term-missing --tb=short
```

Tests run on the SERVER via SSH (Redis + Postgres available there).
Use `pytest-asyncio` for all async tests. Mode: `auto`.

### `tests/conftest.py` — Shared Fixtures

```python
"""
Fixtures available to ALL test files:

Database:
- pg_pool: asyncpg pool connected to test database (shermos_bot_test)
  Created fresh each session. Migrations applied automatically.
  Cleaned (TRUNCATE all tables) between each test function.
- redis_client: RedisClient connected to database 1 (not 0!)
  FLUSHDB between each test function.

Mocks:
- mock_telegram: aioresponses context that intercepts all
  https://api.telegram.org/* calls. Returns 200 with {"ok": true}.
- mock_supabase: patches SupabaseClient methods with AsyncMock.
- mock_gemini: patches executor.call_llm to return configurable JSON.
  Default return: '{"reply_text": "Test reply", "actions": null}'

Factories:
- sample_update(text="Hi", chat_id=12345) -> dict
  Returns a valid Telegram Update JSON with customizable fields.
- sample_job(text="Hi", chat_id=12345, bot_type="client") -> Job
  Returns a valid Job model instance.
- sample_render_action(**overrides) -> dict
  Returns a valid render_partition action dict.
- sample_init_data(user_id=12345) -> str
  Returns a valid Telegram initData string with correct HMAC hash,
  signed with test bot token. For Mini App auth testing.

Marks:
- @pytest.mark.integration — requires real Redis + Postgres (skip in CI without services)
"""
```

### Test Files — COMPREHENSIVE LIST

Every test function must be implemented. This is not a wishlist — it is a contract.

```python
# ═══════════════════════════════════════════════════════════
# tests/test_config.py — Configuration validation
# ═══════════════════════════════════════════════════════════
# - test_settings_loads_from_env
# - test_settings_defaults
# - test_webhook_url_properties
# - test_manager_chat_ids_parsing_csv
# - test_manager_chat_ids_empty
# - test_postgres_dsn_format

# ═══════════════════════════════════════════════════════════
# tests/test_models.py — Pydantic model validation
# ═══════════════════════════════════════════════════════════
# - test_job_serialization_roundtrip
# - test_job_defaults
# - test_actions_json_valid
# - test_actions_json_reply_text_required
# - test_actions_json_reply_text_max_length
# - test_render_action_all_fields
# - test_render_action_minimal_fields
# - test_render_action_invalid_shape_rejected
# - test_schedule_action_valid
# - test_state_patch_valid

# ═══════════════════════════════════════════════════════════
# tests/test_webhook.py — Webhook endpoint (aiohttp test client)
# ═══════════════════════════════════════════════════════════
# - test_health_returns_200
# - test_valid_client_webhook_returns_200
# - test_valid_manager_webhook_returns_200
# - test_invalid_secret_still_returns_200 (prevent Telegram retry storm)
# - test_missing_secret_header_returns_200
# - test_malformed_json_returns_200
# - test_duplicate_update_id_skipped (idempotency)
# - test_job_enqueued_to_redis_after_valid_webhook
# - test_job_has_correct_bot_type_client
# - test_job_has_correct_bot_type_manager
# - test_inbound_event_created_in_postgres
# - test_processed_update_marked_received
# - test_callback_query_parsed_correctly
# - test_webhook_response_time_under_100ms (performance)

# ═══════════════════════════════════════════════════════════
# tests/test_telegram_sender.py — Telegram API client
# ═══════════════════════════════════════════════════════════
# - test_send_message_success
# - test_send_message_with_reply_markup
# - test_send_message_html_parse_mode
# - test_send_media_group
# - test_send_chat_action_typing
# - test_edit_message
# - test_set_webhook
# - test_delete_webhook
# - test_answer_callback_query
# - test_api_error_raises_exception
# - test_network_error_raises_exception
# - test_rate_limit_429_handling

# ═══════════════════════════════════════════════════════════
# tests/test_keyboards.py — Inline keyboard builders
# ═══════════════════════════════════════════════════════════
# - test_confirm_render_keyboard_structure
# - test_confirm_render_keyboard_callback_data
# - test_manager_order_keyboard_buttons
# - test_open_mini_app_keyboard_web_app_type

# ═══════════════════════════════════════════════════════════
# tests/test_worker.py — Worker processing pipeline
# ═══════════════════════════════════════════════════════════
# - test_command_start_sends_welcome
# - test_command_help_sends_help
# - test_command_status_shows_info
# - test_command_clear_resets_state
# - test_command_examples_sends_photos
# - test_text_message_calls_llm
# - test_llm_response_sent_to_user
# - test_render_action_triggers_render_engine
# - test_render_result_images_sent_to_user
# - test_render_result_price_sent_to_user
# - test_render_notifies_manager
# - test_schedule_action_creates_calendar_event
# - test_profile_update_action_updates_supabase
# - test_state_patch_updates_conversation_state
# - test_chat_messages_saved_after_processing
# - test_processed_update_marked_completed
# - test_per_user_lock_acquired_and_released
# - test_locked_user_job_requeued
# - test_max_retries_exceeded_drops_job
# - test_llm_timeout_sends_error_message
# - test_render_crash_sends_error_message
# - test_unknown_exception_sends_error_and_releases_lock
# - test_manager_job_processed_separately
# - test_callback_query_confirm_render
# - test_callback_query_cancel_render
# - test_typing_indicator_sent_before_llm

# ═══════════════════════════════════════════════════════════
# tests/test_outbox_dispatcher.py — Outbox retry loop
# ═══════════════════════════════════════════════════════════
# - test_pending_events_retried
# - test_successful_retry_marks_sent
# - test_failed_retry_increments_attempts
# - test_max_attempts_marks_failed
# - test_no_pending_events_does_nothing
# - test_dispatcher_runs_periodically

# ═══════════════════════════════════════════════════════════
# tests/test_llm_executor.py — Gemini CLI subprocess
# ═══════════════════════════════════════════════════════════
# - test_call_llm_returns_stdout
# - test_call_llm_strips_ansi_codes
# - test_call_llm_timeout_raises
# - test_call_llm_nonzero_exit_raises
# - test_call_llm_semaphore_limits_concurrency
# - test_call_llm_file_not_found_raises
# - test_sigterm_then_sigkill_on_timeout

# ═══════════════════════════════════════════════════════════
# tests/test_llm_actions.py — Action parsing + validation
# ═══════════════════════════════════════════════════════════
# - test_parse_valid_json_direct
# - test_parse_json_in_markdown_fences
# - test_parse_json_from_brace_extraction
# - test_parse_nested_braces_correct
# - test_fallback_on_completely_invalid_output
# - test_fallback_on_empty_output
# - test_validate_render_params_all_fields
# - test_validate_render_params_minimal
# - test_validate_render_params_invalid_shape
# - test_validate_schedule_params
# - test_validate_state_patch
# - test_actions_null_is_valid
# - test_reply_text_required

# ═══════════════════════════════════════════════════════════
# tests/test_prompt_builder.py — Prompt assembly
# ═══════════════════════════════════════════════════════════
# - test_prompt_contains_system_section
# - test_prompt_contains_tools_schema
# - test_prompt_contains_user_message
# - test_prompt_includes_conversation_history
# - test_prompt_includes_collected_params
# - test_prompt_respects_max_context_messages
# - test_prompt_for_new_user_no_profile
# - test_prompt_for_returning_user_with_profile

# ═══════════════════════════════════════════════════════════
# tests/test_fsm.py — Finite state machine
# ═══════════════════════════════════════════════════════════
# - test_idle_to_collecting_valid
# - test_collecting_to_confirming_valid
# - test_confirming_to_rendering_valid
# - test_rendering_to_idle_valid
# - test_idle_to_scheduling_valid
# - test_idle_to_rendering_invalid (must go through collecting first)
# - test_rendering_to_collecting_invalid
# - test_get_missing_params_straight_shape
# - test_get_missing_params_l_shape_needs_width_b
# - test_get_missing_params_u_shape_needs_width_b_and_c
# - test_get_missing_params_none_when_complete
# - test_format_summary_straight
# - test_format_summary_l_shaped
# - test_format_summary_with_handle
# - test_format_summary_russian_text

# ═══════════════════════════════════════════════════════════
# tests/test_pricing.py — Price calculation
# ═══════════════════════════════════════════════════════════
# - test_straight_partition_base_price
# - test_l_shaped_partition_price
# - test_u_shaped_partition_price
# - test_premium_glass_modifier
# - test_bronze_glass_modifier
# - test_non_standard_frame_color_surcharge
# - test_volume_discount_over_8sqm
# - test_no_volume_discount_under_8sqm
# - test_handle_addon_modern
# - test_handle_addon_classic
# - test_combined_modifiers
# - test_price_returns_details_breakdown
# - test_zero_area_raises_error

# ═══════════════════════════════════════════════════════════
# tests/test_render_engine.py — Render engine async wrapper
# ═══════════════════════════════════════════════════════════
# - test_render_straight_partition_returns_4_images
# - test_render_l_shaped_partition
# - test_render_u_shaped_partition
# - test_render_with_handle
# - test_render_with_door_section
# - test_render_uploads_to_supabase
# - test_render_falls_back_to_local_on_upload_failure
# - test_render_runs_in_thread_pool (does not block event loop)
# - test_render_invalid_params_raises

# ═══════════════════════════════════════════════════════════
# tests/test_calendar_engine.py — Google Calendar
# ═══════════════════════════════════════════════════════════
# - test_create_event_valid
# - test_create_event_returns_html_link
# - test_invalid_time_not_15min_interval
# - test_invalid_time_outside_working_hours
# - test_invalid_date_too_far_ahead
# - test_timezone_applied_correctly

# ═══════════════════════════════════════════════════════════
# tests/test_query_parser.py — Query string parsing
# ═══════════════════════════════════════════════════════════
# - test_parse_standard_query
# - test_parse_russian_aliases
# - test_parse_color_names_to_ids
# - test_parse_glass_names_to_ids
# - test_parse_shape_aliases
# - test_parse_dimensions_with_units (mm, cm, m)
# - test_parse_mullion_positions_center
# - test_parse_mullion_positions_percentage
# - test_parse_mullion_positions_absolute
# - test_parse_empty_query_returns_defaults
# - test_parse_malformed_query_returns_defaults

# ═══════════════════════════════════════════════════════════
# tests/test_db_postgres.py — Postgres operations
# ═══════════════════════════════════════════════════════════
# - test_create_pool_connects
# - test_run_migrations_creates_tables
# - test_run_migrations_idempotent
# - test_mark_update_received_returns_true_for_new
# - test_mark_update_received_returns_false_for_duplicate
# - test_insert_and_get_conversation_state
# - test_upsert_conversation_state_updates
# - test_insert_and_get_chat_messages
# - test_chat_messages_ordered_by_date
# - test_chat_messages_limit_respected
# - test_clear_chat_messages

# ═══════════════════════════════════════════════════════════
# tests/test_db_redis.py — Redis operations
# ═══════════════════════════════════════════════════════════
# - test_enqueue_and_dequeue_job
# - test_dequeue_empty_returns_none_after_timeout
# - test_fifo_order_preserved
# - test_acquire_lock_success
# - test_acquire_lock_already_held
# - test_release_lock
# - test_lock_expires_after_ttl
# - test_set_and_get_cached
# - test_cache_expires_after_ttl
# - test_delete_cached

# ═══════════════════════════════════════════════════════════
# tests/test_api_auth.py — Mini App authentication
# ═══════════════════════════════════════════════════════════
# - test_valid_init_data_passes
# - test_invalid_hash_rejected_401
# - test_missing_authorization_header_401
# - test_wrong_auth_prefix_401 (not "tma ")
# - test_expired_auth_date_rejected_401 (>24h old)
# - test_non_manager_user_rejected_403
# - test_valid_manager_user_returns_user_dict

# ═══════════════════════════════════════════════════════════
# tests/test_api_orders.py — Orders API endpoints
# ═══════════════════════════════════════════════════════════
# - test_list_orders_returns_json
# - test_list_orders_filter_by_status
# - test_list_orders_pagination
# - test_get_order_by_id
# - test_get_order_not_found_404
# - test_update_order_status
# - test_update_order_invalid_status_400
# - test_unauthorized_request_401

# ═══════════════════════════════════════════════════════════
# tests/test_api_clients.py — Clients API endpoints
# ═══════════════════════════════════════════════════════════
# - test_list_clients
# - test_list_clients_search
# - test_get_client_detail
# - test_get_client_not_found_404

# ═══════════════════════════════════════════════════════════
# tests/test_api_measurements.py — Measurements API
# ═══════════════════════════════════════════════════════════
# - test_list_measurements_upcoming
# - test_list_measurements_past
# - test_confirm_measurement
# - test_confirm_already_confirmed

# ═══════════════════════════════════════════════════════════
# tests/test_api_pricing.py — Pricing API
# ═══════════════════════════════════════════════════════════
# - test_get_all_prices
# - test_update_price
# - test_get_all_materials
# - test_update_material

# ═══════════════════════════════════════════════════════════
# tests/test_api_analytics.py — Analytics API
# ═══════════════════════════════════════════════════════════
# - test_dashboard_stats
# - test_orders_by_day_time_series
# - test_popular_configs
# - test_conversion_funnel

# ═══════════════════════════════════════════════════════════
# tests/test_e2e.py — End-to-end integration tests
# ═══════════════════════════════════════════════════════════
# @pytest.mark.integration (requires all services running)
# - test_full_render_flow:
#     1. POST webhook with text "Хочу прямую перегородку 3x2.5"
#     2. Assert job enqueued
#     3. Process job (mock Gemini to return render action)
#     4. Assert render engine called
#     5. Assert images uploaded
#     6. Assert price calculated
#     7. Assert response sent to Telegram
#     8. Assert order created in Supabase
#     9. Assert manager notified
# - test_full_measurement_flow:
#     1. POST webhook with schedule request
#     2. Process job
#     3. Assert calendar event created
#     4. Assert measurement in Supabase
#     5. Assert confirmation sent
# - test_conversation_context_preserved:
#     1. Send 3 messages in sequence
#     2. Assert conversation history grows
#     3. Assert prompt includes all previous messages
# - test_duplicate_webhook_no_double_processing
# - test_concurrent_users_no_interference
```

---

## IMPLEMENTATION ORDER

Execute in this exact sequence. Do not skip ahead.
ALL code is written LOCALLY on macOS. Server commands run via `ssh aws-shermos1-frankfurt "..."`.

### Phase 0: Server Cleanup & Repo Setup

**IMPORTANT:** Server user is `ubuntu`, use `sudo` for Docker/systemd.

0.1. SSH into server and stop old Shermos services:
```bash
ssh aws-shermos1-frankfurt "
  # Backup old .env
  cp ~/3d_visualization/.env ~/env_backup_shermos_old.env 2>/dev/null
  
  # Stop n8n container
  sudo docker stop n8n 2>/dev/null && sudo docker rm n8n 2>/dev/null
  
  # Kill old Python render server (pid on port 8080)
  kill \$(sudo lsof -t -i :8080) 2>/dev/null
  
  # Kill ngrok
  pkill ngrok 2>/dev/null
  
  # Remove old project
  rm -rf ~/3d_visualization
  
  # Remove n8n data
  rm -rf ~/.n8n
  
  # Remove dead Docker containers and unused images (saves ~12GB!)
  sudo docker container prune -f
  sudo docker image prune -a -f
  
  echo 'Cleanup complete'
  df -h /
"
```

**DO NOT touch these:**
- `music_school_app` Docker container (ports 80/443)
- `musikschule-tg-bot` systemd service (port 8443)
- `buzz-container` Docker (port 3000)
- `/home/ubuntu/Rudolf_music_site/`
- `/etc/letsencrypt/`

0.2. Generate self-signed SSL certificate on server:
```bash
ssh aws-shermos1-frankfurt "
  mkdir -p ~/shermos-bot/certs
  openssl req -newkey rsa:2048 -sha256 -nodes \
    -keyout ~/shermos-bot/certs/webhook.key \
    -x509 -days 3650 \
    -out ~/shermos-bot/certs/webhook.pem \
    -subj '/CN=3.79.24.73'
  echo 'Certificate generated:'
  openssl x509 -in ~/shermos-bot/certs/webhook.pem -noout -subject -dates
"
```
This cert is valid for 10 years. The aiohttp server will use it directly.
The webhook.pem file is also uploaded to Telegram when calling setWebhook.

0.3. Create new project directory LOCALLY:
```bash
mkdir -p ~/shermos-bot && cd ~/shermos-bot
git init
```

0.4. Create bare repo on server for git push:
```bash
ssh aws-shermos1-frankfurt "
  mkdir -p ~/shermos-bot.git && cd ~/shermos-bot.git && git init --bare
  # Create post-receive hook for auto-checkout
  cat > hooks/post-receive << 'HOOK'
#!/bin/bash
GIT_WORK_TREE=/home/ubuntu/shermos-bot git checkout -f
cd /home/ubuntu/shermos-bot
echo 'Code deployed to /home/ubuntu/shermos-bot'
HOOK
  chmod +x hooks/post-receive
  mkdir -p ~/shermos-bot
"
```

0.5. Add remote locally:
```bash
cd ~/shermos-bot
git remote add production aws-shermos1-frankfurt:shermos-bot.git
```

0.6. Add port 88 to AWS Security Group:
The user must manually add an inbound rule in AWS Console:
- Type: Custom TCP
- Port: 88
- Source: 0.0.0.0/0
- Description: Shermos Telegram webhook

This is a one-time manual step. All other setup is automated.

### Phase 1: Core Python Backend (LOCAL)
1. Create project directory structure (all dirs + `__init__.py` files)
2. Write `requirements.txt` and `pyproject.toml`
3. Write `src/config.py`
4. Write `src/models.py`
5. Write `src/utils/logger.py`
6. Write all migration SQL files
7. Write `src/db/postgres.py` (ALL queries — state tables + business tables)
8. Write `src/db/redis_client.py`
9. Write `src/bot/telegram_sender.py`
11. Write `src/bot/keyboards.py`
12. Write `src/bot/webhook.py`
13. Write `run_webhook.py`
14. Write `docker-compose.yml`
15. Write `.env.example`
16. Write `tests/conftest.py`
17. Write `tests/test_webhook.py`
18. **CHECKPOINT**: Commit and push, verify webhook server starts on server:
```bash
git add -A && git commit -m "Phase 1: webhook server"
git push production main
ssh aws-shermos1-frankfurt "
  cd ~/shermos-bot
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  # Start Redis and Postgres via Docker
  docker compose up -d
  # Run migrations
  python -c 'import asyncio; from src.db.postgres import create_pool, run_migrations; from src.config import settings; asyncio.run(run_migrations(asyncio.run(create_pool(settings))))'
  # Run tests
  pytest tests/test_webhook.py -v
"
```

### Phase 2: Worker + LLM Pipeline (LOCAL)
19. Write `src/queue/worker.py` (skeleton — command handling only)
20. Write `src/queue/outbox_dispatcher.py`
21. Write `run_worker.py`
22. Write `src/llm/tools_schema.py`
23. Write `src/llm/prompt_builder.py`
24. Write `src/llm/executor.py`
25. Write `src/llm/actions_parser.py`
26. Write `src/engine/fsm.py`
27. Write `tests/test_worker.py`, `tests/test_llm_actions.py`, `tests/test_fsm.py`
28. **CHECKPOINT**: Commit, push, test on server:
```bash
git add -A && git commit -m "Phase 2: worker + LLM pipeline"
git push production main
ssh aws-shermos1-frankfurt "cd ~/shermos-bot && source .venv/bin/activate && pytest tests/ -v --tb=short"
```

### Phase 3: Render + Pricing + Calendar (LOCAL)
29. Copy existing render files from `/Users/mosesvasilenko/3d_visualization/utils/` → `src/render/`
30. Copy `config/app_config.json`
31. Write `src/utils/query_parser.py` (extract from existing server.py)
32. Write `src/engine/pricing_engine.py` (extract from existing server.py)
33. Write `src/engine/render_engine.py`
34. Write `src/engine/calendar_engine.py`
35. Write `src/llm/actions_applier.py`
36. Complete `src/queue/worker.py` (full LLM + actions pipeline)
37. Write `tests/test_render.py`, `tests/test_pricing.py`
38. **CHECKPOINT**: Commit, push, test:
```bash
git add -A && git commit -m "Phase 3: render + pricing + calendar"
git push production main
ssh aws-shermos1-frankfurt "cd ~/shermos-bot && source .venv/bin/activate && pytest tests/ -v --tb=short"
```

### Phase 4: Mini App CMS API (LOCAL)
39. Write `src/api/auth.py`
40. Write `src/api/app.py`
41. Write all `src/api/routes_*.py`
42. Write `tests/test_api_auth.py`, `tests/test_api_orders.py`, `tests/test_api_clients.py`, `tests/test_api_measurements.py`, `tests/test_api_pricing.py`, `tests/test_api_analytics.py`
43. **CHECKPOINT**: Commit, push, test

### Phase 5: Mini App Frontend (LOCAL)
44. Initialize `mini-app/` (package.json, vite, tsconfig, tailwind)
45. Write `mini-app/src/api/client.ts`
46. Write `mini-app/src/hooks/useTelegram.ts`
47. Write all Mini App pages and components
48. Build: `cd mini-app && npm install && npm run build`
49. **CHECKPOINT**: Commit, push

### Phase 6: Production Deployment (LOCAL → SERVER via SSH)
50. Write `Dockerfile`
51. Write `docker-compose.prod.yml`
52. Write `deploy.sh` (deployment script)
53. Commit, push, deploy:
```bash
git add -A && git commit -m "Phase 6: production deployment"
git push production main
ssh aws-shermos1-frankfurt "
  cd ~/shermos-bot
  # Copy .env from backup and update values
  cp ~/env_backup_shermos_old.env .env
  # Edit .env to add new vars (MANAGER_BOT_TOKEN, etc.)
  
  # Build and start
  docker compose -f docker-compose.prod.yml up -d --build
  
  # Run full test suite
  source .venv/bin/activate
  pytest tests/ -v --cov=src --cov-report=term-missing
  
  # Verify health
  curl -s http://localhost:8080/health
"
```

### Phase 7: Final Verification
54. Register webhooks with Telegram for both bots
55. Send `/start` to client bot — verify response
56. Send `/start` to manager bot — verify response  
57. Run full e2e test (send render request, verify images returned)
58. Open Mini App from manager bot — verify CMS loads

---

## STYLE GUIDE

- Python: Black formatter, 100 char line length
- Type hints on all function signatures
- Docstrings on all public functions (one-line or Google style)
- Imports: stdlib → third-party → local (separated by blank lines)
- Async everywhere possible (aiohttp, asyncpg, redis.asyncio)
- Synchronous render code runs in asyncio.run_in_executor(None, ...)
- Logging: structlog with JSON output, include chat_id and update_id in all log events
- Error messages to users: always in Russian
- No bare except: always catch specific exceptions
- No print(): use structlog logger

## LANGUAGE

- All user-facing text: Russian
- All code comments: English
- All docstrings: English
- All log messages: English
- Variable names: English

---

## DEPLOYMENT ON SERVER

Server: `ssh aws-shermos1-frankfurt` (Ubuntu, Docker installed, domain configured)

### `deploy.sh` — Deployment Script (LOCAL, runs SSH commands)

```bash
#!/bin/bash
# Usage: ./deploy.sh
# Pushes code to server and restarts services

set -euo pipefail

echo "=== Pushing code to production ==="
git push production main

echo "=== Deploying on server ==="
ssh aws-shermos1-frankfurt << 'REMOTE'
  set -euo pipefail
  cd /home/ubuntu/shermos-bot

  echo "--- Installing Python dependencies ---"
  python3 -m venv .venv 2>/dev/null || true
  source .venv/bin/activate
  pip install -q -r requirements.txt

  echo "--- Building Mini App ---"
  cd mini-app && npm ci --silent && npm run build && cd ..

  echo "--- Starting Docker services ---"
  docker compose up -d

  echo "--- Running migrations ---"
  python -c "
import asyncio
from src.db.postgres import create_pool, run_migrations
from src.config import settings
async def migrate():
    pool = await create_pool(settings)
    await run_migrations(pool)
    await pool.close()
asyncio.run(migrate())
  "

  echo "--- Running tests ---"
  pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

  echo "--- Restarting services ---"
  sudo systemctl restart shermos-webhook
  sudo systemctl restart shermos-worker

  echo "--- Health check ---"
  sleep 2
  curl -sf --insecure https://localhost:88/health && echo " ✅ Webhook OK" || echo " ❌ Webhook FAILED"
  # --insecure because self-signed cert

  echo "=== Deploy complete ==="
REMOTE
```

### systemd Service Files (create on server via SSH)

```bash
# Run ONCE to create systemd services:
ssh aws-shermos1-frankfurt << 'SETUP'

# === Webhook Service ===
cat > /etc/systemd/system/shermos-webhook.service << 'EOF'
[Unit]
Description=Shermos Bot Webhook Server
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shermos-bot
EnvironmentFile=/home/ubuntu/shermos-bot/.env
ExecStart=/home/ubuntu/shermos-bot/.venv/bin/python run_webhook.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# === Worker Service ===
cat > /etc/systemd/system/shermos-worker.service << 'EOF'
[Unit]
Description=Shermos Bot Worker
After=network.target docker.service shermos-webhook.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shermos-bot
EnvironmentFile=/home/ubuntu/shermos-bot/.env
ExecStart=/home/ubuntu/shermos-bot/.venv/bin/python run_worker.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-unit.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable shermos-webhook shermos-worker
systemctl start shermos-webhook shermos-worker

echo "Services created and started"
SETUP
```

### Server Directory Structure (after deployment)

```
/home/ubuntu/shermos-bot/          # Git working tree (auto-checkout on push)
├── .env                           # Production secrets (NOT in git)
├── .venv/                         # Python virtual environment
├── credentials.json               # Google Calendar OAuth (NOT in git)
├── docker-compose.yml             # Redis + Postgres
├── mini-app/dist/                 # Built Mini App static files
├── src/                           # Python source
├── tests/                         # Tests
├── logs/                          # Runtime logs (created by app)
└── data/
    └── renders/                   # Rendered PNG images (local storage)
        ├── {request_id_1}/
        │   ├── 0deg.png
        │   ├── 90deg.png
        │   ├── 180deg.png
        │   └── 270deg.png
        └── {request_id_2}/
            └── ...

/home/ubuntu/shermos-bot.git/      # Bare repo for git push

# Other projects on this server (DO NOT TOUCH):
/home/ubuntu/Rudolf_music_site/    # Music school site + bot
```

### Monitoring Commands (for verification)

```bash
# View service logs
ssh aws-shermos1-frankfurt "journalctl -u shermos-webhook -f --no-pager -n 50"
ssh aws-shermos1-frankfurt "journalctl -u shermos-worker -f --no-pager -n 50"

# Check service status
ssh aws-shermos1-frankfurt "systemctl status shermos-webhook shermos-worker"

# Check Docker containers
ssh aws-shermos1-frankfurt "docker ps"

# Run tests on server
ssh aws-shermos1-frankfurt "cd /root/shermos-bot && source .venv/bin/activate && pytest tests/ -v"

# Quick health check (--insecure for self-signed cert)
ssh aws-shermos1-frankfurt "curl -sk https://localhost:88/health | python3 -m json.tool"

# Check webhook registration with Telegram
ssh aws-shermos1-frankfurt "curl -s 'https://api.telegram.org/bot\$TELEGRAM_BOT_TOKEN/getWebhookInfo' | python3 -m json.tool"

# Check SSL certificate
ssh aws-shermos1-frankfurt "openssl x509 -in ~/shermos-bot/certs/webhook.pem -noout -subject -dates"
```

---

## GITIGNORE

Create `.gitignore` in the project root:

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
dist/
build/

# Environment
.env
.env.local
.env.production

# Secrets & Certificates
credentials.json
certs/
*.pem
*.key

# Runtime
logs/
data/
*.log

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Node (Mini App)
mini-app/node_modules/
mini-app/dist/

# Docker
docker-compose.override.yml

# Test
.coverage
htmlcov/
.pytest_cache/
```
