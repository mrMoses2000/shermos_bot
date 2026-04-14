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

const flowGrid = document.getElementById("flow-grid");
const detailPanel = document.getElementById("detail-panel");
const svg = document.getElementById("connector-svg");
const progressBar = document.getElementById("progress-bar");
const playToggle = document.getElementById("play-toggle");
const prevButton = document.getElementById("prev-hop");
const nextButton = document.getElementById("next-hop");

let activeIndex = 0;
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

  window.addEventListener("keydown", (event) => {
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
wireControls();
selectHop(0);
observeMobileScroll();
window.setTimeout(drawConnectors, 50);
