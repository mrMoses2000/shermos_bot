const hops = [
  {
    icon: "📨",
    name: "Telegram POST",
    file: "src/bot/webhook.py:50-85",
    description: "Telegram доставляет сырой Update в aiohttp по HTTPS.",
    input: ["HTTPS POST от серверов Telegram на 0.0.0.0:88", "JSON payload Telegram Update", "Заголовок X-Telegram-Bot-Api-Secret-Token"],
    output: ["Извлечены chat_id, user_id, text, msg_type, callback_data", "Всегда возвращается HTTP 200"],
    network: "TLS с self-signed сертификатом, TCP порт 88, обработчик aiohttp.",
    state: ["Долговременного состояния ещё нет; сырой payload живёт только в памяти процесса."],
    risks: [{ level: "none", label: "Ошибки проглатываются" }],
    timing: "< 50ms",
    code: `<span class="kw">async def</span> _process_webhook(request, bot_type, secret_token):
    <span class="kw">if</span> request.headers.get(<span class="str">"X-Telegram-Bot-Api-Secret-Token"</span>) != secret_token:
        <span class="kw">return</span> web.json_response({<span class="str">"ok"</span>: True})
    update = <span class="kw">await</span> request.json()
    job = _extract_job(update, bot_type)
    <span class="kw">await</span> redis.enqueue_job(queue_name, job)`
  },
  {
    icon: "🧾",
    name: "Дедупликация (PG)",
    file: "src/db/postgres.py:62-72",
    description: "update_id вставляется один раз, чтобы отсеять повторные доставки Telegram.",
    input: ["Целочисленный update_id из Telegram Update"],
    output: ["Булевый is_new", "Дубликаты останавливаются до постановки в очередь"],
    network: "Бинарный протокол asyncpg по TCP localhost:5432.",
    state: ["INSERT строки в processed_updates со статусом received."],
    risks: [{ level: "crash", label: "PG недоступен = update потерян" }],
    timing: "1-5ms",
    code: `<span class="kw">async def</span> mark_update_received(pool, update_id):
    row = <span class="kw">await</span> pool.fetchrow(
        <span class="str">"INSERT INTO processed_updates ... ON CONFLICT DO NOTHING RETURNING telegram_update_id"</span>,
        update_id,
    )
    <span class="kw">return</span> row <span class="kw">is not</span> None`
  },
  {
    icon: "📥",
    name: "Постановка в очередь (Redis)",
    file: "src/db/redis_client.py:32-34",
    description: "Webhook сериализует Pydantic Job и кладёт его в Redis.",
    input: ["Модель Job, сериализованная в JSON", "queue:incoming или queue:manager"],
    output: ["Job добавлен в начало Redis list через LPUSH"],
    network: "RESP-протокол по TCP localhost:6379.",
    state: ["Redis list queue:incoming получает одну JSON-запись."],
    risks: [{ level: "none", label: "Быстрая локальная запись" }],
    timing: "< 1ms",
    code: `<span class="kw">async def</span> enqueue_job(self, queue_name, job):
    payload = job.model_dump_json()
    <span class="kw">await</span> self.redis.lpush(queue_name, payload)
    <span class="kw">return</span> None`
  },
  {
    icon: "📤",
    name: "BRPOP (воркер)",
    file: "src/db/redis_client.py:36-43",
    description: "Воркер блокируется на Redis и разрушительно забирает следующий job.",
    input: ["Явного входа нет; постоянное блокирующее чтение из Redis"],
    output: ["Модель Job или None после timeout 5 секунд"],
    network: "Постоянное TCP-соединение с localhost:6379.",
    state: ["Redis удаляет job из queue:incoming при успешном BRPOP."],
    risks: [{ level: "crash", label: "Разрушительное чтение" }],
    timing: "0-5 сек",
    code: `<span class="kw">async def</span> dequeue_job(self, queue_name, timeout=<span class="num">5</span>):
    result = <span class="kw">await</span> self.redis.brpop(queue_name, timeout=timeout)
    <span class="kw">if not</span> result:
        <span class="kw">return</span> None
    _, payload = result
    <span class="kw">return</span> Job.model_validate_json(payload)`
  },
  {
    icon: "🔐",
    name: "Пользовательский lock (Redis)",
    file: "src/db/redis_client.py:45-47",
    description: "Lock на chat_id не даёт параллельно запускать LLM/render для одного пользователя.",
    input: ["chat_id из Job"],
    output: ["Булевый результат захвата lock"],
    network: "Redis SET NX EX on localhost.",
    state: ["SET lock:user:{chat_id} 1 NX EX 180"],
    risks: [{ level: "timeout", label: "TTL может истечь" }, { level: "crash", label: "Drop после 5 retry" }],
    timing: "< 1ms",
    code: `<span class="kw">async def</span> acquire_user_lock(self, chat_id, ttl=<span class="num">180</span>):
    key = <span class="str">f"lock:user:{chat_id}"</span>
    acquired = <span class="kw">await</span> self.redis.set(key, <span class="str">"1"</span>, nx=True, ex=ttl)
    <span class="kw">return</span> bool(acquired)`
  },
  {
    icon: "🗃️",
    name: "Загрузка состояния (PG)",
    file: "src/queue/worker.py:181-186",
    description: "Воркер собирает профиль, FSM-состояние и последние сообщения перед prompt.",
    input: ["chat_id", "max_context_messages=20"],
    output: ["dict клиента", "dict conversation_state", "список истории диалога"],
    network: "3-4 последовательных asyncpg-запроса к localhost:5432.",
    state: ["Чтение clients, conversation_state, chat_messages."],
    risks: [{ level: "timeout", label: "Последовательная DB latency" }],
    timing: "3-20ms",
    code: `client = <span class="kw">await</span> postgres.get_client_by_chat_id(pg_pool, job.chat_id)
<span class="kw">if not</span> client:
    client = <span class="kw">await</span> postgres.create_client(pg_pool, job.chat_id, first_name, username)
state = <span class="kw">await</span> postgres.get_conversation_state(pg_pool, job.chat_id)
history = <span class="kw">await</span> postgres.get_chat_messages(pg_pool, job.chat_id, settings.max_context_messages)`
  },
  {
    icon: "🕒",
    name: "Загрузка слотов (PG)",
    file: "src/engine/measurement_service.py:83-129",
    description: "Воркер заранее подгружает доступные времена замеров на ближайшие три дня.",
    input: ["Текущая дата", "диапазон 3 дня", "timezone"],
    output: ["dict[str, list[str]] со свободными слотами"],
    network: "Один asyncpg-запрос в день к таблице measurements.",
    state: ["Чтение measurements, где status в scheduled/confirmed."],
    risks: [{ level: "timeout", label: "Запросы N+days" }],
    timing: "3-30ms",
    code: `<span class="kw">async def</span> get_available_slots(pool, date, timezone, duration_minutes=<span class="num">60</span>):
    rows = <span class="kw">await</span> pool.fetch(
        <span class="str">"SELECT scheduled_time, duration_minutes FROM measurements WHERE status IN (...)"</span>,
        day_start,
    )
    <span class="kw">return</span> free_slots`
  },
  {
    icon: "🧠",
    name: "Сборка prompt",
    file: "src/llm/prompt_builder.py:86-185",
    description: "Чистая функция собирает роль, tools, FSM, слоты, историю и текст пользователя.",
    input: ["текст пользователя", "client", "state", "history", "available slots"],
    output: ["Строка prompt примерно на 2000-5000 символов"],
    network: "Нет. Чистая CPU-работа внутри процесса воркера.",
    state: ["Изменений состояния нет."],
    risks: [{ level: "none", label: "Чистая функция" }],
    timing: "< 1ms",
    code: `<span class="kw">def</span> build_prompt(user_message, client_profile, conversation_state, chat_messages, available_slots=None):
    state = conversation_state <span class="kw">or</span> {<span class="str">"mode"</span>: <span class="str">"idle"</span>}
    history_lines = [...]
    <span class="kw">return</span> <span class="str">f"""Ты — умный консультант...</span>{tools}{slots}{user_message}<span class="str">"""</span>`
  },
  {
    icon: "🤖",
    name: "Gemini CLI (subprocess)",
    file: "src/llm/executor.py:81-135",
    description: "Воркер запускает gemini, передаёт prompt через stdin и держит жёсткий timeout.",
    input: ["Строка prompt через stdin pipe"],
    output: ["Очищенная строка stdout; ожидается JSON"],
    network: "Дочерний процесс ходит по HTTPS к generativelanguage.googleapis.com, OAuth берётся из ~/.gemini/.",
    state: ["Счётчик semaphore в памяти: максимум 2 одновременных LLM-вызова."],
    risks: [{ level: "timeout", label: "Жёсткий timeout 90 сек" }, { level: "crash", label: "Истёк OAuth" }],
    timing: "5-90 сек",
    code: `proc = <span class="kw">await</span> asyncio.create_subprocess_exec(
    settings.llm_cli_command,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,
)
stdout, stderr = <span class="kw">await</span> asyncio.wait_for(proc.communicate(prompt.encode()), timeout=timeout)`
  },
  {
    icon: "🧩",
    name: "Парсинг ответа",
    file: "src/llm/actions_parser.py:90-99",
    description: "Парсер достаёт JSON из сырого LLM output и валидирует контракты actions.",
    input: ["Сырая строка stdout от LLM"],
    output: ["ActionsJson или fallback-ответ"],
    network: "Нет. CPU-парсинг и Pydantic-валидация.",
    state: ["Durable state не меняется. Невалидный output превращается в fallback."],
    risks: [{ level: "none", label: "Не выбрасывает исключения" }],
    timing: "< 1ms",
    code: `<span class="kw">def</span> parse_actions(raw_output):
    <span class="kw">try</span>:
        data = json.loads(raw_output)
    <span class="kw">except</span> Exception:
        data = _extract_json(raw_output)
    <span class="kw">return</span> ActionsJson(**data)`
  },
  {
    icon: "⚙️",
    name: "Применение actions",
    file: "src/llm/actions_applier.py:24-143",
    description: "Валидные actions меняют state, рендерят изображения, создают заказы или замеры.",
    input: ["ActionsJson", "chat_id", "state", "pg_pool"],
    output: ["render_paths", "price", "metadata замера/заказа"],
    network: "Записи в PostgreSQL, опциональные уведомления менеджерам в Telegram, thread executor для renderer.",
    state: ["UPSERT conversation_state", "INSERT orders/measurements", "UPDATE clients."],
    risks: [{ level: "crash", label: "У render нет timeout" }],
    timing: "1-30 сек",
    code: `<span class="kw">if</span> actions.actions.get(<span class="str">"render_partition"</span>):
    params = RenderPartitionAction(**actions.actions[<span class="str">"render_partition"</span>])
    render_result = <span class="kw">await</span> render_partition(params, request_id, settings)
    price = calculate_price(**params.model_dump())
    order = <span class="kw">await</span> postgres.create_order(pg_pool, request_id, chat_id, details, paths, price)`
  },
  {
    icon: "📡",
    name: "Отправка ответа (TG API)",
    file: "src/queue/worker.py:196-203",
    description: "Воркер записывает outbound event, отправляет запрос в Telegram API и помечает событие sent.",
    input: ["reply_text", "опциональные пути к render images"],
    output: ["Ответ Telegram message/photo"],
    network: "HTTPS POST to api.telegram.org:443.",
    state: ["INSERT outbound_events pending", "UPDATE outbound_events sent."],
    risks: [{ level: "crash", label: "Дубликат, если send успешен, а DB update упал" }],
    timing: "100-500ms",
    code: `event_id = <span class="kw">await</span> postgres.insert_outbound_event(pg_pool, chat_id=chat_id, reply_text=text)
<span class="kw">await</span> sender.send_message(token, chat_id, text, reply_markup=reply_markup)
<span class="kw">await</span> postgres.mark_outbound_sent(pg_pool, event_id)`
  },
  {
    icon: "💾",
    name: "Сохранение истории (PG)",
    file: "src/db/postgres.py:194-200",
    description: "Сообщения пользователя и ассистента добавляются в историю диалога.",
    input: ["текст пользователя", "ответ ассистента", "update_id"],
    output: ["Две строки chat_messages", "processed_updates переведён в completed"],
    network: "asyncpg-записи через localhost:5432.",
    state: ["INSERT chat_messages x2", "UPDATE processed_updates status='completed'."],
    risks: [{ level: "timeout", label: "Поздний DB failure пометит job failed" }],
    timing: "2-10ms",
    code: `<span class="kw">await</span> postgres.insert_chat_message(pg_pool, job.chat_id, <span class="str">"user"</span>, job.text)
<span class="kw">await</span> postgres.insert_chat_message(pg_pool, job.chat_id, <span class="str">"assistant"</span>, parsed.reply_text)
<span class="kw">await</span> postgres.mark_update_status(pg_pool, job.update_id, <span class="str">"completed"</span>)`
  },
  {
    icon: "🔓",
    name: "Освобождение lock",
    file: "src/db/redis_client.py:49-50",
    description: "Пользовательский Redis lock удаляется в finally-блоке после обработки.",
    input: ["chat_id"],
    output: ["Количество удалённых ключей Redis DEL"],
    network: "Redis DEL over localhost:6379.",
    state: ["Удаляется lock:user:{chat_id}."],
    risks: [{ level: "none", label: "Очистка в finally" }],
    timing: "< 1ms",
    code: `<span class="kw">finally</span>:
    <span class="kw">await</span> redis_client.release_user_lock(job.chat_id)

<span class="kw">async def</span> release_user_lock(self, chat_id):
    <span class="kw">await</span> self.redis.delete(<span class="str">f"lock:user:{chat_id}"</span>)`
  },
  {
    icon: "🔁",
    name: "Outbox Dispatcher",
    file: "src/queue/outbox_dispatcher.py:15-43",
    description: "Фоновая задача повторяет отправку pending outbound events каждые 15 секунд.",
    input: ["pending строки outbound_events, где attempts < 5"],
    output: ["статус sent или failed"],
    network: "Polling PostgreSQL плюс повторная отправка в Telegram по HTTPS.",
    state: ["UPDATE attempts/last_attempt_at/error_message или status='failed'."],
    risks: [{ level: "timeout", label: "At-least-once доставка" }],
    timing: "интервал polling 15 сек",
    code: `<span class="kw">while</span> True:
    events = <span class="kw">await</span> postgres.get_pending_outbound(pg_pool, limit=<span class="num">20</span>)
    <span class="kw">for</span> event <span class="kw">in</span> events:
        <span class="kw">await</span> _dispatch_event(event, sender)
    <span class="kw">await</span> asyncio.sleep(<span class="num">15</span>)`
  }
];

