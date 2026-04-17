# GEMINI SPEC — Gallery of real work photos (v2, post-audit)

> **Audience:** Gemini CLI 3.1 Pro Preview.
> **Mode:** first pass is done and committed locally; this revision lists the **remaining fixes** plus the full original spec for context. If a section says ✅ DONE you must verify it and leave it alone. Sections marked ❌ FIX are the work items for this run.
> **Style:** user-facing strings in Russian; code/comments/docs in English. Follow existing file style. No marketing tone.
> **Rule of thumb:** do not invent files, tables, helpers, or workflows. If the spec says "read X first", read X before editing.

---

## 0. SELF-CHECK BEFORE YOU FINISH

Before declaring success, in this exact order:

1. `rm -f` every throwaway helper script you created at repo root (`fix_*.py`, `debug_*.py`, `fix_worker.py`, etc.). **None** of these may remain. Use real in-place edits; never commit a one-shot patch script.
2. Run `/Users/mosesvasilenko/shermos-bot/.venv/bin/python -m pytest -q` — must be green.
3. Run `/Users/mosesvasilenko/shermos-bot/.venv/bin/python -m pytest --cov -q` — coverage must stay ≥ 85% (configured `fail_under = 85`).
4. Run `cd mini-app && ./node_modules/.bin/tsc --noEmit` — must exit 0.
5. Run `cd mini-app && npm run build` — must produce `dist/` without errors.
6. `git status` — only these files may appear as changed/new (relative to pre-feature `main`):
   - Modified: `.env.example`, `.gitignore`, `mini-app/src/App.tsx`, `mini-app/src/api/client.ts`, `mini-app/src/components/Layout.tsx`, `run_api.py`, `src/api/app.py`, `src/bot/keyboards.py`, `src/config.py`, `src/db/postgres.py`, `src/queue/worker.py`, `tests/helpers.py`, `tests/test_worker_more.py`
   - New: `docs/GEMINI_SPEC_gallery.md`, `migrations/017_gallery.sql`, `mini-app/src/pages/Gallery.tsx`, `src/api/routes_gallery.py`, `tests/test_gallery_api.py`, `tests/test_gallery_db.py`, `tests/test_worker_gallery.py`
   - Anything else → you did something wrong, fix it.

If ANY of the checks fail, fix and rerun. Do not ask the user to run them.

---

## 1. Goal and UX (unchanged)

- **Manager** opens the Mini App → new tab "Галерея" → creates a "work" bound to a `partition_type` and attaches 1+ photos. Can edit title/notes, toggle `is_published`, delete a work (with photos), delete a single photo, upload more photos.
- **Client** gets 3D render + price → bot asks "Показать 3 реальные работы такого же типа?" with Да / Нет. The rate-keyboard is deferred until this branch resolves.
- **Да** → ≤ 3 random published works of the same `partition_type`. Each work = one album (2–10 photos) or `sendPhoto` (1 photo). Caption on first photo only = work title. Then rate-keyboard. **Нет** → rate-keyboard. **No works** → "Скоро пополним базу реальными фотографиями этого типа." → rate-keyboard.

---

## 2. ❌ FIX — Bugs discovered in the first pass

### 2.1 Runtime bug in `src/api/routes_gallery.py` (POST /works)

Current code (wrong — will AttributeError in real Telegram):

```python
created_by_chat_id=auth["user"].id if auth.get("user") else None,
```

The `require_telegram_auth` dependency returns `data` where `data["user"]` is the **raw JSON string** Telegram sent, and `data["user_json"]` is the parsed dict. See `src/api/auth.py::validate_init_data`.

**Fix** — replace that line with:

```python
created_by_chat_id=(auth.get("user_json") or {}).get("id"),
```

No other changes in this route.

### 2.2 Test coverage gap that hid the bug

Add a test that sends `user` in `signed_init_data` and asserts `created_by_chat_id` actually reaches the DB helper.

In `tests/test_gallery_api.py` add a test similar to:

```python
def test_create_work_captures_chat_id(fake_pool):
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "title": ""}]
    init_data = signed_init_data(user='{"id": 777, "first_name": "M"}')
    res = client.post(
        "/api/gallery/works",
        headers={"X-Telegram-Init-Data": init_data},
        json={"partition_type": "fixed"},
    )
    assert res.status_code == 200
    # asyncpg helper receives created_by_chat_id as the 7th positional arg.
    insert_call = next(c for c in fake_pool.calls if "INSERT INTO gallery_works" in c[1])
    assert 777 in insert_call[2]
```

`signed_init_data` already accepts `**extra: str`, so passing `user='{"id":777,...}'` is valid — see `tests/helpers.py`.

### 2.3 `.gitignore` is wrong

Current state:

```
data/
!data/gallery/
!data/renders/
…
# Local Netlify folder
.netlify
```

Problems:
- `!data/gallery/` and `!data/renders/` **re-include** every file under those directories. User photos and render PNGs would be committed on the next `git add .`.
- `.netlify` is unrelated to this project — do not add it.

**Fix** — restore `.gitignore` so the Gallery change is a single added line:

```
data/
data/gallery/
```

Actually `data/` alone already covers `data/gallery/`. The second line is redundant. **Simplest correct fix: leave `.gitignore` at the state it was in before the first pass, adding nothing.** The directory is created at runtime by `run_api.py` via `os.makedirs(..., exist_ok=True)`; empty directories don't need a `.gitignore` entry.

Concrete delta from current state:
- Remove the lines: `!data/gallery/`, `!data/renders/`, the empty line after them, `# Local Netlify folder`, `.netlify`.

After the fix `.gitignore` must contain exactly what it had pre-feature — no additions.

### 2.4 Junk scripts at repo root

Delete every one of these if present. They are throwaway edit scripts from the first pass and must not be committed:

```
fix_worker.py
fix_syntax.py
fix_tests.py
fix_tests2.py
fix_tests3.py
fix_tests4.py
debug_401.py
debug_env.py
```

Use real file edits for any subsequent changes. Never commit a script whose only purpose is to patch another source file.

### 2.5 `tests/test_api_orders.py` unnecessary change

First pass swapped a hardcoded `b"manager-token"` for `settings.manager_bot_token.encode()` in that file. It's equivalent under the current `conftest.py` (sets `MANAGER_BOT_TOKEN=manager-token`), but the change is outside the feature's scope. **Revert** `tests/test_api_orders.py` to its pre-feature content — don't touch unrelated tests.

### 2.6 Verify `_send_render_result` does NOT send the rate-keyboard anymore

`src/queue/worker.py::_send_render_result` must end by sending the **offer** keyboard (`gallery_offer_keyboard(request_id, pt)`) and nothing else. The rate-keyboard is owned by the callback handler (`_send_gallery_works` and the `gallery_skip` branch of `_handle_client_callback`). Re-read the function and confirm.

---

## 3. ✅ DONE — don't rewrite, but verify the following still match

### 3.1 Migration — `migrations/017_gallery.sql`

Must contain exactly these two `CREATE TABLE IF NOT EXISTS` statements (TEXT PK, CHECK on partition_type, CASCADE FK, indexes). If anything drifted, restore to:

```sql
CREATE TABLE IF NOT EXISTS gallery_works (
    id TEXT PRIMARY KEY,
    partition_type TEXT NOT NULL
        CHECK (partition_type IN ('fixed', 'sliding_2', 'sliding_3', 'sliding_4')),
    glass_type TEXT,
    matting TEXT,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_by_chat_id BIGINT,
    is_published BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gallery_works_type_published
    ON gallery_works(partition_type, is_published);

CREATE TABLE IF NOT EXISTS gallery_photos (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES gallery_works(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    width INT,
    height INT,
    size_bytes INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gallery_photos_work
    ON gallery_photos(work_id, sort_order);
```

Generate IDs Python-side with `uuid4().hex`. Do **not** use `pgcrypto` / `gen_random_uuid()` — the repo doesn't have it.

