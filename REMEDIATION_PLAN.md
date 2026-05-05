# План санации проекта Shermos Bot

**Версия:** 1, 2026-05-04
**Контекст:** аудит ветки `feat/wa-phase-1-bridge` (HEAD `60d1735`) + 99 незакоммиченных правок на сервере `aws-shermos1-frankfurt`. Полный аудит — в чате, основания см. в логах продакшена и спот-ридах файлов.

**Целевое состояние (TL;DR):**
- 1 экземпляр сервиса = 2 номера WhatsApp = 2 логических бота (клиентский + менеджерский), оба маршрутизуются корректно, вход от обычных клиентов на менеджерский номер не блокируется.
- Сайт мастера на CMS (FastAPI + Mini-App SPA) работает как полноценная замена Telegram Mini App, с авторизацией через WhatsApp-OTP и JWT, без открытых CORS-уязвимостей.
- 10 carry-over багов из предыдущего аудита закрыты, есть тесты на каждый.
- Деплой чистый: ноль `.rej/.orig/patch.diff` в репе, всё закоммичено в одну ветку.

**Принцип работы:**
1. Каждый этап имеет `Gate`-критерии. Этап не считается выполненным, пока gate не зелёный.
2. Каждый шаг имеет блок `agent prompt` — самодостаточное задание для следующего агента (с путями, тестами, командами проверки).
3. `Verify` — что Я (или ты) запускаешь после шага: тесты, SSH-команды на серверe, ручные проверки.
4. Между этапами Я отдельной кнопкой говорю «можно идти дальше» или «вернись и доделай».
5. Деструктивные операции на сервере (`git reset`, удаление файлов, перезапуск сервисов) выполняются только с явным подтверждением.

## Workflow rules (нерушимые)

Эти правила действуют для **всех** Phase'ов и шагов. Их нарушение = повод вернуть агента назад, даже если код корректный.

### W-1. Только git, никаких правок «руками» на сервере
- На сервере **нельзя** редактировать файлы в `~/shermos_bot/`, кроме `git pull`/`git checkout`.
- Вся правка кода идёт ТОЛЬКО на ноутбуке → коммит → push → на сервере `git pull`.
- Если агент обнаружил, что на сервере отличается рабочее дерево от HEAD (`git status -s` ≠ 0) — **остановиться и сообщить**, не «исправлять» руками.

### W-2. Каждый шаг — отдельная feature-ветка от стабильной базы
- База — `prod-snapshot-2026-05-04` (актуальная прод-ветка).
- Ветка имени `fix/<scope>-<date>` или `feat/<scope>-<date>`, например `fix/wa-routing-2026-05-04`.
- Прямой коммит в `prod-snapshot-2026-05-04` запрещён. Включается ветка через PR (или fast-forward merge после ручной проверки).

### W-3. Один шаг плана = один коммит
- Не сливать `1.2 + 1.4.1 + 1.4.3` в один большой коммит. Атомарные коммиты ⇒ можно откатить отдельный кусок.
- Сообщение коммита: `<type>(<scope>): <step ID> — <summary>`, например `fix(wa): 1.2 — bridge_role vs sender allowlist semantics`.

### W-4. Локальный клон в чистом виде
- В `/Users/mosesvasilenko/shermos-bot` рабочее дерево всегда чистое (`git status -s` = 0).
- Эксперименты — в worktree (`.claude/worktrees/...`) или в отдельном клоне.
- Ноут и сервер должны указывать на одну и ту же ветку через `origin/` (т.е. тот же commit или ahead-by-N).

### W-5. Цикл разработки строго в 6 шагов

Ни один шаг не пропускается, ни один не переставляется местами. Это базовый цикл, в нём же выполняется и интеграционное тестирование.

| # | Шаг | Где |
|---|---|---|
| 1 | Пишу код | macbook (`/Users/mosesvasilenko/shermos-bot`) |
| 2 | Прогоняю **все** тесты, что можно прогнать локально (unit + мок-based) | macbook |
| 3 | Чиню всё, что упало в шаге 2 | macbook |
| 4 | `git add` (файлами, не `-A`), `git commit`, `git push` | macbook |
| 5 | На сервере `git pull` нужной ветки и `npm/pnpm build` где надо | `ssh aws-shermos1-frankfurt` |
| 6 | Проверяю, что правки реально работают: рестарт сервисов, проверка логов / curl эндпоинтов / интеграционные тесты против серверного Postgres+Redis | `ssh aws-shermos1-frankfurt` |

**Локально Docker НЕ запускается** — на ноуте только unit-тесты. Любые тесты, которым нужен реальный Postgres/Redis, гоняются на сервере (там уже подняты `shermos_bot_postgres_1` и `shermos_bot_redis_1` в Docker). Изоляция теста от прод-данных — отдельная test-БД и Redis namespace, см. Phase 4.1.

**Какие сервисы перезапускать на шаге 6** в зависимости от того, что менялось:

| Изменено | Рестарт |
|---|---|
| `src/queue/worker.py`, `src/llm/*`, `src/engine/*` | `shermos-worker` |
| `src/bot/webhook.py`, `src/db/*` | `shermos-webhook` + `shermos-worker` |
| `src/api/*`, `src/api/auth.py` | `shermos-api` |
| `src/bot/whatsapp_ingress.py` | `shermos-worker` И `shermos-api` (используется обоими) |
| `src/bot/whatsapp_sender.py` | `shermos-worker` (отправка идёт оттуда) |
| `whatsapp-bridge/**` | `shermos-wa-client` И `shermos-wa-manager` |
| `mini-app/**` | пересборка (`npm run build`), потом перезапуск любого сервиса, что отдаёт статику |
| `migrations/*.sql` | `shermos-worker` (миграции прогоняются на старте) **+** проверить, что миграция идемпотентна |

После рестарта — проверка `systemctl is-active <s>` = `active`, потом `journalctl -u <s> --since "1 min ago"` без ошибок.

### W-6. Каждое изменение должно быть проверяемо
- В коммите должны быть тесты, проверяющие правку (или явный `[no-tests]` в сообщении с обоснованием).
- На сервере gate-критерии должны проверяться через `journalctl`/`curl`/`psql`, а не «выглядит хорошо».

---

## Phase −1 — Workflow Discipline и синхронизация ноут↔сервер

**Зачем:** при проверке Phase 1 обнаружилось:
- Локальный клон `/Users/mosesvasilenko/shermos-bot` на ветке `feat/wa-phase-1-bridge` с **97 dirty файлами** — то самое грязное состояние из времени до Phase 0.
- Сервер на `prod-snapshot-2026-05-04`, чистый, ушёл вперёд по коммитам.
- Phase 1 был закоммичен **прямо в `prod-snapshot-2026-05-04`** одним большим коммитом (а не feature-веткой по шагам).
- После пуша на сервер агент не перезапустил `shermos-api`, и фикс allowlist'а **не работает в проде** (старый код в памяти, лог-флуд продолжается).

Эта Phase разово приводит окружение в порядок и подкручивает дисциплину для всех будущих этапов. Без неё Phase 2/3/4 будут страдать от тех же проблем.

### −1.1 Очистить локальный клон

**agent prompt:**
> На ноутбуке в `/Users/mosesvasilenko/shermos-bot`:
> 1. `git status -s | wc -l` — должно быть 97 (или сколько сейчас). Зафиксировать число.
> 2. Сравнить с `~/shermos_bot_attic/` на сервере (Phase 0 туда сложил мусор). Если те же файлы — здесь они тоже мусор.
> 3. Создать локальный attic: `mkdir -p ~/.shermos_bot_local_attic/2026-05-04` и переместить туда:
>    - `.env.backup-*` (если есть)
>    - `*.orig`, `*.rej`
>    - `patch.diff`, `smoke_e2e.py` если в корне
>    - `.playwright-mcp/`, `.netlify/` (если untracked и не нужны)
>    - `shermos-cms-login.png`
> 4. Для остальных dirty файлов — посмотреть `git diff <файл>` и решить:
>    - если правка нужна → закоммитить отдельным branch'ем
>    - если уже есть в `prod-snapshot-2026-05-04` (т.е. была сделана прямо на сервере и мы её догнали через snapshot) → `git checkout <файл>` (откатить локальное)
>    - если совсем мусор → удалить
> 5. После очистки: `git fetch origin && git checkout prod-snapshot-2026-05-04 && git pull origin prod-snapshot-2026-05-04`. Локальная ветка должна указывать на тот же коммит, что и сервер.

**Verify (Я):**
- `cd /Users/mosesvasilenko/shermos-bot && git status -s | wc -l` → 0
- `git rev-parse HEAD` локально == `git rev-parse HEAD` на сервере

### −1.2 Развернуть Phase 1 правильно (через feature-ветку и PR)

**Контекст:** коммит `83db7c9` уже на `prod-snapshot-2026-05-04`. Откатывать его не нужно — он содержит работающие правки. Но его надо переоформить через feature-ветку, чтобы в истории остался правильный паттерн, и добавить недостающие шаги (1.4.1 outbox, 1.4.2 кнопки, 1.4.3 CMS Status).

**Решение:** оставить `83db7c9` как есть (это уже база), но дальнейшую доделку Phase 1 делать в новой ветке `fix/wa-phase1-finishing-2026-05-04` от текущего HEAD `prod-snapshot-2026-05-04`. По завершении — merge через fast-forward, явный коммит-метка.

**agent prompt:**
> 1. `cd /Users/mosesvasilenko/shermos-bot && git checkout prod-snapshot-2026-05-04 && git pull`.
> 2. `git checkout -b fix/wa-phase1-finishing-2026-05-04`.
> 3. Делать ВСЕ дальнейшие правки ТОЛЬКО в этой ветке. Один шаг = один коммит, имя коммита по правилу W-3.
> 4. По завершении — `git push -u origin fix/wa-phase1-finishing-2026-05-04`. Я ревьюю → merge.

**Verify:** ветка существует, коммиты в ней атомарные.

### −1.3 Чек-лист деплоя на сервер

После любого `git pull` на сервере исполнитель должен:
1. Понять, что менялось: `git diff HEAD@{1}..HEAD --stat`.
2. По таблице W-5 определить, какие сервисы перезапустить.
3. Перезапустить **по одному**, проверяя `journalctl -u <s> --since "30 sec ago"` после каждого.
4. Прогнать gate-проверки соответствующего шага (количество ошибок в логах за N минут, curl healthcheck, и т.п.).

**agent prompt:** при каждом деплое формировать отчёт в свободной форме, например:
> «Изменено: `src/bot/whatsapp_ingress.py`, `src/api/routes_whatsapp.py`. По W-5: рестарт `shermos-worker` + `shermos-api`. Перезапустил оба, оба `active`. За 5 минут: `whatsapp_manager_not_allowlisted` = 0 (было 128/час), `whatsapp_client_on_manager_number` = 12. Gate Phase 1.2 пройден.»

### −1.4 Один источник правды для конфигов окружения

**Контекст:** на сервере есть env-переменные (через systemd Environment или /etc/default/...), которые НЕ в git. Когда нужно посмотреть «а что у нас в `manager_whatsapp_numbers_list`», агент идёт на сервер и читает руками. Это нарушает W-1.

**agent prompt:**
> 1. На сервере: `systemctl cat shermos-worker shermos-webhook shermos-api shermos-wa-client shermos-wa-manager | grep -E "^Environment="` — собрать список ВСЕХ env-переменных (без значений секретов!).
> 2. Создать в репо `docs/ENV_REFERENCE.md` со списком всех переменных, описанием, и какой сервис от них зависит. Значения секретов **не указывать**, только имена.
> 3. На сервере все env вынести в один файл `/etc/shermos/shermos.env` с правами `0600` (если ещё нет). Systemd-юниты ссылаются на него через `EnvironmentFile=/etc/shermos/shermos.env`. Это даёт оператору одну точку правки.
> 4. Скрипт-проверка: `scripts/check_env.py` — проверяет, что все обязательные переменные из `ENV_REFERENCE.md` выставлены, при старте сервиса. Падает с понятным сообщением если нет.

**Verify:**
- В репо есть `docs/ENV_REFERENCE.md`.
- На сервере systemctl cat показывает `EnvironmentFile=...`.

### Gate Phase −1
- Локальный `git status -s` = 0.
- Локальный HEAD == server HEAD.
- Ветка `fix/wa-phase1-finishing-2026-05-04` существует.
- `docs/ENV_REFERENCE.md` появился.

После закрытия Phase −1 → переходим к доделке Phase 1 (см. ниже добавленный раздел 1.5).

---

## Phase 0 — Стабилизация деплоя (обязательное предисловие)

**Зачем:** сейчас на сервере 99 файлов dirty + 3 `.rej/.orig` артефакта + миграции 019/020/021 не в git + `patch.diff` 48 КБ + `.env.backup-...` валяется. Любая попытка `git pull`/передеплой сейчас сломает прод. Любые наши правки негде применить, потому что прод != ни одной ветке в репо. Этот этап не правит ни одного бага, только наводит порядок.

### 0.1 Снять снапшот сервера локально

**Цель:** иметь актуальный код в /tmp для аудитов и сравнений (уже сделано в этой сессии: `/tmp/shermos_actual`). Если локальный снапшот уничтожен, повторить:

```bash
SNAPDIR=/tmp/shermos_actual
rm -rf "$SNAPDIR" && mkdir -p "$SNAPDIR"
rsync -az --exclude='.claude' --exclude='node_modules' --exclude='.git' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='dist' \
  --exclude='data' --exclude='certs' --exclude='.playwright-mcp' \
  aws-shermos1-frankfurt:shermos_bot/ "$SNAPDIR/"
```