const vulnerabilities = [
  {
    id: "v1",
    severity: "critical",
    severityLabel: "CRITICAL",
    title: "V1 Worker crash after BRPOP",
    subtitle: "BRPOP удаляет job из очереди до того, как обработка стала durable.",
    affectedHops: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    userSees: "Клиент отправил сообщение, Telegram получил HTTP 200, но в чате больше ничего не происходит. Повторная доставка не придёт, потому что update уже принят webhook.",
    fix: "Phase 6.1 заменил разрушительный BRPOP на safe queue processing: job переносится в processing list, имеет ack/requeue и восстанавливается после падения воркера.",
    before: ["BRPOP", "job удалён", "worker crash", "тишина"],
    after: ["BLMOVE", "processing list", "recovery", "retry"],
    cascade: [
      {
        hop: 4,
        status: "trigger",
        label: "BRPOP забрал job",
        note: "Redis уже удалил задачу из queue:incoming, но воркер ещё не зафиксировал прогресс в durable storage."
      },
      {
        hop: 5,
        status: "orphan",
        label: "Lock остаётся без результата",
        note: "Если процесс умер после lock, пользователь временно заблокирован TTL-ключом без активной обработки."
      },
      {
        hop: "6-13",
        status: "dead",
        label: "Вся бизнес-цепочка пропущена",
        note: "Состояние, prompt, Gemini, actions, Telegram send и история не выполняются."
      },
      {
        hop: 15,
        status: "dead",
        label: "Outbox не поможет",
        note: "Outbound event не создан, поэтому dispatcher не знает, что нужно повторять."
      }
    ]
  },
  {
    id: "v2",
    severity: "critical",
    severityLabel: "CRITICAL",
    title: "V2 Redis disconnect kills all tasks",
    subtitle: "Разрыв Redis-соединения мог завершить worker loop и оставить систему без потребителя очереди.",
    affectedHops: [3, 4, 5, 14],
    userSees: "Новые сообщения принимаются webhook, но ответы не приходят. Очередь растёт, а обработчик фактически умер.",
    fix: "Phase 6.2 добавил reconnect/backoff loop и изоляцию ошибок Redis: временный обрыв не убивает worker tasks, соединение пересоздаётся.",
    before: ["Redis error", "task died", "queue grows", "no replies"],
    after: ["Redis error", "backoff", "reconnect", "continue"],
    cascade: [
      {
        hop: 3,
        status: "blocked",
        label: "Webhook пишет в Redis",
        note: "Если Redis кратко недоступен, новые jobs могут не попасть в очередь с первого раза."
      },
      {
        hop: 4,
        status: "dead",
        label: "BRPOP loop падает",
        note: "Исключение из Redis-клиента завершало основной цикл чтения без восстановления."
      },
      {
        hop: 5,
        status: "skip",
        label: "Locks не обновляются",
        note: "Новые пользовательские locks не ставятся, старые могут жить до TTL."
      },
      {
        hop: 14,
        status: "skip",
        label: "Release lock не вызывается",
        note: "Если воркер упал посреди обработки, finally не гарантирует восстановление всей очереди."
      }
    ]
  },
  {
    id: "v3",
    severity: "serious",
    severityLabel: "SERIOUS",
    title: "V3 3D render hangs forever",
    subtitle: "Синхронный pyrender/trimesh мог зависнуть в thread executor без верхнего лимита времени.",
    affectedHops: [10, 11, 12, 13, 14],
    userSees: "После подтверждения рендера бот долго показывает ожидание, затем перестаёт отвечать на новые сообщения этого клиента.",
    fix: "Phase 6.3 добавил render timeout, отдельную отмену результата и понятный fallback для клиента с освобождением пользовательского lock.",
    before: ["actions", "render hangs", "lock held", "no send"],
    after: ["actions", "timeout", "fallback", "lock released"],
    cascade: [
      {
        hop: 10,
        status: "trigger",
        label: "render_partition стартует",
        note: "Actions applier запускает CPU-bound renderer в thread pool."
      },
      {
        sideEffect: "thread_pool",
        status: "blocked",
        label: "Thread pool занят",
        note: "Зависшая задача удерживает поток и может снизить пропускную способность следующих рендеров."
      },
      {
        hop: 11,
        status: "dead",
        label: "Ответ не отправлен",
        note: "До Telegram send выполнение не доходит, поэтому клиент не получает ни изображения, ни ошибку."
      },
      {
        sideEffect: "user_lock",
        status: "orphan",
        label: "User lock держится",
        note: "Пока корутина ждёт рендер, последующие сообщения того же chat_id переоткладываются."
      },
      {
        hop: 14,
        status: "dead",
        label: "Release задержан",
        note: "Lock освобождается только после возврата из зависшего рендера, которого может не быть."
      }
    ]
  },
  {
    id: "v4",
    severity: "serious",
    severityLabel: "SERIOUS",
    title: "V4 Gemini OAuth expired",
    subtitle: "Истёкший OAuth у Gemini CLI превращал LLM output в ошибку, которую пользователь видел как общий сбой.",
    affectedHops: [8, 9, 10, 11, 13],
    userSees: "Бот отвечает общей ошибкой или просит повторить, хотя проблема не в параметрах клиента, а в авторизации Gemini на сервере.",
    fix: "Phase 6.4 добавил классификацию Gemini auth failures, health check для OAuth и явный manager alert вместо немого деградационного ответа.",
    before: ["prompt", "OAuth expired", "bad stdout", "fallback"],
    after: ["health check", "auth alert", "clear fallback", "ops action"],
    cascade: [
      {
        hop: 8,
        status: "trigger",
        label: "Gemini CLI запускается",
        note: "Subprocess стартует нормально, но CLI не может получить валидные credentials."
      },
      {
        hop: 9,
        status: "garbage",
        label: "Парсер получает не JSON",
        note: "stdout/stderr содержит auth error вместо JSON-контракта actions."
      },
      {
        hop: 10,
        status: "skip",
        label: "Actions не применяются",
        note: "Рендер, запись заказа и замер не запускаются, потому что валидных actions нет."
      },
      {
        hop: 11,
        status: "degraded",
        label: "Клиент получает fallback",
        note: "Ответ технически отправляется, но не решает задачу клиента."
      },
      {
        hop: 13,
        status: "degraded",
        label: "История загрязняется",
        note: "В чат-историю попадает fallback, который в следующих prompt может мешать диалогу."
      }
    ]
  },
  {
    id: "v5",
    severity: "serious",
    severityLabel: "SERIOUS",
    title: "V5 Outbox duplicates messages",
    subtitle: "Если Telegram send прошёл, а mark_outbound_sent упал, dispatcher мог отправить то же сообщение повторно.",
    affectedHops: [11, 15],
    userSees: "Клиент или менеджер получает одинаковый ответ дважды: например, два подтверждения или два комплекта уведомлений.",
    fix: "Phase 6.5 добавил idempotency на уровне outbound_events: send_result/message_id сохраняется, retry проверяет завершённые попытки и не дублирует уже отправленное.",
    before: ["send ok", "DB mark failed", "pending", "duplicate send"],
    after: ["send ok", "message_id saved", "idempotent retry", "no duplicate"],
    cascade: [
      {
        hop: 11,
        status: "trigger",
        label: "Telegram принял send",
        note: "Сообщение уже доставлено во внешний мир, но локальная транзакция ещё не завершена."
      },
      {
        hop: 11,
        status: "orphan",
        label: "mark_outbound_sent падает",
        note: "Outbound event остаётся pending, хотя Telegram message уже существует."
      },
      {
        hop: 15,
        status: "duplicate",
        label: "Dispatcher повторяет pending",
        note: "Фоновый retry видит старый статус и отправляет тот же payload повторно."
      }
    ]
  }
];

