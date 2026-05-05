# CMS Deployment Guide

## Build artifacts

Running `npm run build` in `mini-app/` produces a multi-entry Vite build:

```
mini-app/dist/
  index.html          # Telegram Mini App entry
  cms.html            # CMS browser entry (no Telegram SDK)
  assets/             # shared JS/CSS chunks (content-hashed)
```

## Routing requirements

Both HTML files are standalone SPAs. The web server / CDN must route:

| URL prefix | Serve file          | Notes                        |
|------------|---------------------|------------------------------|
| `/cms*`    | `dist/cms.html`     | All sub-paths → same file    |
| `/`        | `dist/index.html`   | Telegram Mini App            |
| `/assets/` | `dist/assets/`      | Static pass-through          |

### Cloudflare Workers / Pages example

Create a `_redirects` file (Cloudflare Pages) or a Worker route:

```
/cms/*    /cms.html    200
/assets/* /assets/:splat 200
/*        /index.html  200
```

### Nginx example

```nginx
location /assets/ {
    root /var/www/mini-app/dist;
}
location /cms {
    try_files /cms.html =404;
}
location / {
    try_files /index.html =404;
}
```

## FastAPI backend — no change needed

`src/api/app.py` does **not** mount static files; it is a pure API server.
The Mini App and CMS are served as static files by the CDN / reverse proxy.
The backend only needs to accept requests from the CMS origin in `CORS_ALLOWED_ORIGINS`.

## Auth notes

### CSRF cookie in CMS mode

The `csrf_token` cookie is set by the backend with `SameSite=None; Secure`.
This means:
- It is **only accessible over HTTPS**. In local dev over plain `http://localhost`
  the cookie will not be set and `getCsrfToken()` will return `null`. This is
  expected — the `/api/auth/refresh` endpoint only needs CSRF protection in
  production where the cookie arrives from the browser.
- Developers testing the CMS locally should use `mkcert` + `https://` or a
  tunnel (e.g. `cloudflared tunnel`) to get a valid HTTPS context.

### Environment variable

Set `VITE_API_BASE` at build time to point at the API origin if the frontend
and API are on different domains:

```bash
VITE_API_BASE=https://api.shermos.ru npm run build
```

If left empty, all `/api/*` requests go to the same origin (recommended when
the reverse proxy forwards `/api/` to the FastAPI process).

## Local development

```bash
cd mini-app
npm run dev
# Open http://localhost:5173/         → Mini App (Telegram context needed)
# Open http://localhost:5173/cms.html → CMS login
```

In dev, Vite serves `cms.html` at `/cms.html`. In production the router maps
`/cms*` → `cms.html`. Use the `.html` URL in dev only.