**Verify:**
- `find /tmp/shermos_actual/src -name "*.py" | wc -l` ≈ 55
- `ls /tmp/shermos_actual/src/queue/worker.py.rej` существует (значит снапшот настоящий)

### 0.2 Закоммитить состояние сервера в snapshot-ветку

**Цель:** зафиксировать в git ровно то, что сейчас в проде, чтобы было что откатывать и с чего бранчеваться.

**agent prompt:**
> На сервере `aws-shermos1-frankfurt` в `~/shermos_bot`:
> 1. Посмотреть `git status -s | wc -l` — должно быть ~99 файлов.
> 2. Создать ветку `prod-snapshot-2026-05-04` от текущего HEAD: `git checkout -b prod-snapshot-2026-05-04`.
> 3. Перед `git add`: ОТДЕЛЬНО просмотреть `.env.backup-*` файлы и `patch.diff` — если содержат секреты, добавить в `.gitignore` и НЕ коммитить.
> 4. `worker.py.orig`, `worker.py.rej`, `worker.py.rej.orig` — НЕ коммитить, добавить в `.gitignore`.
> 5. `git add` оставшегося, `git commit -m "chore(snapshot): production state on 2026-05-04 before remediation"`.
> 6. `git push origin prod-snapshot-2026-05-04`.
> 7. Локально: `git fetch origin && git checkout prod-snapshot-2026-05-04` в основном клоне, чтобы дальше работать с актуальным кодом.

**Verify (Я выполняю):**
- `ssh aws-shermos1-frankfurt 'cd shermos_bot && git status -s | wc -l'` → 0 (только игнорируемые остаются)
- `git fetch origin && git log origin/prod-snapshot-2026-05-04 -1 --stat | head -20` локально → видны новые файлы (`routes_auth.py`, `routes_whatsapp.py`, `whatsapp_ingress.py`, …)
- Все 5 systemd-сервисов на сервере по-прежнему `active (running)`: `ssh aws-shermos1-frankfurt 'systemctl is-active shermos-{worker,webhook,api,wa-client,wa-manager}.service'`

**Gate 0.2:** snapshot-ветка существует на origin, прод не упал, ничего не удалено с сервера, секретов не закоммичено.

### 0.3 Гигиена репозитория на сервере

**Цель:** убрать мусор, который не должен лежать в рабочем дереве сервиса в проде.

**agent prompt:**
> На сервере, после Gate 0.2:
> 1. Перенести `*.orig`, `*.rej`, `patch.diff`, `.env.backup-*`, `shermos-cms-login.png`, `.playwright-mcp/` в `~/shermos_bot_attic/2026-05-04/` (создать каталог), чтобы можно было откатить:
>    ```bash
>    mkdir -p ~/shermos_bot_attic/2026-05-04
>    cd ~/shermos_bot
>    mv src/queue/worker.py.orig src/queue/worker.py.rej src/queue/worker.py.rej.orig patch.diff shermos-cms-login.png ~/shermos_bot_attic/2026-05-04/
>    mv .env.backup-manager-whatsapp-* ~/shermos_bot_attic/2026-05-04/   # секрет!
>    mv .playwright-mcp ~/shermos_bot_attic/2026-05-04/ 2>/dev/null || true
>    mv smoke_e2e.py ~/shermos_bot_attic/2026-05-04/   # если он автономный а не часть pytest
>    ```
> 2. Перезапустить worker и webhook по очереди, проверить logs:
>    ```bash
>    sudo systemctl restart shermos-worker
>    journalctl -u shermos-worker -n 50 --no-pager
>    sudo systemctl restart shermos-webhook
>    journalctl -u shermos-webhook -n 50 --no-pager
>    ```

**Verify:**
- `ssh aws-shermos1-frankfurt 'ls shermos_bot/src/queue/'` → только `worker.py`, `outbox_dispatcher.py`, `__init__.py`
- `ssh aws-shermos1-frankfurt 'ls shermos_bot/*.diff shermos_bot/.env.backup* 2>&1'` → No such file
- В `journalctl` нет новых ошибок после рестарта.

**Gate 0.3:** репо на сервере чистый, прод работает.

---

## Phase 1 — Починить routing двух WhatsApp-номеров

**Зачем:** сейчас `whatsapp_manager_not_allowlisted` спамит в лог каждую секунду, потому что любое входящее сообщение (от клиента) на менеджерский номер помечается `bot_type=manager` и блокируется. Это видно в логах. Архитектурно нужно: «номер 1 — клиентский поток, номер 2 — менеджерский поток», и роль определяется НОМЕРОМ ПОЛУЧАТЕЛЯ (т.е. через какой бридж пришло), а не флагом из payload.

> **Статус Phase 1 (на 2026-05-04 после ревью коммита `83db7c9`):**
> Подшаги **1.1, 1.2 (код), 1.4.1 (silent except), 1.4.3 (/healthz), 1.4.4** — закрыты. Подшаги **1.2 (deploy), 1.3 (схема), 1.4.1 (outbox), 1.4.2, 1.4.3 (CMS Status)** — открыты, **переехали в раздел 1.5 с уточнёнными промптами**. Раздел 1.5 — это and what an agent must implement now. Разделы 1.1–1.4 ниже оставлены для контекста и проверки/копирайтинга, но агент НЕ должен по ним повторно работать — только читать как историю.

### 1.1 Привести два инстанса бриджа к разному `bridge_role` — ✅ DONE (commit `83db7c9`)

**Контекст:** на сервере уже есть `shermos-wa-client.service` и `shermos-wa-manager.service` (видно в systemd). Нужно убедиться, что:
- `shermos-wa-client` слушает клиентский WhatsApp-номер и шлёт payload с `bridge_role: "client"`.
- `shermos-wa-manager` — менеджерский, `bridge_role: "manager"`.
- У каждого свой `auth-state-redis` namespace (чтобы Baileys-сессии не пересекались).
- У каждого свой `bridge_shared_secret` (или один общий, но это hardcoded в `whatsapp_ingress.is_bridge_secret_valid`).

**agent prompt:**
> 1. Прочитать `whatsapp-bridge/src/index.ts` и понять, как читается роль из env (вероятно `BRIDGE_ROLE`).
> 2. Прочитать systemd-юниты `scripts/systemd/shermos-wa-client.service` и `shermos-wa-manager.service`. Удостовериться, что они запускают бридж с разными env: `BRIDGE_ROLE=client` vs `BRIDGE_ROLE=manager`, разными `WHATSAPP_NUMBER`, разными портами/Redis-префиксами.
> 3. Прочитать на сервере env-файлы (`/etc/default/...` или Environment в юните) — НЕ коммитить, только зафиксировать.
> 4. Если env-разделение НЕ настроено — добавить и описать в `whatsapp-bridge/OPERATOR.md`.

**Verify:**
- `ssh aws-shermos1-frankfurt 'systemctl cat shermos-wa-client | grep -E "Environment|ExecStart"'` показывает явное `BRIDGE_ROLE=client`.
- То же для `shermos-wa-manager` с `BRIDGE_ROLE=manager`.
- В Redis: `redis-cli KEYS 'wa:client:*' | head` и `wa:manager:*` существуют как раздельные неймспейсы.

### 1.2 Исправить семантику allowlist — ⚠️ КОД ✅, ДЕПЛОЙ ❌ (см. 1.5.1)

**Файл:** `src/bot/whatsapp_ingress.py:128-133`.

**Текущая (поломанная) логика:**
```python
if bot_type == "manager" and not _is_allowed_manager_phone(phone_e164):
    raise PermissionError("manager WhatsApp number is not allowlisted")
```
Здесь `phone_e164` — телефон **отправителя**. Если клиент пишет на менеджерский номер, его телефона нет в allowlist → ошибка → лог-флуд.

**Правильная логика:**
- `bridge_role` определяет, на КАКОЙ номер пришло сообщение (manager/client). Это просто канал.
- `bot_type` (внутреннее понятие очереди) = `manager` ТОЛЬКО если отправитель находится в allowlist (т.е. это сотрудник, общающийся через WhatsApp). Иначе сообщение — клиентское, идёт в `queue:incoming` независимо от того, на какой номер пришло.

**agent prompt:**
> Заменить блок `whatsapp_ingress.py:127-134`:
> ```python
> bot_type = _bridge_role(payload)
> if bot_type == "manager" and not _is_allowed_manager_phone(phone_e164):
>     logger.warning(...)
>     raise PermissionError(...)
> queue_name = "queue:manager" if bot_type == "manager" else "queue:incoming"
> ```
> на:
> ```python
> bridge_role = _bridge_role(payload)
> sender_is_staff = _is_allowed_manager_phone(phone_e164)
> # bridge_role фиксирует канал (на какой номер пришло), bot_type — роль отправителя.
> # Менеджерская очередь — только если отправитель в allowlist.
> bot_type = "manager" if sender_is_staff else "client"
> queue_name = "queue:manager" if bot_type == "manager" else "queue:incoming"
> if bridge_role == "manager" and not sender_is_staff:
>     # клиент написал на менеджерский номер — это нормально, просто идёт в клиентскую очередь
>     logger.info("whatsapp_client_on_manager_number", extra={"phone_e164": phone_e164})
> ```
> Также убедиться, что в `Job` payload передаётся `bridge_role` отдельно от `bot_type` (новое поле модели). Если в `models.py` нет — добавить опциональное поле.
>
> Тесты:
> - Обновить `tests/test_whatsapp_ingress.py`: добавить кейс «отправитель НЕ в allowlist + bridge_role=manager → queue:incoming + bot_type=client + лог `whatsapp_client_on_manager_number`».
> - Старый кейс «отправитель в allowlist + bridge_role=manager → queue:manager» оставить.
> - Добавить кейс «отправитель в allowlist + bridge_role=client → queue:manager» (сотрудник пишет с клиентского номера — это редкий, но валидный сценарий: тоже идёт в менеджерскую очередь).

**Verify (Я выполняю):**
- Локально: `cd /tmp/shermos_actual && python -m pytest tests/test_whatsapp_ingress.py -v` → все тесты зелёные, в т.ч. новые.
- На сервере после деплоя: в течение 5 минут после рестарта worker — `journalctl -u shermos-worker -n 200 | grep -c whatsapp_manager_not_allowlisted` должно быть **0** (или близко к 0, только реальные нарушения).
- Отправить тестовое сообщение со своего личного WhatsApp (НЕ из allowlist) на оба номера — оба должны получить ответ от LLM-движка (т.е. не молча отброситься).

**Gate 1.2:** лог-флуд прекратился; реальные клиентские сообщения через оба номера обрабатываются.

### 1.3 Документация архитектуры двух ботов — ⚠️ ЧАСТИЧНО (OPERATOR.md ✅, dual-bot doc ❌ — см. 1.5.2)

**agent prompt:**
> Обновить `whatsapp-bridge/OPERATOR.md` (или создать `docs/WHATSAPP_DUAL_BOT.md`):
> - Какие два номера, какие env у каждого systemd-юнита, какие порты.
> - Как сообщения маршрутизуются (схема: WhatsApp → Bridge_X → POST /api/whatsapp/inbound → enqueue_whatsapp_inbound → bot_type detection → queue).
> - Что значит allowlist (только сотрудники), как добавлять новый номер сотрудника.
> - Сценарии: «клиент пишет на любой из двух», «менеджер пишет с личного на любой из двух».

**Gate 1.3:** документ есть, в нём есть Mermaid-схема ИЛИ ASCII-схема потока.

### 1.4 Менеджерский WhatsApp-бот: входящие + подтверждение замера — ⚠️ ЧАСТИЧНО

> Из 4 подшагов закрыты: **1.4.3 /healthz** ✅, **1.4.4 sanity-log** ✅. Открыты: **1.4.1 outbox routing** ❌ (переехало в 1.5.3), **1.4.2 native buttons** ❌ (1.5.4), **1.4.3 CMS Status page** ❌ (1.5.5). Silent-except → log внутри 1.4.1 ✅.

**Зачем:** жалоба «у мастера в WhatsApp ничего не приходит, нет кнопок подтвердить время замера». Расследование:
- Входящие сообщения мастера попадают в фильтр allowlist (часть 1.2 это решает: после правки сообщения от номера сотрудника идут в `queue:manager`, остальные — в `queue:incoming`).
- Исходящие уведомления о новом замере: `actions_applier.py:328-346` шлёт сообщение + `manager_measurement_keyboard(m_id)`. На WhatsApp клавиатура конвертится в текст «👉 Подтвердить: /meas_confirm:42» через `_reply_markup_to_payload`.
- **Главная дыра:** в `actions_applier.py:256-257, 364, 369` стоит `try/except Exception: continue` — если бридж не отвечает (401, connection refused, timeout), уведомление **молча теряется без лог-записи**. Поэтому мастер «не получает». В `worker.py:670-705` (auto-confirm loop) такой же паттерн, но там хотя бы есть `logger.warning("manager_whatsapp_auto_confirm_notify_failed")` — здесь нет.
- Дополнительно: у Baileys-бриджа в логах регулярные «Connection Terminated» и «init queries failed». Нет healthcheck/observability, чтобы оператор видел, что бридж висит.

**1.4.1 — выкинуть silent except, добавить outbox**