const flowGrid = document.getElementById("flow-grid");
const detailPanel = document.getElementById("detail-panel");
const svg = document.getElementById("connector-svg");
const progressBar = document.getElementById("progress-bar");
const playToggle = document.getElementById("play-toggle");
const prevButton = document.getElementById("prev-hop");
const nextButton = document.getElementById("next-hop");
const pageTabs = [...document.querySelectorAll(".page-tab")];
const tabPanels = [...document.querySelectorAll("[data-tab-panel]")];
const vulnerabilityList = document.getElementById("vulnerability-list");

let activeIndex = 0;
let activeTab = "flow";
let expandedVulnIndex = 0;
let playTimer = null;
let suppressObserverUntil = 0;

function renderNodes() {
  flowGrid.innerHTML = "";
  hops.forEach((hop, index) => {
    const button = document.createElement("button");
    button.className = "hop-card";
    button.type = "button";
    button.dataset.index = String(index);
    button.innerHTML = `
      <span class="hop-index"><span class="hop-icon">${hop.icon}</span>Шаг ${index + 1}</span>
      <span class="hop-name">${hop.name}</span>
      <p class="hop-description">${hop.description}</p>
    `;
    button.addEventListener("click", () => selectHop(index, true));
    flowGrid.appendChild(button);
  });
}

