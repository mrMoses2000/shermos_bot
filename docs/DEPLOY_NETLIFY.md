# Frontend deploy на Netlify

CMS (фронт мастера) живёт на Netlify, backend (FastAPI + workers + БД) — на Ubuntu сервере. Между ними — кросс-доменные запросы через явный `VITE_API_BASE_URL`. Боты клиента и мастера общаются с пользователями через WhatsApp; CMS — это веб-интерфейс мастера для просмотра заказов, замеров, цен и т.д.

> **Архитектура:** оба бота — только WhatsApp. Telegram отключён (Phase 10). Единственный браузерный фронт — CMS на Netlify; в нём же и точка входа.

## Текущая конфигурация

| | Значение |
|---|---|
| Netlify site name | `shermos-mini-app-takoe` |
| Netlify site ID | `121a8211-34a6-4f70-bc6e-a5fc4e261138` |
| Production URL (CMS) | https://shermos-mini-app-takoe.netlify.app |
| Admin URL | https://app.netlify.com/projects/shermos-mini-app-takoe |
| Текущий API backend | https://carb-investigation-drive-equations.trycloudflare.com (cloudflared trycloudflare, **временный**) |

## Деплой: что уже автоматизировано, что вручную

Сейчас деплой **ручной через CLI**. Continuous deployment (auto-deploy на каждый git push) — следующий шаг (см. ниже «Setup auto-deploy»).

### Ручной деплой (текущий способ)

```bash
cd /Users/mosesvasilenko/shermos-bot/mini-app
VITE_API_BASE_URL=https://<api-backend-url> npm run build

cd ..
netlify deploy --dir=mini-app/dist \
  --site=121a8211-34a6-4f70-bc6e-a5fc4e261138 \
  --no-build --prod
```

Где `<api-backend-url>` — текущий публичный URL backend'а. Получить:
```bash
ssh aws-shermos1-frankfurt 'journalctl -u shermos-tunnel | grep trycloudflare | tail -1'
```

`--no-build` важен: Netlify иначе попытается прогнать свой build remotely, который сейчас не нужен (мы билдим локально с правильным env).

### Setup auto-deploy (todo)

Чтобы каждый push в `main` авто-деплоил Netlify:
1. Открыть https://app.netlify.com/projects/shermos-mini-app-takoe → Site settings → Build & deploy → Continuous deployment.
2. Connect to GitHub → выбрать репо `mrMoses2000/shermos_bot` → branch `main`.
3. Netlify автоматически подхватит `netlify.toml` (base = `mini-app`, command = `npm run build`, publish = `mini-app/dist`).
4. В **Environment variables** в Netlify UI выставить `VITE_API_BASE_URL` со значением текущего API URL.
5. После каждого push — Netlify сам сделает `npm run build` с этим env и опубликует.

## Backend env (на сервере)

`CORS_ALLOWED_ORIGINS` должен содержать URL Netlify-сайта:
```
CORS_ALLOWED_ORIGINS=https://shermos-mini-app-takoe.netlify.app
```

`MINI_APP_URL` — Netlify URL (используется ботом для построения inline-кнопок «Открыть Mini App»):
```
MINI_APP_URL=https://shermos-mini-app-takoe.netlify.app/
```

После любого изменения — рестарт `shermos-api` и `shermos-worker`.

## Доставка ссылки на CMS мастеру

CMS — это веб-сайт. Мастер открывает его в обычном браузере (на телефоне или ноутбуке) по ссылке `https://shermos-mini-app-takoe.netlify.app/`. Можно отправить ему ссылку через WhatsApp (или закладку в браузере).

Клиент в CMS не заходит — для клиента есть только WhatsApp-бот. CMS-логин по WhatsApp-OTP (введи свой номер → получишь код в WhatsApp → введи код → внутри).

## Локальная разработка

Способ 1 — **Backend отдаёт SPA напрямую** (как было до Phase 6):
```bash
cd /Users/mosesvasilenko/shermos-bot/mini-app && npm run build
SERVE_FRONTEND_LOCAL=1 .venv/bin/python run_api.py
```
Открыть `http://127.0.0.1:9443/` — работает single-origin, CORS не нужен.

Способ 2 — **Vite dev-сервер + backend на 9443** (правильнее для разработки):
```bash
# Terminal 1: backend без статики
.venv/bin/python run_api.py

# Terminal 2: фронт с hot-reload
cd mini-app && VITE_API_BASE_URL=http://127.0.0.1:9443 npm run dev
```
Открыть Vite URL (обычно `http://localhost:5173`). Понадобится разрешить cors на 5173 на бэке (env `CORS_ALLOWED_ORIGINS=http://localhost:5173`).

## Стабильный API URL — известная проблема

Сейчас backend публичный URL — `trycloudflare`-ad-hoc. **Каждый рестарт `shermos-tunnel` даёт новый URL.** При смене URL нужно:
1. Получить новый: `ssh aws-shermos1-frankfurt 'journalctl -u shermos-tunnel | grep trycloudflare | tail -1'`.
2. Обновить `VITE_API_BASE_URL` в Netlify UI (или в `.env.production` локально и пересобрать-передеплоить).
3. Обновить `CORS_ALLOWED_ORIGINS` на сервере (если из Netlify-стороны изменился origin — обычно нет, только если Netlify домен меняется).

Долгосрочно — настроить named cloudflared tunnel со своим доменом, см. план Phase 6.4 в `REMEDIATION_PLAN.md`.

## Откат

Каждый deploy на Netlify создаёт **immutable URL** (`<deploy-id>--shermos-mini-app-takoe.netlify.app`) — он живёт всегда. Чтобы откатиться:
1. Открыть https://app.netlify.com/projects/shermos-mini-app-takoe/deploys.
2. Найти предыдущий зелёный deploy.
3. Кнопка «Publish deploy» → этот deploy становится production.

Никаких локальных команд не нужно.