**agent prompt:**
> 1. В `src/llm/actions_applier.py` все блоки вида:
>    ```python
>    for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
>        try:
>            await send_and_record(...)
>        except Exception:
>            continue
>    ```
>    заменить на:
>    ```python
>    for manager_phone in settings.manager_whatsapp_numbers_list:
>        try:
>            await send_and_record(...)
>        except Exception as exc:
>            logger.error(
>                "manager_whatsapp_notify_failed",
>                extra={"phone": manager_phone, "kind": "new_measurement", "error": str(exc)},
>            )
>    ```
>    То же для всех аналогичных try/except continue (строки 256-257, 364, 369 — найти все через `grep -n "except Exception:" src/llm/actions_applier.py`).
>
> 2. **Не отправлять напрямую** — записывать в outbox через `postgres.insert_outbound_event(channel='whatsapp', ...)`. Outbox dispatcher уже это умеет (после фикса 2.2 он будет уметь различать permanent ошибки). Тогда падение бриджа не теряет уведомление: оно подождёт в БД и доедет, когда бридж поднимется. Соответственно, `actions_applier` НЕ зовёт `send_and_record` напрямую для менеджеров — пишет в outbox.

**Verify:**
- Локально: симулировать падение бриджа (`manager_whatsapp_bridge_url=http://localhost:1`), создать тестовый замер через `actions_applier` — проверить, что в `outbound_events` появилась строка со `status='pending'`. Поднять бридж (мок) — outbox dispatcher должен переотправить.
- На сервере после деплоя: убить бридж (`systemctl stop shermos-wa-manager`), создать замер; в `outbound_events WHERE channel='whatsapp' AND status='pending'` появилась строка. Запустить бридж — статус становится `sent`.

**1.4.2 — нативные WhatsApp interactive buttons вместо текста**

**Контекст:** Baileys поддерживает interactive messages (`buttonsMessage`, `listMessage`). Сейчас бридж (`whatsapp-bridge/src/routes/send.ts`) принимает только `{text, media}`. Нужно расширить.

**agent prompt:**
> 1. В `whatsapp-bridge/src/routes/send.ts` принять опциональное поле `buttons: [{id, title}]`. Если оно есть, отправлять Baileys `buttonsMessage` (или `listMessage` для >3 кнопок), не plain text. См. https://baileys.whiskeysockets.io/.
> 2. В `src/bot/whatsapp_sender.py:_reply_markup_to_payload`: вместо склейки в текст возвращать `{"text": ..., "buttons": [...]}`.
> 3. Поскольку не все WhatsApp-клиенты надёжно показывают buttonsMessage (из-за антиспам-ограничений Meta), оставить fallback: если `buttons` пришли, но Baileys вернул ошибку «button not supported», бридж шлёт plain text. Логировать `whatsapp_button_fallback`.
> 4. Тест в `whatsapp-bridge/tests/send.test.ts`: payload с `buttons` → запрашивает Baileys с `buttonsMessage`. Без `buttons` → старый текст.
> 5. Тест в `tests/test_whatsapp_sender.py` (новый): передаём `reply_markup` с inline_keyboard → в payload улетает `buttons`, не текст с «👉».

**Verify:**
- Тесты зелёные.
- Ручной тест: бридж получает payload с buttons → реальный WhatsApp-клиент показывает кнопки. (Может потребовать WhatsApp Business аккаунта — если нет, оставить как Soft-fallback и зафиксировать в OPERATOR.md.)

**1.4.3 — наблюдаемость менеджерского канала**

**agent prompt:**
> 1. В `whatsapp-bridge` добавить эндпоинт `/healthz` — возвращает `{connected: bool, last_message_at: iso, reconnect_attempts: N}`.
> 2. В `src/api/routes_settings.py` (или новый `routes_health.py`): эндпоинт `GET /api/health/bridges` который опрашивает `whatsapp_bridge_url/healthz` и `manager_whatsapp_bridge_url/healthz`, возвращает агрегированный статус. Доступен с auth.
> 3. CMS в Mini App страница «Status» показывает: для каждого бриджа — connected/disconnected, last_message_at, count pending в outbox.

**Verify:**
- `curl localhost:3001/healthz` и `localhost:3002/healthz` возвращают JSON.
- В CMS на странице Status видно, какой бридж лежит.

**1.4.4 — sanity-check конфига**

**agent prompt:**
> При старте `run_worker.py` / `run_api.py` залогировать (один раз, на INFO):
> - `manager_chat_ids_list` (Telegram menager IDs)
> - `manager_whatsapp_numbers_list` (e164 списком, маска кроме последних 4 цифр)
> - `manager_whatsapp_bridge_url` (без сектерта)
> - Если оба списка пустые — `logger.warning("no_manager_channels_configured")`. Сейчас если `MANAGER_CHAT_IDS=` пуст и `MANAGER_WHATSAPP_NUMBERS=` пуст, мастер вообще не получит ничего, и нигде об этом не сказано.

**Verify:** один раз перезапустить сервис → в логе видно, в какие каналы пойдут уведомления.

### 1.5 Доделка Phase 1 (по результатам ревью коммита `83db7c9`)

**Контекст:** коммит `83db7c9 fix(phase1): fix WA routing, add healthz, log manager config, fix silent excepts` закрыл часть Phase 1, но не всё. Этот раздел добавлен после ревью.

| Шаг | Сделано | Что осталось |
|---|---|---|
| 1.1 Раздельные роли бриджей | ✅ | — |
| 1.2 Allowlist semantics | ✅ в коде | **рестарт `shermos-api`** + проверка лог-флуда (см. 1.5.1) |
| 1.3 Документация WHATSAPP_DUAL_BOT | ⚠️ OPERATOR.md обновлён | схема/диаграмма потока (см. 1.5.2) |
| 1.4.1 Silent except → log | ✅ | **routing менеджерских уведомлений через outbox** (см. 1.5.3) |
| 1.4.2 Native WA buttons | ❌ | целиком (см. 1.5.4) |
| 1.4.3 /healthz | ✅ | **CMS Status page** (см. 1.5.5) |
| 1.4.4 Sanity log | ✅ | — |

**1.5.1 — Рестарт shermos-api и проверка allowlist-фикса**

**agent prompt:**
> 1. На сервере: `sudo systemctl restart shermos-api && sleep 5 && systemctl is-active shermos-api`.
> 2. Подождать 10 минут, на которые WhatsApp успеет нагнать обычный поток сообщений.
> 3. Проверить:
>    ```
>    journalctl -u shermos-api --since "10 min ago" | grep -c whatsapp_manager_not_allowlisted
>    journalctl -u shermos-api --since "10 min ago" | grep -c whatsapp_client_on_manager_number
>    journalctl -u shermos-api --since "10 min ago" | grep -c whatsapp_inbound_queued
>    ```
>    Ожидание: первая строка = 0, вторая и третья > 0.
> 4. Если первая != 0 — там есть РЕАЛЬНЫЕ нарушители (попытки от номеров, которые мы хотим блокировать). Прочитать payload'ы — если это легитимные клиенты — баг. Если правда мусор — оставить.

**Verify:** см. метрики выше.

**1.5.2 — Документ архитектуры двух ботов**

**agent prompt:**
> Создать `docs/WHATSAPP_DUAL_BOT.md` с:
> - ASCII-схемой потока (WhatsApp → Bridge_X → POST /api/whatsapp/inbound → enqueue_whatsapp_inbound → bot_type detection → queue:incoming/queue:manager).
> - Таблицей: какой бридж на каком порту, какой `BRIDGE_ROLE`, какой Redis-неймспейс.
> - Семантикой allowlist: «список = сотрудники; не сотрудник = клиент, идёт в queue:incoming независимо от того, на какой номер пришло».
> - 4 сценариями: клиент→client_num, клиент→manager_num, сотрудник→client_num, сотрудник→manager_num. Для каждого — итоговая очередь и ожидаемый ответ.

**Verify:** документ существует, схему я могу прочитать.

**1.5.3 — Менеджерские уведомления через outbox**

**Зачем:** сейчас `actions_applier.py` после правки 1.4.1 хотя бы логирует ошибки, но если бридж в дауне — уведомление о замере **теряется навсегда**. Гарантия доставки = outbox + dispatcher.

**agent prompt:**
> 1. В `src/llm/actions_applier.py` все блоки прямой отправки менеджерам (по chat_id и phone) заменить на `postgres.insert_outbound_event(channel="telegram"|"whatsapp", chat_id=..., reply_text=..., reply_markup=..., bot_type="manager")`. Outbox dispatcher сам потом отправит.
> 2. **Важно:** outbox таблица `outbound_events` должна уметь хранить `external_chat_id` (для WhatsApp — это `phone@s.whatsapp.net`). Проверить миграцию 019 — поддерживает ли она это? Если нет — добавить миграцию 022 с колонкой `external_chat_id TEXT`.
> 3. То же самое в `src/queue/worker.py:670-705` (auto-confirm loop) — заменить прямые отправки менеджерам на outbox.
> 4. Тест: симулировать падение бриджа (мок выкидывает ConnectionError при `_post_json`), создать замер через `apply_actions` — проверить, что в `outbound_events` 2 записи (для chat_id'ов и phone'ов) со статусом `pending`. После «поднятия» бриджа dispatcher отправляет.

**Verify:**
- Локальный тест `tests/test_actions_applier.py` зелёный для нового кейса.
- На сервере: `psql -c "SELECT count(*) FROM outbound_events WHERE bot_type='manager' AND created_at > now() - interval '1 hour'"` показывает > 0 после реального замера.

**1.5.4 — Native WhatsApp buttons (interactive messages)**

**agent prompt:**
> 1. `whatsapp-bridge/src/routes/send.ts`: принять опциональное `buttons: [{id:string, title:string}]` (до 3) или `list: {sections: [...]}` для большего числа. Если пришло — отправить через Baileys `sendMessage(jid, { text, buttons, ... })` или `templateButtons`.
> 2. На уровне типов: подсмотреть актуальный API в `@whiskeysockets/baileys` через `npx tsc --noEmit` и доку https://baileys.whiskeysockets.io/.
> 3. Если Baileys возвращает ошибку «buttons not supported» / «templateButtons deprecated» — fallback на text как раньше, лог `whatsapp_button_fallback`.
> 4. В `src/bot/whatsapp_sender.py:_reply_markup_to_payload` возвращать `{"text": ..., "buttons": [{"id": cb_data, "title": _button_title(text)}]}` для inline_keyboard с callback_data. URL-кнопки оставить как fallback в текст.
> 5. Тесты:
>    - `whatsapp-bridge/tests/send.test.ts`: payload с buttons → Baileys.sendMessage вызван с `{ buttons: ... }`.
>    - `tests/test_whatsapp_sender.py`: reply_markup → payload содержит buttons (а не только текст с «👉»).

**Verify:**
- Тесты зелёные.
- Ручной тест: создать замер от тестового клиента → менеджер на WhatsApp получает сообщение **с кнопками**. Если получает текст с «👉 Подтвердить: /meas_confirm:N» — fallback сработал, фиксируем причину в OPERATOR.md.

**1.5.5 — CMS Status page**

**agent prompt:**
> 1. В `src/api/` создать `routes_health.py`:
>    ```python
>    @router.get("/api/health/bridges")
>    async def health_bridges(...) -> dict:
>        # GET healthz обоих бриджей (settings.whatsapp_bridge_url, settings.manager_whatsapp_bridge_url)
>        # Параллельно через asyncio.gather с таймаутом 3 сек
>        # Вернуть {"client": {connected, last_message_at, reconnect_attempts}, "manager": {...}}
>    ```
>    Защитить через JWT (`require_auth`).
> 2. `src/api/app.py`: подключить router.
> 3. В `mini-app/src/pages/` создать `Status.tsx` с таблицей: канал | connected | last_message_at | reconnect_attempts | pending в outbox.
> 4. Тест: `tests/test_routes_health.py` — мокнуть aiohttp на `/healthz`, ожидать корректную агрегацию.

**Verify:** в Mini App открыть Status, оба бриджа зелёные. Убить wa-client → через 5 секунд страница показывает disconnected.

**Gate Phase 1.4:**
- Локально: тест «бридж в дауне → создаём замер → запись в outbound_events pending → поднимаем бридж → отправлено».
- На сервере: создать замер через клиента (вручную через бот), мастер получает уведомление в WhatsApp в течение 30 секунд. Мастер отвечает `/meas_confirm:N` (или нажимает кнопку, если 1.4.2 сработал) — статус замера в БД меняется на `confirmed`.
- В CMS Status видно: оба бриджа connected.

---

## Phase 2 — Carry-over баги из аудита (10 пунктов)

Идём по таблице из последнего сообщения, по одному пункту за коммит. Все правки идут в новую ветку `fix/audit-2026-05-04` от `prod-snapshot-2026-05-04`.

### 2.1 `parse_slot_proposal` падает на «2.50 м» — `src/engine/measurement_service.py:347`

**agent prompt:**
> 1. Сузить регекс на dot-формат: вместо `\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b` использовать `\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b` (требовать год обязательно для dot-формата). Это устранит ловлю `"2.50"`.
> 2. Дополнительно обернуть `datetime(year, month, day, tzinfo=tz)` в try/except ValueError → return None.
> 3. Тесты в `tests/test_measurement_service.py`:
>    - `parse_slot_proposal("2.50 м замер", tz) is None`
>    - `parse_slot_proposal("1500.50 руб", tz) is None`
>    - `parse_slot_proposal("приду 13.05.2026 в 14:00", tz) == ("2026-05-13", "14:00")` (с годом)
>    - `parse_slot_proposal("13.05 в 14:00", tz) is None` (без года — dot-формат теперь требует год; альтернативно: добавить отдельный regex с проверкой границ)
>    - `parse_slot_proposal("завтра в 11:00", tz) == (date.today() + 1, "11:00")` (старое поведение работает)

**Verify:**
- `python -m pytest tests/test_measurement_service.py -v` все зелёные.
- На сервере проверить логи в течение 24 ч: `journalctl -u shermos-worker --since "24h ago" | grep -c "day is out of range"` → 0.