function list(items) {
  return `<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>`;
}

function riskBadges(risks) {
  return risks
    .map((risk) => `<span class="risk-badge risk-${risk.level}">${risk.label}</span>`)
    .join("");
}

function statusLabel(status) {
  const labels = {
    blocked: "blocked",
    dead: "dead",
    degraded: "degraded",
    duplicate: "duplicate",
    garbage: "garbage",
    orphan: "orphan",
    skip: "skip",
    trigger: "trigger"
  };
  return labels[status] || status;
}

function hopTitle(hop) {
  if (typeof hop === "number") {
    return `Шаг ${hop}: ${hops[hop - 1]?.name || "неизвестно"}`;
  }
  return `Шаги ${hop}`;
}

function hopButton(step) {
  if (typeof step.hop === "number") {
    return `<button class="cascade-hop-button" type="button" data-jump-hop="${step.hop}">${hopTitle(step.hop)}</button>`;
  }
  if (step.hop) {
    return `<span>${hopTitle(step.hop)}</span>`;
  }
  return `<span>${step.sideEffect === "thread_pool" ? "Thread pool" : "User lock"}</span>`;
}

function renderHopMap(affectedHops) {
  return `
    <div class="vuln-hop-map" aria-label="Карта затронутых шагов">
      ${hops
        .map((_, index) => {
          const hopNumber = index + 1;
          const isAffected = affectedHops.includes(hopNumber);
          return `<span class="vuln-hop-cell${isAffected ? " is-affected" : ""}">${hopNumber}</span>`;
        })
        .join("")}
    </div>
  `;
}

