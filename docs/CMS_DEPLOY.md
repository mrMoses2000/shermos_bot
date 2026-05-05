# CMS Deployment Guide

> Updated 2026-05-05. Telegram Mini App removed. Only the CMS browser entry remains.

## Build artifacts

Running `npm run build` in `mini-app/` produces a single-entry Vite build:

```
mini-app/dist/
  index.html          # CMS entry (no Telegram SDK)
  assets/             # JS/CSS chunks (content-hashed)
```

## Routing requirements

`index.html` is a standalone SPA. The web server / CDN must serve it for all paths:

| URL prefix | Serve file        | Notes                     |
|------------|-------------------|---------------------------|
| `/assets/` | `dist/assets/`    | Static pass-through       |
| `/*`       | `dist/index.html` | SPA fallback              |

This is already configured in `netlify.toml` for Netlify deployments.

### Nginx example

```nginx
location /assets/ {
    root /var/www/cms/dist;
}
location / {
    try_files $uri /index.html;
}
```

## Netlify deployment

The `netlify.toml` at the repo root configures automatic builds:

```toml
[build]
  base = "mini-app"
  command = "npm run build"
  publish = "mini-app/dist"
```

Set `VITE_API_BASE_URL` in Netlify UI → Site settings → Environment variables
to point at the backend API (e.g. `https://api.shermos.ru`).

On every push to `main`, Netlify auto-builds and deploys the CMS.

## FastAPI backend — no change needed

`src/api/app.py` is a pure API server; it does not serve static files.
The CMS is served from Netlify. The backend only needs the CMS origin in
`CORS_ALLOWED_ORIGINS`.

## Auth notes

### CSRF cookie

The `csrf_token` cookie is set by the backend with `SameSite=None; Secure`.
- It is **only accessible over HTTPS**. In local dev over plain `http://localhost`
  the cookie will not be set and `getCsrfToken()` will return `null`. This is
  expected — `/api/auth/refresh` only needs CSRF protection in production.
- Developers testing locally should use `mkcert` + `https://` or a tunnel
  (e.g. `cloudflared tunnel`) to get a valid HTTPS context.

### Environment variable

Set `VITE_API_BASE_URL` at build time if the frontend and API are on different domains:

```bash
VITE_API_BASE_URL=https://api.shermos.ru npm run build
```

If left empty, all `/api/*` requests go to the same origin.

## Local development

```bash
cd mini-app
npm run dev
# Open http://localhost:5173/ → CMS login
```