### 3.2 DB helpers — `src/db/postgres.py`

Nine async functions already appended to the end of the file:

- `create_gallery_work(pool, partition_type, glass_type, matting, title, notes, created_by_chat_id) -> dict`
- `list_gallery_works(pool, partition_type=None, published_only=False) -> list[dict]` — includes `photo_count` via LEFT JOIN + GROUP BY, ORDER BY `created_at DESC`.
- `get_gallery_work(pool, work_id) -> dict | None` — two-query form (work row + photos list), photos ordered by `(sort_order, id)`.
- `update_gallery_work(pool, work_id, **fields) -> dict` — allow-list of keys, `ValueError` on missing.
- `delete_gallery_work(pool, work_id) -> list[dict]` — fetch photos **before** delete (CASCADE removes them), return photo rows.
- `add_gallery_photo(pool, work_id, file_path, sort_order, width, height, size_bytes) -> dict`
- `list_photos_for_work(pool, work_id) -> list[dict]`
- `delete_gallery_photo(pool, photo_id) -> dict | None` — `DELETE … RETURNING *`.
- `pick_random_gallery_works(pool, partition_type, limit=3) -> list[dict]` — `is_published = true AND EXISTS(…)`, `ORDER BY random() LIMIT $2`, second query loads photos via `work_id = ANY($1)`, attaches `photos` to each work.

### 3.3 Config

`src/config.py::Settings` has `gallery_dir: str = "data/gallery"` and `gallery_photo_max_bytes: int = 8 * 1024 * 1024`.

`.env.example` has a block near `RENDERS_DIR`:

```
# --- Gallery (real-work photos attached by managers) ---
GALLERY_DIR=data/gallery
GALLERY_PHOTO_MAX_BYTES=8388608
```

### 3.4 FastAPI route file `src/api/routes_gallery.py`

Mirror of `routes_pricing.py`. Endpoints, models, Pillow validation, format-based extension, and the upload loop are as required. Reminders for Gemini verifying:

- `WorkCreate` / `WorkPatch` use `Literal["fixed","sliding_2","sliding_3","sliding_4"]` for `partition_type`.
- `FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}`. Unknown `img.format` → `HTTPException(400, "Неподдерживаемый формат")`.
- Oversize → `HTTPException(400, "Файл слишком большой")`.
- Always `Image.verify()` on a fresh `BytesIO`, then reopen to read `size` and `format` (verify consumes the stream).
- `upload_photos` first calls `get_gallery_work` and 404s if missing.
- `delete_work` unlinks each returned photo file, then `rmdir` the (now empty) work directory best-effort inside `try/except OSError`.
- `delete_photo` unlinks the file best-effort after DB delete.

### 3.5 Static mount + router registration

`src/api/app.py::create_app` includes `routes_gallery.router`.

`run_api.py`, BEFORE the SPA mount, runs:

```python
import os
os.makedirs(settings.gallery_dir, exist_ok=True)
app.mount("/gallery", StaticFiles(directory=settings.gallery_dir, check_dir=False), name="gallery")
```

The SPA mount at `/` stays last — it's a catch-all.

### 3.6 Mini App

- `mini-app/src/api/client.ts` has `apiPost`, `apiDelete`, `apiUpload` (multipart; no `Content-Type` header — browser sets boundary).
- `mini-app/src/App.tsx` has `"gallery"` in the `Page` union and the route switch.
- `mini-app/src/components/Layout.tsx` has `{ id: "gallery", label: "Галерея" }` in the nav array.
- `mini-app/src/pages/Gallery.tsx` renders the list, filter dropdown, "Добавить работу" inline form, work cards with first-photo thumbnail, actions (Edit / Toggle published / Delete / Add photos), expandable grid with per-photo delete. Sequential uploads. Strict TypeScript. Russian labels.

### 3.7 Bot consent flow

`src/bot/keyboards.py` has:

```python
def gallery_offer_keyboard(order_id: str, partition_type: str) -> dict:
    return _inline_keyboard([
        [
            {"text": "Да, покажите", "callback_data": f"gallery_show:{order_id}:{partition_type}"},
            {"text": "Нет, спасибо", "callback_data": f"gallery_skip:{order_id}:{partition_type}"},
        ]
    ])
```

`src/queue/worker.py`:

- `_send_render_result` finishes with the **offer** keyboard (not rate-keyboard).
- `_send_gallery_works(job, pg_pool, sender, order_id, partition_type)` implements the Да branch: `pick_random_gallery_works` → iterate → `send_media_group` (≥2 photos) / `send_photo` (1 photo) / fallback text (0 works) → rate-keyboard.
- `_handle_client_callback(job, pg_pool, sender) -> bool` dispatches `rate_render:*`, `gallery_show:*`, `gallery_skip:*`. Unknown → `return False` (falls through to LLM).
- `process_client_job` checks `msg_type == "callback_query"` **before** the command / voice / LLM branches.

### 3.8 Tests

- `tests/test_gallery_db.py` uses the `FakePool` from `tests/helpers.py`. Remember: `calls[i]` is a 3-tuple `(method, query, args)` — query is `calls[i][1]`, args is `calls[i][2]`.
- `tests/test_gallery_api.py` uses `fastapi.testclient.TestClient` + `signed_init_data()` + `app.dependency_overrides[get_pool] = lambda: pool`. PNG fixture works.
- `tests/test_gallery_worker.py` (or `test_worker_gallery.py` — match existing file naming convention, already correct) covers the three consent branches plus the "unknown callback returns False" case plus "`_send_render_result` sends offer keyboard".

### 3.9 Helpers

`tests/helpers.py` has a `FakePool` class with sequential `results` list and `calls` recorder — keep the implementation you have. Do NOT redefine it per test file.

---

## 4. Hard don'ts (reinforced)

- **Don't** commit throwaway patch/debug scripts. Edit files directly.
- **Don't** change `.gitignore` in a way that re-includes `data/**`. Leave it pre-feature.
- **Don't** touch tests/files unrelated to the feature (`test_api_orders.py` etc.).
- **Don't** use `auth["user"].id`. Use `auth.get("user_json", {}).get("id")`.
- **Don't** introduce new Python or npm deps. Pillow, FastAPI, asyncpg, aiohttp, React, Vite, TS are already present.
- **Don't** mount `/gallery` after the SPA catch-all.
- **Don't** call `sendMediaGroup` with fewer than 2 items.
- **Don't** derive image extension from filename.
- **Don't** use `gen_random_uuid()` or `pgcrypto`.
- **Don't** write user-facing strings in English.

---

## 5. Acceptance checklist

Gemini must self-verify and only then mark the task done. All must be true:

1. `pytest -q` → all tests pass. Record the number.
2. `pytest --cov -q` → coverage ≥ 85%.
3. `cd mini-app && ./node_modules/.bin/tsc --noEmit` → exit 0.
4. `cd mini-app && npm run build` → succeeds, `dist/` updated.
5. `git status` shows only the files listed in §0.6 — no `fix_*.py`, `debug_*.py`, no unrelated edits.
6. `grep -n 'auth\["user"\]\.id' src/api/routes_gallery.py` returns nothing.
7. `grep -n '\.netlify\|!data/' .gitignore` returns nothing.
8. POSTing `/api/gallery/works` with a real Telegram-style initData (including `user='{"id":N,…}'`) stores `created_by_chat_id = N` in the DB.
9. Uploading 3 valid images to a work writes 3 rows in `gallery_photos` and 3 files under `data/gallery/<work_id>/`, derived from PIL format.
10. After the render, Telegram sees the offer keyboard first; the rate keyboard only appears after the gallery branch resolves.

---

## 6. Final note to Gemini

You already have ~95% of the code correct. This revision is intentionally narrow: fix the runtime bug, clean up the junk, restore `.gitignore`, and keep everything else exactly as it is. When done, run the commands in §0 and only then report success.