function renderTimeline(vulnerability) {
  return `
    <div class="cascade-timeline">
      ${vulnerability.cascade
        .map(
          (step, index) => `
            <div class="cascade-step" style="--i: ${index}">
              <span class="cascade-dot" aria-hidden="true"></span>
              <div class="cascade-card">
                <div class="cascade-heading">
                  ${hopButton(step)}
                  <span class="status-chip status-${step.status}">${statusLabel(step.status)}</span>
                </div>
                <p class="cascade-note"><b>${step.label}.</b> ${step.note}</p>
              </div>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function miniFlowRow(items, tone) {
  return `
    <div class="mini-flow-row">
      ${items
        .map(
          (item, index) => `
            <span class="mini-flow-node ${tone}">${item}</span>
            ${index < items.length - 1 ? '<span class="mini-flow-arrow">→</span>' : ""}
          `
        )
        .join("")}
    </div>
  `;
}

function renderVulnerabilityCard(vulnerability, index) {
  const expanded = index === expandedVulnIndex;
  return `
    <article class="vuln-card${expanded ? " is-expanded" : ""}" data-vuln-index="${index}">
      <button
        class="vuln-toggle"
        type="button"
        aria-expanded="${expanded ? "true" : "false"}"
        aria-controls="vuln-expand-${vulnerability.id}"
      >
        <span class="severity-dot severity-${vulnerability.severity}" aria-label="${vulnerability.severityLabel}"></span>
        <span>
          <span class="vuln-title">${vulnerability.title} · ${vulnerability.severityLabel}</span>
          <span class="vuln-subtitle">${vulnerability.subtitle}</span>
        </span>
        <span class="vuln-chevron" aria-hidden="true">›</span>
      </button>
      <div id="vuln-expand-${vulnerability.id}" class="vuln-expand">
        <div class="vuln-content">
          ${renderHopMap(vulnerability.affectedHops)}
          ${renderTimeline(vulnerability)}
          <section class="vuln-impact">
            <span class="vuln-block-label">Что видит пользователь</span>
            <div class="chat-bubble">${vulnerability.userSees}</div>
          </section>
          <section class="vuln-fix">
            <span class="vuln-block-label">Как исправлено</span>
            <p>${vulnerability.fix}</p>
          </section>
          <div class="mini-flow" aria-label="Сравнение до и после">
            <div class="mini-flow-card">
              <strong>До Phase 6</strong>
              ${miniFlowRow(vulnerability.before, "bad")}
            </div>
            <div class="mini-flow-card">
              <strong>После Phase 6</strong>
              ${miniFlowRow(vulnerability.after, "good")}
            </div>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderVulnerabilities() {
  vulnerabilityList.innerHTML = vulnerabilities.map(renderVulnerabilityCard).join("");
}

function detailMarkup(hop, index) {
  return `
    <div class="detail-kicker">Шаг ${index + 1}</div>
    <h2 class="detail-title">${hop.name}</h2>
    <div class="file-ref">${hop.file}</div>
    <div class="detail-grid">
      <section class="detail-section">
        <h3>Вход / выход</h3>
        ${list([`Вход: ${hop.input.join("; ")}`, `Выход: ${hop.output.join("; ")}`])}
      </section>
      <section class="detail-section">
        <h3>Сеть / IPC</h3>
        <p>${hop.network}</p>
      </section>
      <section class="detail-section">
        <h3>Фрагмент кода</h3>
        <pre class="code-block"><code>${hop.code}</code></pre>
      </section>
      <section class="detail-section">
        <h3>Изменения состояния</h3>
        ${list(hop.state)}
      </section>
      <section class="detail-section">
        <h3>Риски / время</h3>
        <div class="badge-row">${riskBadges(hop.risks)}<span class="timing-badge">${hop.timing}</span></div>
      </section>
    </div>
  `;
}

function mobileDetailSlot() {
  let slot = document.querySelector(".mobile-detail-slot");
  if (!slot) {
    slot = document.createElement("div");
    slot.className = "mobile-detail-slot";
  }
  return slot;
}

function selectHop(index, shouldScroll = false) {
  activeIndex = Math.max(0, Math.min(index, hops.length - 1));
  if (shouldScroll) {
    suppressObserverUntil = Date.now() + 900;
  }
  const cards = [...document.querySelectorAll(".hop-card")];
  cards.forEach((card, cardIndex) => {
    card.classList.toggle("is-active", cardIndex === activeIndex);
    card.classList.toggle("is-done", cardIndex < activeIndex);
  });

  detailPanel.classList.add("is-changing");
  window.setTimeout(() => {
    const markup = detailMarkup(hops[activeIndex], activeIndex);
    detailPanel.innerHTML = markup;
    const slot = mobileDetailSlot();
    slot.innerHTML = markup;
    cards[activeIndex].after(slot);
    detailPanel.classList.remove("is-changing");
  }, 120);

  progressBar.style.width = `${((activeIndex + 1) / hops.length) * 100}%`;
  drawConnectors();

  if (shouldScroll && window.matchMedia("(max-width: 767px)").matches) {
    cards[activeIndex].scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function switchTab(tabName) {
  activeTab = tabName;
  pageTabs.forEach((tab) => {
    const isActive = tab.dataset.tab === tabName;
    tab.classList.toggle("is-active", isActive);
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  tabPanels.forEach((panel) => {
    const isActive = panel.dataset.tabPanel === tabName;
    panel.hidden = !isActive;
    panel.classList.toggle("is-active", isActive);
  });
  document.body.classList.toggle("is-vulns", tabName === "vulns");
  if (tabName === "flow") {
    window.setTimeout(drawConnectors, 50);
  } else if (playTimer) {
    setPlaying(false);
  }
}

function setExpandedVulnerability(index) {
  expandedVulnIndex = index;
  document.querySelectorAll(".vuln-card").forEach((card, cardIndex) => {
    const isExpanded = cardIndex === expandedVulnIndex;
    card.classList.toggle("is-expanded", isExpanded);
    card.querySelector(".vuln-toggle")?.setAttribute("aria-expanded", isExpanded ? "true" : "false");
  });
}

function jumpToHop(hopNumber) {
  switchTab("flow");
  window.setTimeout(() => {
    selectHop(hopNumber - 1, true);
    document.querySelector(".hop-card.is-active")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 80);
}

function centerOf(element, rootBox) {
  const box = element.getBoundingClientRect();
  return {
    x: box.left - rootBox.left + box.width / 2,
    y: box.top - rootBox.top + box.height / 2
  };
}

function pathBetween(a, b) {
  const dx = Math.abs(b.x - a.x);
  const mid = Math.max(34, dx * 0.35);
  return `M ${a.x} ${a.y} C ${a.x + mid} ${a.y}, ${b.x - mid} ${b.y}, ${b.x} ${b.y}`;
}

function drawConnectors() {
  if (activeTab !== "flow") {
    return;
  }

  if (window.matchMedia("(max-width: 767px)").matches) {
    svg.innerHTML = "";
    return;
  }

  const shell = document.querySelector(".diagram-shell");
  const cards = [...document.querySelectorAll(".hop-card")];
  const rootBox = shell.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${rootBox.width} ${rootBox.height}`);
  svg.innerHTML = "";

  for (let i = 1; i < cards.length; i += 1) {
    const from = centerOf(cards[i - 1], rootBox);
    const to = centerOf(cards[i], rootBox);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathBetween(from, to));
    path.setAttribute("class", `connector-line${i === activeIndex ? " is-active" : ""}`);
    path.setAttribute("id", `connector-${i}`);
    svg.appendChild(path);

    if (i === activeIndex) {
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("r", "4");
      dot.setAttribute("class", "pulse-dot");
      const motion = document.createElementNS("http://www.w3.org/2000/svg", "animateMotion");
      motion.setAttribute("dur", "900ms");
      motion.setAttribute("repeatCount", "indefinite");
      motion.setAttribute("path", pathBetween(from, to));
      dot.appendChild(motion);
      svg.appendChild(dot);
    }
  }
}