### 2.2 Outbox не отличает permanent от transient ошибок — `src/queue/outbox_dispatcher.py:67` + `src/db/postgres.py:282`

**agent prompt:**
> 1. В `src/bot/telegram_sender.py`: при получении 403/400 от Telegram бросать кастомное `PermanentSendError(error_code, description)` вместо общего исключения. Аналогично для WhatsApp 4xx-ошибок (если бридж их прокидывает).
> 2. В `src/queue/outbox_dispatcher.py:67`:
>    ```python
>    except PermanentSendError as exc:
>        await postgres.mark_outbound_dead(pg_pool, int(event["id"]), str(exc))
>        logger.info("outbox_send_permanent_fail", ...)
>    except Exception as exc:
>        await postgres.mark_outbound_failed(pg_pool, int(event["id"]), str(exc))
>        logger.warning("outbox_send_failed", ...)
>    ```
> 3. В `src/db/postgres.py`: добавить `mark_outbound_dead(pool, event_id, error)` — сразу `status='failed'`, без `attempts+1`. Опционально новая миграция: добавить колонку `outbound_events.dead_reason TEXT` для диагностики.
> 4. В `mark_outbound_failed` сохранять историю: `error_message=COALESCE(error_message,'') || E'\n[N] ' || $2` (или просто хранить последние N через jsonb-array).
> 5. Тесты в `tests/test_outbox_dispatcher.py`:
>    - 403 → `mark_outbound_dead` вызван 1 раз, `mark_outbound_failed` НЕ вызван.
>    - timeout/500 → `mark_outbound_failed` вызван, attempts++.
>    - после 5 transient → status='failed'.
>    - после 1 permanent → status='failed', attempts=1.

**Verify:**
- Тесты зелёные.
- На сервере: после деплоя за 1 час `journalctl -u shermos-worker | grep "bot was blocked" | wc -l` ≤ количеству заблокировавших пользователей × 1 (а не × 5).

### 2.3 `auth_date == 0` пропускает проверку срока — `src/api/auth.py:79-80`

**agent prompt:**
> 1. Заменить:
>    ```python
>    auth_date = int(data.get("auth_date", "0") or "0")
>    if auth_date and time.time() - auth_date > max_age_seconds:
>        raise ValueError("initData expired")
>    ```
>    на:
>    ```python
>    try:
>        auth_date = int(data.get("auth_date", "0") or "0")
>    except (TypeError, ValueError):
>        auth_date = 0
>    if auth_date <= 0:
>        raise ValueError("Missing or invalid auth_date")
>    if time.time() - auth_date > max_age_seconds:
>        raise ValueError("initData expired")
>    ```
> 2. Тесты в `tests/test_api_auth.py`:
>    - initData без `auth_date` → 401.
>    - initData с `auth_date=0` → 401.
>    - initData с `auth_date` вчерашним (>86400) → 401.
>    - initData с `auth_date=now()` → 200.

**Verify:** тесты зелёные.

### 2.4 Webhook secret не constant-time — `src/bot/webhook.py:55`

**agent prompt:**
> Заменить `if incoming_secret != secret_token:` на `if not hmac.compare_digest(incoming_secret, secret_token):`. Импортировать `hmac` если нет. Тест в `tests/test_webhook.py`: запрос с пустым/неправильным `X-Telegram-Bot-Api-Secret-Token` → 200 OK (как сейчас, чтобы не палить наличие endpoint), но job НЕ ставится в очередь.

**Verify:** тест зелёный.

### 2.5 Gemini health check ставит healthy на странном выводе — `src/llm/health_check.py:33`

**agent prompt:**
> Заменить:
> ```python
> if "ok" in result.lower():
>     ...
>     _gemini_healthy = True
> else:
>     logger.warning("gemini_health_unexpected_output", ...)
>     _gemini_healthy = True
> ```
> на:
> ```python
> if "ok" in result.lower():
>     if not _gemini_healthy:
>         logger.info("gemini_health_recovered")
>     _gemini_healthy = True
> else:
>     logger.warning("gemini_health_unexpected_output", extra={"output": result[:200]})
>     _gemini_healthy = False
> ```
> Также увеличить `_CHECK_INTERVAL` с 600 до 1800 (30 мин) — текущая частота сжигает квоту впустую (12 платных вызовов / час). Сделать `interval` параметром env `gemini_health_check_seconds` в settings.
>
> Тесты: `tests/test_llm_actions.py` или новый `tests/test_health_check.py` — мокнуть `call_llm`, проверить:
> - `result="ok"` → healthy=True.
> - `result="random garbage"` → healthy=False, warning logged.
> - `call_llm` бросает TimeoutError → healthy=False, critical logged.

**Verify:** тесты зелёные. На сервере после деплоя: за 24 ч количество `gemini_health_check_failed` лог-записей не вырастет (как сейчас оно ~1/сутки), при этом `llm_call_finished` для health check теперь ~ 48 раз/сутки, а не 144.

### 2.6 Gallery upload без стриминга и pixel-bomb защиты — `src/api/routes_gallery.py:141-149`

**agent prompt:**
> 1. До чтения файла проверить `file.size` (UploadFile его экспонирует) или `Content-Length` заголовок. Если > `gallery_photo_max_bytes` — сразу 413, не читая тело.
> 2. Сразу после `Image.open(io.BytesIO(data))` поставить `Image.MAX_IMAGE_PIXELS = 50_000_000` (модульно, в начале файла или в config) — иначе DecompressionBombError на огромных PNG.
> 3. Проверять `file.content_type` против allow-list `{"image/jpeg", "image/png", "image/webp"}` ДО открытия PIL.
> 4. Не делать `Image.open` дважды (`img.verify()` ломает дескриптор) — открыть один раз, проверить format и size, и сразу записать оригинальный `data` на диск.
> 5. Тесты в `tests/test_gallery_api.py`:
>    - upload файл размером > max → 413.
>    - upload текстового файла с расширением .jpg → 400.
>    - upload pixel bomb (PNG 50000×50000) → 400.
>    - upload валидного JPG → 200.

**Verify:** тесты зелёные. Локально проверить с большим файлом: `dd if=/dev/zero bs=1M count=100 of=/tmp/big.jpg && curl -F file=@/tmp/big.jpg ...` → 413.

### 2.7 Gallery delete: orphan'ы при ошибке unlink — `src/api/routes_gallery.py:99-119, 178-190`

**agent prompt:**
> Поменять порядок:
> 1. Сначала отмечать `gallery_photos.is_deleted=true` (мягкое удаление в БД, ALTER TABLE добавит колонку — миграция 022).
> 2. Удалять файл с диска.
> 3. Если файл удалился — финальный `DELETE FROM gallery_photos`.
> 4. Если файл НЕ удалился — оставить `is_deleted=true` и логировать. Cron / отдельная задача потом подберёт orphan'ов.
>
> Если миграция 022 — слишком тяжело, минимально: попытаться unlink первым; если упало — return 500 без DELETE из БД, чтобы не было orphan'ов.

**Verify:** unit-тест с замоканым unlink, который бросает OSError, → DB не удалила, ответ 500.

### 2.8 Нет SIGTERM-хендлеров в Python-демонах — `run_worker.py`, `run_webhook.py`

**agent prompt:**
> 1. В `run_worker.py` и `run_api.py`/`run_webhook.py`: установить `loop.add_signal_handler(SIGTERM, ...)` который ставит `asyncio.Event` shutdown_event; основной цикл проверяет event и аккуратно закрывает pg_pool, redis, останавливает sender'ов.
> 2. В docker-compose: убедиться, что `stop_signal: SIGTERM` и `stop_grace_period: 30s`.
> 3. В systemd-юнитах: `KillSignal=SIGTERM`, `TimeoutStopSec=30`.

**Verify:** на сервере: `systemctl restart shermos-worker` отрабатывает быстро (< 5 с) и в `journalctl` видны лог-записи `worker_shutdown_initiated` и `worker_shutdown_complete`, без force-kill.

### 2.9 Удалить мёртвый `src/render/validators.py`

**agent prompt:**
> 1. `grep -r "from src.render.validators\|render.validators\|validate_partition_params" src/ tests/` — убедиться, что нет импортов.
> 2. Если нет — удалить файл.
> 3. Если есть — починить импорты (`from utils.config_manager` → `from src.utils.config_manager`) и подтвердить, что функция вызывается.

**Verify:** `pytest -q` без ошибок import; код не используется → файл удалён.

### 2.10 `mark_outbound_failed` затирает первичную ошибку — `src/db/postgres.py:282`

Слито в 2.2.

---

## Phase 3 — Сайт мастера (CMS) как замена Mini App

**Где гоняется:** код пишется и unit-тестируется на macbook'е. Production-проверка (CORS, реальный OTP через WhatsApp, JWT lifecycle, CSRF, multi-entry build) — **только на сервере** через `ssh aws-shermos1-frankfurt`. Каждый шаг ниже подразумевает 6-фазный цикл из W-5.

**Контекст:** уже есть `src/api/routes_auth.py` с OTP+JWT, mini-app фронтенд в `mini-app/` на Vite. Цель: запустить отдельный домен `cms.shermos.<…>` (или sub-path), на котором мастер логинится через WhatsApp-OTP, и фронт работает в браузере вне Telegram.

### 3.1 Закрыть CORS

**agent prompt:**
> 1. В `src/config.py` добавить `cors_allowed_origins: list[str]` (через env `CORS_ALLOWED_ORIGINS`, comma-separated).
> 2. В `src/api/app.py:42`:
>    ```python
>    app.add_middleware(
>        CORSMiddleware,
>        allow_origins=settings.cors_allowed_origins or [],
>        allow_credentials=True,   # нужно для refresh-cookie
>        allow_methods=["GET", "POST", "PATCH", "DELETE"],
>        allow_headers=["Authorization", "X-Telegram-Init-Data", "X-CMS-Admin-Token", "Content-Type"],
>    )
>    ```
> 3. На сервере в env: `CORS_ALLOWED_ORIGINS=https://cms.shermos.example,https://t.me`. Конкретные домены подтвердить с владельцем.

**Verify:**
- Локально: `curl -H "Origin: https://evil.com" -i $API_HOST/api/orders` → нет `Access-Control-Allow-Origin: *`, либо отсутствует ACAO заголовок (и CORS-preflight 400).
- Из Mini App / CMS — продолжает работать.

### 3.2 Rate-limit на OTP verify

**agent prompt:**
> 1. Добавить мидлварь `slowapi` или собственный (через Redis INCR с TTL): `/api/auth/otp/verify` лимитится 5 попытками в минуту по `phone` + 20 в минуту по IP.
> 2. На превышение — 429 с `Retry-After`.
> 3. Тест `tests/test_routes_auth.py`: 10 кривых попыток подряд за 1 секунду → последние 5 получают 429.

**Verify:** тест зелёный.

### 3.3 CSRF на /api/auth/refresh

**Текущая дыра:** refresh-cookie с `samesite="none"` + CORS теперь с `allow_credentials=True` означает, что любой разрешённый origin может вызывать refresh. Хорошо если origin'ов мало; **ещё** нужно double-submit CSRF token.

**agent prompt:**
> 1. При выдаче refresh-cookie в `routes_auth.py:123` дополнительно ставить cookie `csrf_token` (НЕ httpOnly, читаемый JS): `secrets.token_urlsafe(32)`.
> 2. В endpoint `/api/auth/refresh` требовать заголовок `X-CSRF-Token` равный кукe `csrf_token` (через `hmac.compare_digest`).
> 3. Frontend (`mini-app/src/api/client.ts`): добавить чтение `csrf_token` из cookie и проброс в заголовок.
> 4. Тест: запрос на refresh без X-CSRF-Token → 403; правильный → 200.

**Verify:** тест + ручная проверка из браузера.

### 3.4 Раздельные сборки фронтенда: Mini App (Telegram) и CMS (web)

**agent prompt:**
> Изучить `mini-app/`: там App.tsx, страницы, общий API client. Цель — одна кодовая база, две точки входа:
> 1. `mini-app/index.html` — для Telegram (использует `@twa-dev/sdk`, авторизуется через initData).
> 2. `mini-app/cms.html` — для браузера мастера (никакого Telegram SDK, авторизация через JWT после OTP).
>
> В `mini-app/src/auth.ts` (новый файл): функция `getAuthHeaders()` возвращает либо `X-Telegram-Init-Data`, либо `Authorization: Bearer ...` в зависимости от detect (наличие `window.Telegram.WebApp.initData`).
>
> В `vite.config.ts` сделать multi-entry: `build.rollupOptions.input = { mini: 'index.html', cms: 'cms.html' }`.
>
> Добавить в FastAPI отдельный мопший `mini-app/dist/cms.html` под путь `/cms` через StaticFiles.
>
> Логин-флоу для CMS:
> - `/cms/login` — форма «введите телефон → получаете OTP в WhatsApp → введите код».
> - После успешного `/api/auth/otp/verify` access-токен в localStorage, refresh — в HttpOnly cookie.
> - Все API-запросы шлют `Authorization: Bearer <access>`.

**Verify:**
- `npm run build` в `mini-app/` создаёт `dist/index.html` и `dist/cms.html`.
- Открыть в браузере `https://cms.shermos.example/cms/login` → форма, OTP уходит в WhatsApp, код принимается, дальше обычный CMS-интерфейс.

### 3.5 OTP — слабые места починить

**agent prompt:**
> 1. Увеличить длину OTP до 8 цифр (10⁸ вариантов вместо 10⁶) — изменить `auth.py:30` `_ for _ in range(6)` → `range(8)`. Обновить тест.
> 2. Усилить rate-limit на /verify (см. 3.2) — после 5 неверных попыток для одного телефона на 1 час блокировать verify.
> 3. На /send уже есть лимит «1 в минуту, N в час» — оставить, но добавить лимит по IP.