function setPlaying(nextPlaying) {
  if (nextPlaying) {
    playToggle.textContent = "Пауза";
    playTimer = window.setInterval(() => {
      selectHop((activeIndex + 1) % hops.length, true);
    }, 3000);
  } else {
    playToggle.textContent = "Старт";
    window.clearInterval(playTimer);
    playTimer = null;
  }
}

function wireControls() {
  playToggle.addEventListener("click", () => setPlaying(!playTimer));
  prevButton.addEventListener("click", () => selectHop(activeIndex - 1, true));
  nextButton.addEventListener("click", () => selectHop(activeIndex + 1, true));

  pageTabs.forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  vulnerabilityList.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
    if (!target) return;

    const toggle = target.closest(".vuln-toggle");
    if (toggle) {
      const card = toggle.closest(".vuln-card");
      setExpandedVulnerability(Number(card.dataset.vulnIndex));
      return;
    }

    const jumpButton = target.closest("[data-jump-hop]");
    if (jumpButton) {
      jumpToHop(Number(jumpButton.dataset.jumpHop));
    }
  });

  vulnerabilityList.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
    const toggle = target?.closest(".vuln-toggle");
    if (!toggle) return;
    event.preventDefault();
    const card = toggle.closest(".vuln-card");
    setExpandedVulnerability(Number(card.dataset.vulnIndex));
  });

  window.addEventListener("keydown", (event) => {
    if (activeTab !== "flow") return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      selectHop(activeIndex + 1, true);
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      selectHop(activeIndex - 1, true);
    }
    if (event.code === "Space") {
      event.preventDefault();
      setPlaying(!playTimer);
    }
  });

  window.addEventListener("resize", drawConnectors);
}

function observeMobileScroll() {
  const observer = new IntersectionObserver(
    (entries) => {
      if (!window.matchMedia("(max-width: 767px)").matches) return;
      if (Date.now() < suppressObserverUntil) return;
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) {
        selectHop(Number(visible.target.dataset.index), false);
      }
    },
    { threshold: [0.55, 0.75] }
  );

  document.querySelectorAll(".hop-card").forEach((card) => observer.observe(card));
}

renderNodes();
renderVulnerabilities();
wireControls();
selectHop(0);
observeMobileScroll();
window.setTimeout(drawConnectors, 50);