**Verify:** тесты зелёные.

---

## Phase 4 — Тестовое покрытие (фундамент)

**Зачем:** сейчас 37 тест-файлов, ноль интеграционных с реальной БД. Регрессии в SQL/миграциях/race conditions проходят мимо CI.

**Где гоняется:** интеграционные тесты Phase 4 запускаются **на сервере** (не локально). Локально остаются unit + мок-based. Это вытекает из W-5: Docker нет на ноуте, есть на сервере. Изоляция от продовых данных — через отдельную test-БД (`shermos_test`) и Redis-namespace (`test:*`).

### 4.1 Серверные интеграционные фикстуры (Postgres + Redis)

Этот шаг — фундамент для 4.2-4.4. После него все три следующих шага умеют гонять реальные SQL/Redis-операции на сервере.

**Что нужно:**

1. **Test-БД на сервере.** В контейнере `shermos_bot_postgres_1` создать БД `shermos_test`, владельца оставить тем же. Никаких изменений прод-БД `shermos_bot`. БД создаётся один раз и держится — заново мигрируется на каждый прогон.

2. **Test Redis namespace.** Тот же `shermos_bot_redis_1`, но все ключи через префикс `test:` (через `RedisClient(... key_prefix="test:")` — добавить опциональный параметр в RedisClient, если ещё нет). На каждый тестовый прогон — `FLUSHDB` против test-namespace (через `SCAN test:* | DEL`, прод-ключи не трогаем).

3. **Pytest fixtures `tests/conftest.py`:**
   - `pg_pool_integration` (session scope): подключается к `shermos_test` БД на сервере, прогоняет все `migrations/*.sql` через существующий `postgres.run_migrations`, отдаёт asyncpg pool. На teardown — TRUNCATE всех таблиц (или просто оставить — следующая сессия сама перепишет).
   - `redis_client_integration` (session scope): подключается к `shermos_bot_redis_1` с префиксом `test:`. На teardown — DEL всех `test:*` ключей.
   - `integration` pytest marker: `@pytest.mark.integration` — тесты, что требуют этих фикстур. По умолчанию `pytest` НЕ запускает их (через `addopts = -m "not integration"` в pytest.ini), запуск явный: `pytest -m integration`.

4. **Connectivity:**
   - Локальный `pytest -m integration` НЕ работает (нет доступа к 127.0.0.1:5432 на сервере). Запуск только через ssh.
   - Удобный wrapper: `scripts/test_integration.sh` который делает `ssh aws-shermos1-frankfurt 'cd shermos_bot && .venv/bin/python -m pytest -m integration -v'`. После git pull на сервере — этот скрипт прогоняет интеграцию.
   - Альтернатива: SSH-туннель `ssh -L 15432:127.0.0.1:5432 aws-shermos1-frankfurt` + env `INTEGRATION_DB_HOST=127.0.0.1 INTEGRATION_DB_PORT=15432`. Сложнее, но позволяет дебажить с macbook'а. Делать только если первый вариант неудобен.

**agent prompt (при выполнении):**
> 1. На macbook'е: добавить в `requirements.txt` или новый `requirements-dev.txt` зависимости `pytest-asyncio>=0.23` (если ещё нет). Реальные клиенты `asyncpg` и `redis` уже в проде. Никакого `testcontainers` — не нужны.
> 2. Расширить `RedisClient.__init__` опциональным `key_prefix: str = ""`; все методы, которые формируют ключи, добавляют префикс. Это нужно и для тестов, и в будущем для multi-tenant. Покрыть юниттестами `test_redis_client.py`.
> 3. Создать `tests/conftest.py` фикстуры:
>    ```python
>    @pytest.fixture(scope="session")
>    async def pg_pool_integration():
>        if not os.getenv("INTEGRATION_DB_DSN"):
>            pytest.skip("INTEGRATION_DB_DSN not set; integration tests run on server only")
>        pool = await asyncpg.create_pool(os.getenv("INTEGRATION_DB_DSN"))
>        await postgres.run_migrations(pool)
>        yield pool
>        await pool.close()
>    ```
>    Аналогично `redis_client_integration` через `INTEGRATION_REDIS_URL`.
> 4. `pytest.ini` или `pyproject.toml` — добавить `markers = ["integration: requires real Postgres/Redis (server only)"]`. И `addopts = "-m 'not integration'"`.
> 5. Создать `scripts/test_integration.sh` — wrapper для серверного запуска. Скрипт:
>    ```bash
>    #!/usr/bin/env bash
>    ssh aws-shermos1-frankfurt 'cd shermos_bot && \
>        INTEGRATION_DB_DSN="postgresql://shermos:${POSTGRES_PASSWORD}@127.0.0.1:5432/shermos_test" \
>        INTEGRATION_REDIS_URL="redis://127.0.0.1:6379/15" \
>        .venv/bin/python -m pytest -m integration -v'
>    ```
>    DB номер 15 в Redis резервируем под тесты (db 0 — прод).
> 6. Один пробный тест `tests/test_integration_smoke.py`:
>    ```python
>    @pytest.mark.integration
>    @pytest.mark.asyncio
>    async def test_pg_pool_can_select(pg_pool_integration):
>        result = await pg_pool_integration.fetchval("SELECT 1")
>        assert result == 1

>    @pytest.mark.integration
>    @pytest.mark.asyncio
>    async def test_redis_set_get(redis_client_integration):
>        await redis_client_integration.client.set("smoke", "ok")
>        assert (await redis_client_integration.client.get("smoke")).decode() == "ok"
>    ```
> 7. На сервере (один раз вручную): `psql -h 127.0.0.1 -U shermos -c "CREATE DATABASE shermos_test"`. Закоммитить шпаргалку в `docs/TEST_DB_SETUP.md`.

**Verify (где):**
- **macbook (шаг 2 из W-5):** `.venv/bin/python -m pytest -q` (без `-m integration`) → 266+ зелёных, integration-маркированные пропускаются.
- **macbook (шаг 4):** `git push`.
- **сервер (шаг 5):** `git pull`.
- **сервер (шаг 6):** `bash scripts/test_integration.sh` → smoke-тесты `test_integration_smoke.py` зелёные. Если БД `shermos_test` ещё нет — создать вручную, прогнать снова.

**Gate Phase 4.1:** smoke-тесты на сервере зелёные; локально полный набор unit-тестов не падает; миграции применяются к чистой `shermos_test` БД без ошибок.

### 4.2 Интеграционный e2e: webhook → worker → outbox → telegram (моки наружу)

**agent prompt:**
> Новый тест `tests/test_e2e_telegram_flow.py` под маркером `@pytest.mark.integration`:
> 1. Использует `pg_pool_integration` + `redis_client_integration` фикстуры (4.1) против `shermos_test` БД на сервере.
> 2. Запускает воркер в отдельной asyncio task (через `asyncio.create_task(run_worker(...))` с моком `TelegramSender`).
> 3. POST на webhook handler (через aiohttp test client) с фейковым update — текст «Здравствуйте».
> 4. Ждёт до 10 сек, что worker обработал и в outbox появилось событие со статусом `sent`.
> 5. Asserts: `pg_pool.fetchrow("SELECT status FROM outbound_events WHERE chat_id=$1", chat_id)` = `'sent'`, `FakeSender.messages` содержит ровно 1 ответ.

**Verify:**
- **macbook (шаг 2):** локально тесты под `integration` маркером пропускаются, остальное должно остаться 266+ зелёных.
- **сервер (шаг 6):** `bash scripts/test_integration.sh tests/test_e2e_telegram_flow.py` — тест зелёный за < 30 секунд.

### 4.3 Аналогично для WhatsApp

`tests/test_e2e_whatsapp_flow.py` под `@pytest.mark.integration`: POST на `/api/whatsapp/inbound` (с правильным `bridge_shared_secret`) → worker → outbox → mock WhatsAppSender. Прогнать оба сценария: клиент на менеджерском номере (ожидаемо: queue:incoming, ответ от LLM); сотрудник в allowlist (queue:manager).

**Verify:** локально пропускается (integration); серверный запуск — `bash scripts/test_integration.sh tests/test_e2e_whatsapp_flow.py`.

### 4.4 Регрессионная матрица клиентских кейсов

**Зачем:** жалоба «убедиться, что в клиентских кейсах всё работает». Сейчас тесты проверяют отдельные функции, а не реальные сценарии. Нужна явная матрица «вход → ожидаемое поведение», где каждый кейс реально гоняется через webhook → worker → outbox → mock sender и/или реальный API.

**Каждый кейс ниже = отдельный тест-функция в `tests/test_e2e_client_cases.py`** поверх инфраструктуры из 4.1. Если кейс падает — это либо баг, либо непокрытый сценарий → правка/доработка.

| # | Кейс | Вход (что шлёт клиент) | Ожидаемое поведение | Где может сломаться |
|---|---|---|---|---|
| C-01 | Холодный старт через Telegram | `/start` | Приветствие + кнопка Mini App | webhook secret, mark_update_received, открытие Mini App |
| C-02 | Холодный старт через WhatsApp | «Привет» с нового номера | Приветствие | whatsapp_ingress, dedup, маршрутизация в queue:incoming |
| C-03 | Сбор параметров (happy path) | «Хочу перегородку 2.5 на 1.8, прозрачное стекло, чёрный профиль» | LLM собирает параметры, в conversation_state появляется patch | actions_parser, prompt_builder, render_requirements |
| C-04 | Дробные размеры с точкой | «ширина 2.50, высота 1.80» | НЕ должно упасть в parse_slot_proposal с «day out of range» | измерительный регекс, фикс 2.1 |
| C-05 | Цена с точкой/запятой | «бюджет 1500.50» | LLM не интерпретирует как дату, ничего не валится | то же |
| C-06 | Голосовое сообщение | OGG voice → AssemblyAI | Транскрипт → как текст идёт в LLM, без эхо в чате | transcribe.py, fix `7ff1625` |
| C-07 | Запрос рендера | «покажите как будет выглядеть» (после сбора параметров) | render_engine генерит PNG, send_photo, цена в caption | render_engine, OOM-защита, gallery_offer_keyboard |
| C-08 | Замер — happy path | После рендера: «давайте на замер завтра в 11:00, я Иван, +77001234567, ул. Х» | schedule_measurement → INSERT в measurements → менеджер получает уведомление + кнопки | schedule_measurement, конфликты слотов, manager_measurement_keyboard |
| C-09 | Замер — конфликт | После C-08, второй клиент: «завтра в 11:15» (внутри окна) | ValueError «уже есть замер рядом» → клиенту понятный текст | check_conflict, error handling |
| C-10 | Замер — воскресенье | «приду в воскресенье» | Отказ либо альтернативное время | calendar_engine, weekday() == 6 |
| C-11 | Замер — менеджер подтвердил (Telegram) | Менеджер жмёт «Подтвердить» в Telegram | measurement.status='confirmed', клиент получает уведомление | _handle_measurement_callback |
| C-12 | Замер — менеджер подтвердил (WhatsApp) | Менеджер пишет `/meas_confirm:N` в WhatsApp | то же | Phase 1.4.2 fix |
| C-13 | Замер — авто-подтверждение | Прошло 15 минут, мастер не отреагировал | _measurement_auto_confirm_loop переводит в confirmed, уведомляет обоих | auto-confirm loop |
| C-14 | Замер — менеджер отклонил | «Отклонить» в Telegram | status='rejected', клиенту сообщение, slot освобождён | update_measurement_status |
| C-15 | Замер — менеджер хочет другое время | Менеджер шлёт «давайте 12.05 в 14:00» в чат | parse_slot_proposal предлагает альтернативу клиенту | _handle_manager_slot_proposal |
| C-16 | Дубликат сообщения (Telegram) | Тот же update_id два раза подряд | Второй раз → return early, без двойной обработки | mark_update_received, fix `7ff1625` |
| C-17 | Дубликат сообщения (WhatsApp) | Тот же external_id два раза | то же | mark_external_update_received |
| C-18 | Заблокировал бота (Telegram) | Бот шлёт ответ → 403 от Telegram | outbox: ОДНА попытка, status=failed, нет retry-спама | fix 2.2 |
| C-19 | Восстановление после падения worker | Worker убит на середине обработки | Job попадает обратно в queue:incoming через _client_loop_recovery, не теряется | dequeue_job_safe, ack_job, processing queue |
| C-20 | LLM таймаут | Gemini не отвечает 60 сек | TimeoutError → клиенту «секунду, мы немного думаем» или fallback, не молчание | call_llm timeout, _gemini_healthy |
| C-21 | LLM вернул мусор | call_llm: `"some random text"` без JSON | actions_parser возвращает пустые actions, клиенту fallback-сообщение | actions_parser strict mode |
| C-22 | Mini App — открытие галереи | Клиент в Mini App жмёт «Готовые работы» → API /api/gallery/works | список с фотками, фильтр по типу/форме | routes_gallery, auth |
| C-23 | Mini App — вход через initData (Telegram) | Telegram WebApp передаёт initData | 200 OK, токен auth_method=telegram | auth.py, fix 2.3 |
| C-24 | CMS — вход через OTP | Сайт мастера шлёт телефон → получает OTP в WhatsApp → вводит код | JWT access + refresh-cookie | routes_auth, Phase 3 |
| C-25 | Лимит OTP | 6 неверных кодов подряд за минуту | 401 + удаление OTP, 7-я попытка → 429 | otp_max_attempts, rate-limit Phase 3.2 |
| C-26 | Длинный диалог | 100 сообщений, conversation_memory растёт | summary не теряет ключевые параметры (height/width/glass) | conversation_memory.merge_memory_summary (риск из аудита) |
| C-27 | Команда /reset (если есть) | Клиент шлёт `/reset` или «начать сначала» | conversation_state очищен | TODO: проверить, есть ли вообще такая команда |
| C-28 | Бот не понял | «погода в Москве» (off-topic) | Вежливый отказ, не пытается рендерить | system_prompt, LLM-guardrails |
| C-29 | Очень дешёвый расчёт | Минимальная конфигурация | price > 0, без отрицательной скидки | pricing_engine, division-by-zero |
| C-30 | Параллельные сообщения от одного клиента | 2 сообщения за 100ms | second job в queue:delayed, обрабатывается через 2-15с, нет race condition | _schedule_locked_client_job |

**agent prompt:**
> Создать `tests/test_e2e_client_cases.py` под маркером `@pytest.mark.integration` поверх фикстур из 4.1 (`pg_pool_integration` + `redis_client_integration`). Реализовать кейсы C-01..C-30 как отдельные `async def test_C01_*` функции. Для LLM-зависимых кейсов (C-03, C-20, C-21, C-26, C-28) мокать `call_llm` соответствующими ответами. Для рендера (C-07) — мокать `render_engine.render_partition` (генерит реальную PNG-заглушку 1×1).
>
> Каждый тест использует:
> - `pg_pool_integration` (реальный Postgres `shermos_test` на сервере)
> - `redis_client_integration` (реальный Redis с префиксом `test:`)
> - `worker_task` (фоновая задача с моком sender'а)
> - `await asyncio.wait_for(condition, timeout=10)` — ждать ожидаемого состояния в БД.
>
> Ожидаемые asserts: состояние БД (status, conversation_state.collected_params, outbound_events), список вызовов `FakeSender.messages` (по тексту/получателю/reply_markup), отсутствие необработанных исключений в worker task.

**Verify:**
- **macbook:** тесты под `integration` маркером пропускаются.
- **сервер:** `bash scripts/test_integration.sh tests/test_e2e_client_cases.py -v` — все 30 кейсов.
- Если хотя бы один падает: это И регрессия и непокрытая ситуация. Не пропускать с `xfail`. Либо чинить код, либо чинить тест (если кейс изначально невалидный — вычеркнуть из матрицы с обоснованием).
- Зафиксировать в `docs/CLIENT_CASES.md` финальный список кейсов и их статус — какие зелёные, какие в работе.

**Gate Phase 4.4:** все 30 кейсов зелёные на сервере, или те что отложены — явно помечены как known-limited с тикетом.

### 4.5 Безопасность

`tests/test_security.py` — частично unit (без `integration`), частично интеграционные. Unit-часть проверяется локально, интеграционная — на сервере:
- Подделанный initData (неверный hash) → 401.
- initData с auth_date=0 → 401.
- JWT с `iss=другой` → 401.
- /api/auth/refresh без X-CSRF-Token → 403.
- /api/auth/otp/verify 10 раз подряд за 1 сек → 429.
- /api/whatsapp/inbound без правильного bridge secret → 401.

**Gate Phase 4:** `pytest -q` зелёный, coverage `pytest --cov=src` ≥ 70% (сейчас неизвестно, но скорее всего 50-60).

---

## Phase 5 — Операбельность

**Где гоняется:** код локально, верификация (метрики, watchdog, healthcheck, journalctl priority) — **только на сервере** через `ssh aws-shermos1-frankfurt`.

### 5.1 Метрики и /metrics endpoint

**agent prompt:**
> Добавить простой Prometheus exposition (через `prometheus_client`):
> - Счётчик `outbound_events_sent_total{channel,status}`.
> - Гистограмма `llm_call_duration_seconds`.
> - Gauge `worker_jobs_in_flight`.
> - Endpoint `/metrics` на API (без auth, но за privacy-network) ИЛИ отдельный порт.

**Verify:** `curl localhost:88/metrics | head` показывает метрики.

### 5.2 Лог-уровни приведены к syslog priority

**Контекст:** `journalctl -u shermos-worker -p err` сейчас пуст, потому что Python пишет JSON-строки уровня ERROR в stdout, а systemd их не парсит — все уходят как INFO. Нужно либо `SyslogIdentifier` + structured logging с приоритетами (`<ERROR>` префикс), либо переход на `python-systemd` / `systemd.daemon`.

**agent prompt:**
> Самое простое: использовать `systemd.journal.JournalHandler` (из `python-systemd`) в `src/utils/logger.py`, чтобы каждый log record выставлял правильный priority. Тогда `journalctl -p err` будет работать.

**Verify:** на сервере после деплоя: симулировать ошибку (например, кратковременно положить Postgres) → `journalctl -u shermos-worker -p err -n 20` показывает свежие записи.

### 5.3 Healthcheck-ы у всех сервисов (systemd / docker)

**agent prompt:**
> В каждом systemd-юните `WatchdogSec=60`, и каждый сервис sd_notify(WATCHDOG=1) каждые 30 сек. Если сервис висит — systemd рестартит. Использовать `python-systemd.daemon`.

**Verify:** kill -STOP <pid> воркера на 90 сек → systemd рестартит сам.

### 5.4 Документация по операционке

**agent prompt:**
> Обновить `DEPLOY.md`:
> - Полный список env переменных (с примерами и какие обязательные).
> - Как обновить продакшен (git pull, миграции, рестарт сервисов в правильном порядке).
> - Как откатить (через snapshot-ветку из 0.2).
> - Как смотреть логи, метрики, как читать «manager_job_failed» и т.п.

**Gate Phase 5:** в DEPLOY.md есть runbook на 4 типичных инцидента (Gemini в дауне, Postgres в дауне, Redis в дауне, бридж WhatsApp в дауне).

---

## Phase 6 — Раздельный деплой: Frontend на Netlify, Backend на Ubuntu

**Зачем:** сейчас фронтенд (Mini App + CMS) отдаётся через uvicorn (`run_api.py` mount StaticFiles) → cloudflared trycloudflare URL. Это:
1. Завязывает поведение фронтенда на состояние backend-сервиса.
2. trycloudflare URL временный — каждый рестарт `shermos-tunnel` даёт новый адрес. Нет стабильной ссылки для Telegram BotFather и для клиентов.
3. CDN-преимущества (кеш, географическое распределение) не используются.
4. `.netlify/state.json` показывает что Netlify-проект `shermos-architecture-viz-32711` **уже создан** (siteId `752f6fe1-1f6c-4df5-bcc9-4e5b939293e8`) — но не настроен под Mini App.

Цель: фронтенд деплоится на Netlify (стабильный URL, CDN, auto-deploy на git push), backend остаётся на Ubuntu и обслуживает только API. Между ними — кросс-доменные запросы через явный `VITE_API_BASE_URL`.

### 6.0 Audit текущего состояния Netlify-проекта (один шаг, ручной)

**Где:** macbook.

**agent prompt:**
> 1. `netlify status` — увидеть текущий проект (`shermos-architecture-viz-32711`).
> 2. `netlify api listSiteDeploys --data '{"site_id":"752f6fe1-1f6c-4df5-bcc9-4e5b939293e8"}' | head -50` — посмотреть последний деплой, что там лежит.
> 3. Принять решение: переиспользовать (rename + новый publish dir) ИЛИ создать новый site с понятным именем `shermos-cms` или `shermos-app`.
> 4. Если новый: `netlify sites:create --name shermos-app` (или интерактивно через `netlify init`). Запомнить новый siteId, обновить `.netlify/state.json` (он в .gitignore — это локальный файл).

**Verify:** `netlify status` показывает выбранный/созданный сайт.

### 6.1 Frontend: API client → абсолютный URL через `VITE_API_BASE_URL`

**Файлы:** `mini-app/src/api/client.ts`, `mini-app/.env.example` (новый), `mini-app/.env.production` (новый, в .gitignore).

**agent prompt:**
> 1. В `mini-app/src/api/client.ts` найти базовый URL формирующий запросы (вероятно `''` или относительные пути типа `/api/...`).
> 2. Ввести `const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''`. Все запросы идут с `${API_BASE}/api/...`.
> 3. Пустая строка = same-origin поведение (для локального dev и текущего uvicorn-варианта). Проставленный URL = абсолютный (для Netlify production).
> 4. Создать `mini-app/.env.example` с шаблоном:
>    ```
>    VITE_API_BASE_URL=https://carb-investigation-drive-equations.trycloudflare.com
>    ```
> 5. `mini-app/.env.production` (в gitignore!) — реальное значение, используется при `npm run build` локально для тестов. Netlify build использует env-переменные из своего UI, не из git.
> 6. Тесты: добавить unit-тест в `mini-app/src/__tests__/api-base-url.test.ts` если фреймворк есть; иначе просто smoke в `tsc --noEmit` и `npm run build`.

**Verify (локально):**
- `cd mini-app && VITE_API_BASE_URL=https://example.com npm run build` → в `dist/assets/*.js` встречается `https://example.com`.
- `cd mini-app && npm run build` (без env) → в bundle нет жёстко зашитого URL.
- Backend локально: запускать без статики (см. 6.7) и видеть, что фронт всё ещё стучится в API через absolute URL.

### 6.2 Корневой `netlify.toml` (под git)

**Файл:** `netlify.toml` в корне репо (новый).

```toml
[build]
  base = "mini-app"
  command = "npm run build"
  publish = "mini-app/dist"

[build.environment]
  NODE_VERSION = "20"

# SPA: catch-all для Mini App
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

# CMS — отдельный entry point
[[redirects]]
  from = "/cms"
  to = "/cms.html"
  status = 200

[[redirects]]
  from = "/cms/*"
  to = "/cms.html"
  status = 200

[[headers]]
  for = "/*"
  [headers.values]
    # Telegram Mini App требует загрузку в iframe — НЕ ставить X-Frame-Options
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"
    # CSP включаем когда CMS будет реально проверена в браузере; пока пусто.
```

**agent prompt:**
> 1. Создать `netlify.toml` с содержимым выше.
> 2. Удалить из репо `.netlify/` если случайно попала (она в .gitignore — должна не попасть, но проверить).
> 3. Тестовый build локально: `cd mini-app && npm run build`, потом из корня `netlify build --offline` (если CLI поддерживает) — должен прогнать тот же скрипт.

**Verify:** `npm run build` зелёный, `dist/index.html` + `dist/cms.html` существуют.

### 6.3 Деплой на Netlify (CI через git + ручной первичный)

**agent prompt:**
> 1. Из корня репо: `netlify deploy --prod --dir=mini-app/dist` (или сначала `--dir=mini-app/dist` без `--prod` для preview).
> 2. URL результата зафиксировать.
> 3. Настроить **continuous deployment** через Netlify UI или `netlify init`: connect GitHub репо `mrMoses2000/shermos_bot`, branch `main`, build settings из `netlify.toml`. После этого каждый push в main = авто-деплой фронта.
> 4. В Netlify UI выставить env-переменную `VITE_API_BASE_URL` со значением **публичного API URL backend'а** (см. 6.4 ниже — для начала это текущий trycloudflare URL).

**Verify:**
- `curl https://<netlify-url>/index.html` → 200, HTML.
- `curl https://<netlify-url>/cms.html` → 200, CMS-разметка.
- Открыть в браузере, в DevTools → Network → запрос на API уходит на `VITE_API_BASE_URL`.

### 6.4 Backend: стабильный публичный API URL (две опции)

**Зачем:** Netlify-фронту нужен фиксированный API endpoint. Сейчас `https://carb-investigation-drive-equations.trycloudflare.com` живёт случайно (последний рестарт cloudflared был 14 апреля). Любой `systemctl restart shermos-tunnel` даст новый URL — Netlify-фронт сломается.

**Опция A: named Cloudflare tunnel (рекомендую)**
1. На сервере: `cloudflared login` → авторизация в Cloudflare-аккаунте через браузер.
2. `cloudflared tunnel create shermos-api` → получаем UUID туннеля и credentials json.
3. Создать `/etc/cloudflared/config.yml`:
   ```yaml
   tunnel: <UUID>
   credentials-file: /etc/cloudflared/<UUID>.json
   ingress:
     - hostname: api.shermos.example.com  # требуется свой домен в CF
       service: http://localhost:9443
     - service: http_status:404
   ```
4. `cloudflared tunnel route dns shermos-api api.shermos.example.com` → в Cloudflare DNS прописывается CNAME.
5. Обновить systemd unit `shermos-tunnel.service` — `ExecStart=/usr/bin/cloudflared --config /etc/cloudflared/config.yml tunnel run shermos-api`.
6. `systemctl restart shermos-tunnel` → стабильный URL `https://api.shermos.example.com`.

**Требует:** свой домен в Cloudflare. Если нет — пропустить опцию A.

**Опция B: оставить trycloudflare как временный**
- Просто **не рестартить shermos-tunnel** без необходимости.
- В Netlify env прописать текущий trycloudflare URL.
- Документировать в `docs/DEPLOY_NETLIFY.md`: «при перезапуске cloudflared взять новый URL из `journalctl -u shermos-tunnel | grep trycloudflare` и обновить `VITE_API_BASE_URL` в Netlify UI». Это операционный долг.

**agent prompt (для опции A):**
> Подготовить `cloudflared/config.yml.template` в репе (`scripts/cloudflared/config.yml.template`) с placeholder для UUID и hostname. Документировать в `docs/STABLE_API_URL.md` шаги 1-6 выше. Не требовать выполнения — пользователь сделает когда у него будет домен.

**agent prompt (для опции B — то что делаем сейчас):**
> Документировать в `docs/STABLE_API_URL.md`:
> - текущий статус: trycloudflare без своего домена.
> - команда для получения текущего URL: `ssh aws-shermos1-frankfurt 'journalctl -u shermos-tunnel | grep trycloudflare | tail -1'`.
> - инструкция как обновить `VITE_API_BASE_URL` в Netlify UI после ротации URL.
> - upgrade path до опции A.

**Verify:** `docs/STABLE_API_URL.md` есть.

### 6.5 CORS на сервере → Netlify URL

**agent prompt:**
> 1. На сервере (через ssh, ручная правка `.env` — это секрет, не git): обновить `CORS_ALLOWED_ORIGINS` на конкретный Netlify URL (например `https://shermos-app.netlify.app`).
> 2. `systemctl restart shermos-api`.
> 3. Проверка из ноута: `curl -H "Origin: https://shermos-app.netlify.app" -i https://<api-url>/api/health/bridges` → ACAO заголовок присутствует.

**Verify:** preflight OPTIONS-запрос на `/api/orders` с Origin от Netlify возвращает корректные ACAO + ACAM + ACAH.

### 6.6 Telegram Mini App URL update

**agent prompt:**
> 1. В Telegram BotFather: `/mybots` → выбрать клиентский бот → Bot Settings → Menu Button (или /newapp если нет) → URL: `https://<netlify-url>/`.
> 2. То же для менеджерского бота, если у него есть Mini App: URL `https://<netlify-url>/cms`.
> 3. Тестовый прогон: открыть Mini App из Telegram, увидеть Mini App страницу.

**Verify:** Mini App открывается в Telegram WebView, делает запросы на API, получает ответы.

### 6.7 Backend больше не отдаёт фронтенд (опционально, но чище)

**Файл:** `run_api.py`.

**agent prompt:**
> 1. Завернуть `app.mount("/", StaticFiles(directory="mini-app/dist", html=True), name="spa")` в условие `if os.getenv("SERVE_FRONTEND_LOCAL") == "1"`.
> 2. На сервере НЕ выставлять `SERVE_FRONTEND_LOCAL=1` → фронт идёт ТОЛЬКО на Netlify.
> 3. Локально для dev можно выставить и продолжать работать как раньше.
> 4. Тестовый прогон локально: `SERVE_FRONTEND_LOCAL=1 python run_api.py` → отдаёт SPA. Без флага → 404 на `/`.

**Verify:** на сервере `curl https://<api-url>/` → 404 (или подобный ответ от FastAPI), `curl https://<api-url>/api/health/bridges` → 401. Frontend полностью на Netlify.

### 6.8 `MINI_APP_URL` в env → Netlify URL

**agent prompt:**
> На сервере в `.env`: `MINI_APP_URL=https://<netlify-url>/`. Рестарт worker'а (он использует MINI_APP_URL для построения inline-кнопок «Открыть Mini App»).

**Verify:** клиент в Telegram, нажимая кнопку «Открыть Mini App» → попадает на Netlify-фронт.

### 6.9 Документация

**agent prompt:**
> Создать/обновить:
> - `docs/DEPLOY_NETLIFY.md` — как настроить Netlify, какие env, как менять API URL без передеплоя backend.
> - `DEPLOY.md` — раздел «Раздельный деплой: фронтенд + backend».

**Gate Phase 6:**
- Frontend на стабильном Netlify URL.
- Backend отдаёт только API (4xx на `/`).
- Mini App открывается в Telegram через Netlify URL.
- CMS открывается в браузере по `/cms`.
- CORS-префлайт работает с Netlify origin.
- Хотя бы один e2e: пройти OTP-логин в CMS из обычного браузера до получения `access_token`.

---

## Phase 7 — Watchdog production wiring (доделать Phase 5.3)

**Зачем:** в Phase 5.3 я приготовил Python-сторону watchdog (`src/utils/watchdog.py`, notify-функции, интеграция в `run_worker.py`/`run_webhook.py`), но не положил **systemd unit-файлы** в репу и не активировал `Type=notify, WatchdogSec=60` в проде. Без этого watchdog никакого эффекта не даёт.

### 7.1 Все 5 unit-файлов в репу

**Файлы:** `scripts/systemd/shermos-{worker,webhook,api,wa-client,wa-manager,tunnel}.service`. Сейчас в репе только два WhatsApp-юнита.

**agent prompt:**
> 1. Через ssh снять текущие unit-файлы с сервера: `for s in worker webhook api tunnel; do ssh aws-shermos1-frankfurt "systemctl cat shermos-$s.service" > /tmp/$s; done`.
> 2. Очистить от инструкций systemd-комментариев (строки `#` с путём).
> 3. Положить в `scripts/systemd/`. Привести имена в соответствие с уже лежащими (`shermos-worker.service` и т.п.).
> 4. В worker и webhook добавить `Type=notify`, `NotifyAccess=main`, `WatchdogSec=60`, `Restart=on-failure` (если ещё нет).
> 5. API оставить без watchdog (uvicorn не интегрирован с sd_notify; только Restart=on-failure).
> 6. Tunnel — без watchdog, но `Restart=on-failure`.
> 7. WhatsApp-бриджи — Node.js, sd_notify работает только с системным libsystemd; пока без watchdog (TODO в комментарии).

**Verify (локально):** `systemd-analyze verify scripts/systemd/*.service` (если есть на macOS — нет; пропустить).

### 7.2 Скрипт деплоя unit-файлов

**Файл:** `scripts/install_systemd.sh`.

```bash
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")/systemd" && pwd)"
for f in "$DIR"/*.service; do
  name="$(basename "$f")"
  echo "Installing $name..."
  sudo cp "$f" "/etc/systemd/system/$name"
done
sudo systemctl daemon-reload
echo "Done. Restart with: sudo systemctl restart shermos-{worker,webhook,api,wa-client,wa-manager}"
```

Сделать chmod +x, документировать в DEPLOY.md.

### 7.3 systemd-python на сервере

**agent prompt:**
> 1. На сервере: `apt install -y libsystemd-dev` (или эквивалент Ubuntu 24.04 — `libsystemd-dev`).
> 2. `cd ~/shermos_bot && .venv/bin/pip install systemd-python>=235`.
> 3. Smoke: `.venv/bin/python -c "import systemd.daemon; print(systemd.daemon.notify('READY=1'))"` — без ошибки.

### 7.4 Тестовый прогон watchdog

**agent prompt:**
> 1. Установить unit-файлы через скрипт (7.2), `daemon-reload`, перезапустить worker.
> 2. `journalctl -u shermos-worker --since "1 min ago" -p info | grep "WATCHDOG\|notify"` — увидеть `READY=1`.
> 3. Симулировать зависание: `sudo kill -STOP <pid_worker>`. Подождать 70 секунд.
> 4. Проверить: `systemctl status shermos-worker` — был перезапущен. В логах: `Watchdog timeout` от systemd, `Started` снова.

**Gate Phase 7:**
- Все 5 unit-файлов в репе.
- На сервере watchdog активен для worker и webhook.
- Тест с kill -STOP → автоматический рестарт через 60 сек.

---

## Phase 8 — Закрытие xfail (C-19, C-26, C-27)

**Контекст:** в Phase 4.4 три кейса остались `xfail`. Это реальные продакшн-проблемы.

### 8.1 — C-19: периодический recover_stuck_jobs

**Файл:** `src/queue/worker.py`.

**Бизнес-проблема:** worker умер посреди обработки → job застрял в `queue:processing:client` → клиент не получает ответа. `recover_stuck_jobs` зовётся **только при старте** worker'а (в начале `run_worker`). Если worker завис без рестарта (или watchdog отсутствует на каком-то сервисе) — job-зомби накапливаются.

**План:**
1. Создать функцию `recover_stuck_jobs_periodic_loop(redis_client, interval_seconds=300, max_age_seconds=600)`:
   ```python
   async def recover_stuck_jobs_periodic_loop(redis_client, interval=300, max_age=600):
       while True:
           try:
               recovered = await redis_client.recover_stuck_jobs(
                   "queue:processing:client", "queue:incoming",
                   max_age_seconds=max_age,
               )
               # same for manager
               if recovered:
                   logger.info("recovered_stuck_jobs", extra={"count": recovered})
           except asyncio.CancelledError:
               raise
           except Exception as exc:
               logger.exception("recover_loop_error", extra={"error": str(exc)})
           await asyncio.sleep(interval)
   ```
2. В `run_worker`: добавить `asyncio.create_task(recover_stuck_jobs_periodic_loop(...))` к существующим background tasks.
3. В `RedisClient.recover_stuck_jobs` добавить параметр `max_age_seconds` если ещё нет — проходить только по job'ам со старым `received_at`.
4. Обновить `tests/test_redis_client.py` под новый параметр.
5. В `tests/test_e2e_client_cases.py::test_C19_worker_recovery_after_kill_simulation`:
   - Снять `xfail`.
   - Обновить тест: положить старый job (с received_at 11 минут назад) в processing-очередь, дать loop'у тикнуть, assert job вернулся в `queue:incoming`.

**Объём:** ~50 строк кода + 1 e2e-тест. Один коммит: `feat(8.1): periodic stuck-jobs recovery in worker (closes C-19)`.

### 8.2 — C-26: LLM-компрессия memory_summary

**Файл:** `src/llm/conversation_memory.py:merge_memory_summary`.

**Бизнес-проблема:** длинный диалог теряет ранние факты (ширину/высоту/тип стекла) при байтовой обрезке `summary[-MAX_SUMMARY_CHARS:]`.

**Два возможных подхода — выбираю гибрид:**

**Подход X (структурный):** хранить ключевые параметры в `conversation_state.collected_params` (это уже JSONB колонка, см. `conversation_state` table). Они **никогда не теряются** при сжатии summary. Summary остаётся для разговорного контекста.

**Подход Y (LLM-сжатие):** когда summary > MAX, вызывать LLM с инструкцией «сожми, сохранив все размеры и контактные данные». Дороже (один лишний LLM-call в эпизоде сжатия), но универсальнее.

**Гибрид:** Подход X — основной (бесплатный, не теряет факты), Подход Y — fallback для контекста и нечисловых деталей.

**План:**
1. Audit: убедиться, что `apply_actions` пишет ВСЕ числовые/важные параметры в `collected_params`. Проверить что нет ничего что попадает только в conversation_state.memory_summary, минуя `collected_params`.
2. В `merge_memory_summary`: при `len(summary) > MAX_SUMMARY_CHARS`:
   - Сначала попытаться сжать через LLM с инструкцией «не теряй: имена, телефоны, адреса, числовые размеры».
   - Если LLM-call упал → fallback на текущее байтовое усечение (с пометкой `[older context truncated]` в начале).
3. Сделать MAX_SUMMARY_CHARS env-настраиваемым (default 900).
4. Обновить тесты: `tests/test_conversation_memory.py` — мокать call_llm для теста сжатия, asserть что числовые факты сохраняются.
5. В `tests/test_e2e_client_cases.py::test_C26_long_dialog_memory_keeps_key_params`:
   - Снять xfail.
   - Тест: положить 100 chat_messages, в первых 5 — «ширина 2.5», в средних — болтовня. Прогнать `refresh_conversation_memory_if_needed`. Assert что в conversation_state «2.5» либо в `collected_params['width']` (если LLM сэкстракчивал), либо в `memory_summary` (если LLM-сжатие сохранило строку).

**Объём:** ~80 строк + изменения тестов. Один коммит: `feat(8.2): LLM-based summary compression preserves key facts (closes C-26)`.

### 8.3 — C-27: команда /reset

**Файл:** `src/queue/worker.py` — handler команд клиента.

**Бизнес-проблема:** есть `/clear`, нет `/reset` и NL-вариантов.

**План:**
1. В command-handler (там где обрабатывается `/clear`) добавить алиас: `if cmd in {"/clear", "/reset", "/новый", "/начать"}: ... clear conversation_state ...`.
2. В `tests/test_e2e_client_cases.py::test_C27_reset_command_clears_state`: снять xfail. Создать conversation_state с параметрами, послать `/reset`, assert state пуст (или `mode='idle'`).
3. NL-варианты («начать сначала», «обнулить») — это уже LLM-логика, не command parser. Обновить промпт в `prompt_builder.py` чтобы LLM эмитил `clear_state` action на такие фразы. Опционально, отдельный коммит.

**Объём:** ~10 строк + 1 тест. Один коммит: `feat(8.3): /reset command alias for /clear (closes C-27)`.

**Gate Phase 8:**
- Все три xfail сняты.
- Полный прогон интеграции на сервере: 40 passed, 0 xfailed (или 0 failed; xfail можно оставить если новый кейс появился, но эти три — нет).
- `docs/CLIENT_CASES.md` обновлён: эти кейсы помечены ✅.

---

## Phase 9 — Ротация секретов (опциональная)

**Зачем:** в attic'е лежал `.env.backup-manager-whatsapp-20260430-111840` со всеми боевыми токенами. Файл **никогда не был в git** (проверено `git log`), но физически 4 дня лежал в `~/shermos_bot/` на сервере. Если за это время к серверу никто посторонний не имел доступа — риск низкий. Если сомневаешься — ротировать.

### 9.1 Telegram bot tokens

**agent prompt:**
> 1. В BotFather: `/mybots` → выбрать клиентский бот → API Token → Revoke current token. Получить новый.
> 2. То же для менеджерского бота.
> 3. На сервере обновить `.env`: `TELEGRAM_BOT_TOKEN=<new>`, `MANAGER_BOT_TOKEN=<new>`.
> 4. В Telegram перезалить webhook'и: `curl "https://api.telegram.org/bot<NEW_TOKEN>/setWebhook?url=...&secret_token=..."` (URL и secret_token взять из текущей конфигурации).
> 5. Рестарт `shermos-worker shermos-webhook`.
> 6. Тест: послать `/start` через Telegram → бот ответил.

### 9.2 BRIDGE_SHARED_SECRET

**agent prompt:**
> 1. На сервере: `python -c 'import secrets; print(secrets.token_urlsafe(32))'` — новый секрет.
> 2. Обновить `.env` (`BRIDGE_SHARED_SECRET=<new>`) И env'ы обоих WhatsApp-бриджей (если они хранят секрет отдельно — `whatsapp-bridge/.env.client` / `.env.manager`).
> 3. Рестарт `shermos-wa-client shermos-wa-manager shermos-api shermos-worker`.
> 4. Тест: WhatsApp-сообщение → видим `whatsapp_inbound_queued` без 401.

### 9.3 CMS_ADMIN_TOKEN

**agent prompt:**
> 1. Сгенерить новый: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
> 2. Если нигде не используется (audit `grep -r CMS_ADMIN_TOKEN`) — можно вообще убрать, есть JWT-логин.
> 3. Иначе обновить `.env`, рестарт `shermos-api`.

### 9.4 Postgres password (последний — самый рискованный)

**agent prompt:**
> 1. `docker exec shermos_bot_postgres_1 psql -U shermos -d shermos_bot -c "ALTER USER shermos PASSWORD '<new>'"`.
> 2. Обновить `.env`: `POSTGRES_PASSWORD=<new>`.
> 3. Рестарт ВСЕХ сервисов (`shermos-worker shermos-webhook shermos-api`).
> 4. Тест: послать сообщение, видеть успешный inbound в логах.

**Gate Phase 9 (опционально — если решил ротировать):**
- Все 4 типа секретов ротированы.
- Все сервисы зелёные.
- Один тестовый flow (Telegram + WhatsApp + CMS-OTP) проходит до конца.

---

## Финальный Gate

Перед закрытием всего плана:

- [ ] Phase 0 done — снапшот в git, репо чистый.
- [ ] Phase 1 done — 0 спам-логов про `whatsapp_manager_not_allowlisted` за час, оба номера обрабатывают сообщения.
- [ ] Phase 2 done — 10 carry-over багов закрыты, тесты зелёные.
- [ ] Phase 3 done — CMS живой, OTP работает, CORS закрыт, CSRF на refresh.
- [ ] Phase 4 done — testcontainers интеграционные тесты прогоняются, **30 клиентских кейсов C-01..C-30 зелёные**, coverage ≥ 70%.
- [ ] Phase 5 done — метрики, healthcheck, runbook.
- [ ] **Phase 6 done — Frontend на Netlify, Backend только API, CORS закрыт на Netlify origin, Mini App открывается через Netlify.**
- [ ] **Phase 7 done — watchdog активен в systemd, kill -STOP → авторестарт за 60 сек.**
- [ ] **Phase 8 done — три xfail закрыты, integration 40/40 зелёных.**
- [ ] **Phase 9 — опционально, по решению владельца.**
- [ ] **Phase 10 done — Telegram-стек полностью удалён, оба бота работают только через WhatsApp.**

---

## Phase 10 — Decommission Telegram (только WhatsApp для обоих ботов)

**Решение владельца (2026-05-05):** Telegram-бот не нужен ни для клиента, ни для менеджера. Оба канала — **только WhatsApp**. Mini App в Telegram-WebView не используется. CMS на Netlify остаётся как браузерный сайт.

**Что остаётся жить:**
- WhatsApp client bridge (`shermos-wa-client.service`).
- WhatsApp manager bridge (`shermos-wa-manager.service`).
- CMS на Netlify (https://shermos-mini-app-takoe.netlify.app/cms) — авторизация через WhatsApp-OTP (Phase 3), JWT-сессии.
- Backend FastAPI с `/api/whatsapp/inbound`, `/api/health/*`, `/api/auth/*`, и доменными эндпоинтами для CMS.
- Worker для обработки очередей `queue:incoming` и `queue:manager`.

**Что выпиливаем:**
- `shermos-webhook.service` — обслуживал только Telegram webhook'и.
- `src/bot/webhook.py` — удалить.
- `src/bot/telegram_sender.py` — удалить (или оставить как dead-code? предпочту удалить).
- `run_webhook.py` — удалить.
- Telegram-специфичные ENV: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `MANAGER_BOT_TOKEN`, `MANAGER_WEBHOOK_SECRET`, `MANAGER_CHAT_IDS`. Удалить из `.env` на сервере и из `docs/ENV_REFERENCE.md`.
- Telegram initData auth в `src/api/auth.py:require_auth` — fallback на `X-Telegram-Init-Data` убирается; остаётся JWT и `X-CMS-Admin-Token`.
- В CMS (`mini-app/src/auth.ts`) — функция `detectAuthMode()` всегда возвращает `"cms"`; код для Telegram WebApp удаляется. `index.html` (Telegram Mini App entry) удаляется. Vite multi-entry build → single entry `cms.html` либо переименовать в `index.html`.
- `process_manager_job` в `src/queue/worker.py` — содержит ветки про Telegram callback_data (`meas_confirm:N`, `meas_reject:N`, `meas_call:N`). Эти команды **сохраняем** — менеджер шлёт их текстом в WhatsApp (нативные buttons WhatsApp из Phase 1.5.4 кладут эти строки в текст: «👉 Подтвердить: /meas_confirm:42»). Маршрут уже работает.
- В `src/llm/actions_applier.py` — выпилить отправку Telegram-уведомлений менеджерам (`for manager_chat_id in settings.manager_chat_ids_list`) и связанные outbox-инсерты с `channel="telegram"`. Оставить только `channel="whatsapp"`.
- `tests/test_webhook.py`, `tests/test_telegram_sender.py`, `tests/test_e2e_telegram_flow.py` — удалить.
- Тесты, которые используют `manager_chat_ids` для проверки Telegram-маршрутов — переписать на whatsapp-only (или удалить если избыточны).
- В клиентских кейсах (Phase 4.4): C-01 (Telegram /start), C-11 (manager confirm в Telegram), C-16 (Telegram dedup), C-23 (Mini App initData) — удалить или преобразовать в WhatsApp-варианты.

### 10.1 Удалить серверные сущности

**agent prompt:**
> 1. На сервере (через ssh): `sudo systemctl disable --now shermos-webhook` → сервис больше не запускается.
> 2. Удалить unit-файл: `sudo rm /etc/systemd/system/shermos-webhook.service && sudo systemctl daemon-reload`.
> 3. В `.env` удалить строки: `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_WEBHOOK_SECRET=`, `MANAGER_BOT_TOKEN=`, `MANAGER_WEBHOOK_SECRET=`, `MANAGER_CHAT_IDS=`.
> 4. На бот-стороне Telegram (BotFather) — оставить как есть (отзывать токены не обязательно — они без ENV у нас не делают ничего, но если хочешь чистоту: `/deletebot` или revoke token у обоих ботов).

**Verify:**
- `ssh aws-shermos1-frankfurt 'systemctl status shermos-webhook'` → not loaded / not active.
- `journalctl -u shermos-worker --since "5 min ago" | grep -E "no_manager_channels_configured|telegram"` → видим warning «menager_chat_ids пусто», игнорируем (после подтверждения, что WhatsApp-уведомления работают).

### 10.2 Удалить код (один большой коммит)

**Файлы на удаление:**
- `src/bot/webhook.py`
- `src/bot/telegram_sender.py`
- `run_webhook.py`
- `tests/test_webhook.py`
- `tests/test_telegram_sender.py`
- `tests/test_e2e_telegram_flow.py`

**Файлы на правку:**
- `src/api/auth.py`: `require_auth` без telegram-fallback.
- `src/llm/actions_applier.py`: убрать telegram-блок отправки менеджерам.
- `src/queue/outbox_dispatcher.py`: убрать ветку `channel='telegram'` (или оставить как мёртвую если решим что вдруг полезно — нет, удаляем).
- `src/queue/worker.py`: 
  - Удалить `manager_chat_id`-логику нотификаций.
  - Telegram-callback-обработчики (callback_query) удалить.
  - process_manager_job: оставить логику команд (`/orders`, `/meas_confirm:N` etc.) — она работает для WhatsApp manager-message текстов.
- `src/config.py`: удалить `telegram_bot_token`, `telegram_webhook_secret`, `manager_bot_token`, `manager_webhook_secret`, `manager_chat_ids`.
- `src/models.py`: возможно полезно убрать `Job.bot_type` если он использовался только для Telegram-различения; оставить, потому что определяет client-vs-manager очередь.
- `src/bot/whatsapp_ingress.py`: проверить что нет упоминаний telegram-token-token (его там и не должно быть).
- `tests/conftest.py`: удалить `os.environ.setdefault("TELEGRAM_BOT_TOKEN", ...)` строки.
- `tests/test_e2e_client_cases.py`: удалить C-01, C-11, C-16, C-23. Адаптировать остальные.
- `mini-app/src/auth.ts`: `detectAuthMode` всегда `"cms"`. Удалить ветку Telegram WebApp.
- `mini-app/index.html`: удалить (Telegram Mini App entry больше не нужен).
- `mini-app/src/main.tsx`, `mini-app/src/App.tsx`: удалить (если они были Telegram-mode только) или преобразовать.
- `mini-app/vite.config.ts`: убрать `mini` entry, оставить только `cms`. ИЛИ переименовать `cms.html` в `index.html` чтобы Netlify SPA работал на корне.
- `netlify.toml`: убрать `/cms` redirects — теперь сайт сам по себе CMS.
- `docs/CMS_DEPLOY.md`, `docs/DEPLOY_NETLIFY.md`: удалить упоминания Telegram BotFather, Mini App в Telegram, X-Telegram-Init-Data header.

**agent prompt:**
> Сделать в одной ветке `chore/decommission-telegram-2026-05-NN`. Удалить файлы перечисленные выше; править оставшиеся. Прогнать `pytest -q` — должно остаться около 270-280 тестов (минус удалённые ~25-30). На сервере после deploy: `journalctl -u shermos-worker -n 100` — нет ошибок import, worker нормально стартует, `worker_startup_config` логирует только manager_whatsapp_numbers.

### 10.3 Frontend — single CMS site

**agent prompt:**
> 1. Удалить `mini-app/index.html`, `mini-app/src/main.tsx`, `mini-app/src/App.tsx` (Telegram Mini App).
> 2. Переименовать `mini-app/cms.html` → `mini-app/index.html` (теперь это корень).
> 3. В `vite.config.ts` убрать multi-entry: `build.rollupOptions.input` с одним `cms` или просто оставить дефолт (Vite сам найдёт `index.html`).
> 4. В `netlify.toml` убрать `/cms` redirects, оставить только SPA-fallback на `/index.html`.
> 5. `npm run build` → `dist/index.html` есть. Никакого `cms.html`.
> 6. Передеплой через `netlify deploy --prod`. URL `https://shermos-mini-app-takoe.netlify.app/` теперь сразу = CMS-логин.

### 10.4 Адаптировать клиентские кейсы

**Удалить:** C-01 (`/start` Telegram), C-11 (manager Telegram callback), C-16 (Telegram dedup), C-23 (Mini App initData).

**Заменить:** C-01-WA: `/start` через WhatsApp от нового номера → приветствие.

### 10.5 Документация

`docs/DEPLOY_NETLIFY.md`, `DEPLOY.md`, `docs/WHATSAPP_DUAL_BOT.md`, `REMEDIATION_PLAN.md` — обновить, убрав упоминания Telegram. CMS — единственный фронт, доступен через Netlify URL. Авторизация — через WhatsApp-OTP в любом случае.

**Gate Phase 10:**
- `shermos-webhook.service` отключён.
- В коде нет ни одного `import telegram_sender` или `import webhook`.
- `pytest -q` зелёный.
- На WhatsApp клиенту: «/start» от нового номера → приветствие. Менеджеру: создание замера → уведомление в WhatsApp. Менеджер: `/meas_confirm:N` через WhatsApp → статус confirmed.
- CMS на Netlify-URL открывается, OTP логин работает.

## Порядок исполнения

Рекомендуемая последовательность:
1. **Сразу:** Phase 0 (без неё всё остальное опасно делать). ✅ done
2. **Затем:** Phase 1 (визибельная боль в проде, простой фикс). ✅ done
3. Phase 2 параллельно с Phase 1, по одному коммиту за фикс. ✅ done
4. Phase 4.1 (серверная интеграционная инфра) — потому что Phase 4.2/4.3 и Phase 3 проще тестировать поверх неё. ✅ done
5. Phase 3 (CMS). ✅ done
6. Phase 4.2-4.5 (интеграционные тесты + security). ✅ done
7. Phase 5 (операбельность) — после стабилизации. ✅ done
8. **Phase 6 (Netlify + раздельный деплой)** — даёт стабильный URL Mini App.
9. **Phase 7 (watchdog production wiring)** — продолжение Phase 5.3.
10. **Phase 8 (закрытие xfail)** — три мелких бага из аудита.
11. **Phase 9 (ротация секретов)** — опционально.

## Что НЕ входит в этот план

- Миграция с Gemini CLI на Gemini SDK (отдельная история, опасная).
- Production hardening Redis (auth, TLS) — упомянуто как замечание, но фактическое исправление = отдельный сетевой проект.
- Шифрование Baileys-кредов в Redis — сделать после стабилизации, отдельной задачей.
- WhatsApp media (фото/голос/документы) — там сейчас отдельные баги, но они не блокируют основной флоу.
- Reconnect-storm в Baileys-бридже (jitter, ceiling) — заметка для отдельной задачи.

Эти пункты — кандидаты на следующий аудит.
