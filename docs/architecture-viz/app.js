const hops = [
  {
    icon: "📨",
    name: "Telegram POST",
    file: "src/bot/webhook.py:50-85",
    description: "Telegram delivers the raw Update to aiohttp over HTTPS.",
    input: ["HTTPS POST from Telegram servers to 0.0.0.0:88", "JSON Telegram Update payload", "X-Telegram-Bot-Api-Secret-Token header"],
    output: ["Parsed chat_id, user_id, text, msg_type, callback_data", "Always returns HTTP 200"],
    network: "TLS with self-signed cert, TCP port 88, aiohttp request handler.",
    state: ["No durable state yet; raw payload is only in process memory."],
    risks: [{ level: "none", label: "Errors swallowed" }],
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
    name: "Dedup (PG)",
    file: "src/db/postgres.py:62-72",
    description: "The update_id is inserted once to reject duplicate Telegram retries.",
    input: ["update_id integer from Telegram Update"],
    output: ["is_new boolean", "Duplicate updates stop before enqueue"],
    network: "asyncpg binary protocol over TCP localhost:5432.",
    state: ["INSERT row into processed_updates with status='received'."],
    risks: [{ level: "crash", label: "PG down = update lost" }],
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
    name: "Enqueue (Redis)",
    file: "src/db/redis_client.py:32-34",
    description: "The webhook serializes the Pydantic Job and pushes it to Redis.",
    input: ["Job model serialized to JSON", "queue:incoming or queue:manager"],
    output: ["Job appended to Redis list head via LPUSH"],
    network: "RESP protocol over TCP localhost:6379.",
    state: ["Redis list queue:incoming receives one JSON entry."],
    risks: [{ level: "none", label: "Fast local write" }],
    timing: "< 1ms",
    code: `<span class="kw">async def</span> enqueue_job(self, queue_name, job):
    payload = job.model_dump_json()
    <span class="kw">await</span> self.redis.lpush(queue_name, payload)
    <span class="kw">return</span> None`
  },
  {
    icon: "📤",
    name: "BRPOP (Worker)",
    file: "src/db/redis_client.py:36-43",
    description: "The worker blocks on Redis and destructively removes the next job.",
    input: ["No explicit input; persistent blocking Redis read"],
    output: ["Job model or None after 5s timeout"],
    network: "Persistent TCP connection to localhost:6379.",
    state: ["Redis removes the job from queue:incoming on successful BRPOP."],
    risks: [{ level: "crash", label: "Destructive dequeue" }],
    timing: "0-5s",
    code: `<span class="kw">async def</span> dequeue_job(self, queue_name, timeout=<span class="num">5</span>):
    result = <span class="kw">await</span> self.redis.brpop(queue_name, timeout=timeout)
    <span class="kw">if not</span> result:
        <span class="kw">return</span> None
    _, payload = result
    <span class="kw">return</span> Job.model_validate_json(payload)`
  },
  {
    icon: "🔐",
    name: "User Lock (Redis)",
    file: "src/db/redis_client.py:45-47",
    description: "A per-chat lock prevents concurrent LLM/render work for one user.",
    input: ["chat_id from Job"],
    output: ["Boolean lock acquisition result"],
    network: "Redis SET NX EX on localhost.",
    state: ["SET lock:user:{chat_id} 1 NX EX 180"],
    risks: [{ level: "timeout", label: "TTL can expire" }, { level: "crash", label: "Dropped after 5 retries" }],
    timing: "< 1ms",
    code: `<span class="kw">async def</span> acquire_user_lock(self, chat_id, ttl=<span class="num">180</span>):
    key = <span class="str">f"lock:user:{chat_id}"</span>
    acquired = <span class="kw">await</span> self.redis.set(key, <span class="str">"1"</span>, nx=True, ex=ttl)
    <span class="kw">return</span> bool(acquired)`
  },
  {
    icon: "🗃️",
    name: "Load State (PG)",
    file: "src/queue/worker.py:181-186",
    description: "Worker gathers profile, FSM state, and recent history before prompting.",
    input: ["chat_id", "max_context_messages=20"],
    output: ["client dict", "conversation_state dict", "chat history list"],
    network: "3-4 sequential asyncpg queries over localhost:5432.",
    state: ["Reads clients, conversation_state, chat_messages."],
    risks: [{ level: "timeout", label: "Sequential DB latency" }],
    timing: "3-20ms",
    code: `client = <span class="kw">await</span> postgres.get_client_by_chat_id(pg_pool, job.chat_id)
<span class="kw">if not</span> client:
    client = <span class="kw">await</span> postgres.create_client(pg_pool, job.chat_id, first_name, username)
state = <span class="kw">await</span> postgres.get_conversation_state(pg_pool, job.chat_id)
history = <span class="kw">await</span> postgres.get_chat_messages(pg_pool, job.chat_id, settings.max_context_messages)`
  },
  {
    icon: "🕒",
    name: "Load Slots (PG)",
    file: "src/engine/measurement_service.py:83-129",
    description: "The worker preloads available measurement times for the next three days.",
    input: ["Current date", "3-day range", "timezone"],
    output: ["dict[str, list[str]] of available slots"],
    network: "One asyncpg query per day against measurements.",
    state: ["Reads measurements where status in scheduled/confirmed."],
    risks: [{ level: "timeout", label: "N+days queries" }],
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
    name: "Build Prompt",
    file: "src/llm/prompt_builder.py:86-185",
    description: "A pure function assembles role, tools, FSM, slots, history, and user text.",
    input: ["user text", "client", "state", "history", "available slots"],
    output: ["Prompt string around 2000-5000 chars"],
    network: "None. Pure CPU work inside worker process.",
    state: ["No state changes."],
    risks: [{ level: "none", label: "Pure function" }],
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
    description: "The worker forks gemini, streams prompt through stdin, and enforces a hard timeout.",
    input: ["Prompt string via stdin pipe"],
    output: ["Cleaned stdout string; JSON expected"],
    network: "Child process uses HTTPS to generativelanguage.googleapis.com with OAuth from ~/.gemini/.",
    state: ["Semaphore counter in memory: max 2 concurrent LLM calls."],
    risks: [{ level: "timeout", label: "90s hard timeout" }, { level: "crash", label: "OAuth expiry" }],
    timing: "5-90s",
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
    name: "Parse Response",
    file: "src/llm/actions_parser.py:90-99",
    description: "The parser recovers JSON from raw LLM output and validates action contracts.",
    input: ["Raw LLM stdout string"],
    output: ["ActionsJson or fallback reply"],
    network: "None. Pure CPU parse and Pydantic validation.",
    state: ["No durable state. Invalid output becomes fallback."],
    risks: [{ level: "none", label: "Never raises" }],
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
    name: "Apply Actions",
    file: "src/llm/actions_applier.py:24-143",
    description: "Validated actions mutate state, render images, create orders, or schedule measurements.",
    input: ["ActionsJson", "chat_id", "state", "pg_pool"],
    output: ["render_paths", "price", "measurement/order metadata"],
    network: "PostgreSQL writes, optional Telegram manager notification, thread executor for renderer.",
    state: ["UPSERT conversation_state", "INSERT orders/measurements", "UPDATE clients."],
    risks: [{ level: "crash", label: "Render has no timeout" }],
    timing: "1-30s",
    code: `<span class="kw">if</span> actions.actions.get(<span class="str">"render_partition"</span>):
    params = RenderPartitionAction(**actions.actions[<span class="str">"render_partition"</span>])
    render_result = <span class="kw">await</span> render_partition(params, request_id, settings)
    price = calculate_price(**params.model_dump())
    order = <span class="kw">await</span> postgres.create_order(pg_pool, request_id, chat_id, details, paths, price)`
  },
  {
    icon: "📡",
    name: "Send Reply (TG API)",
    file: "src/queue/worker.py:196-203",
    description: "The worker records an outbound event, sends Telegram API request, then marks sent.",
    input: ["reply_text", "optional render image paths"],
    output: ["Telegram message/photo response"],
    network: "HTTPS POST to api.telegram.org:443.",
    state: ["INSERT outbound_events pending", "UPDATE outbound_events sent."],
    risks: [{ level: "crash", label: "Duplicate if send succeeds but DB update fails" }],
    timing: "100-500ms",
    code: `event_id = <span class="kw">await</span> postgres.insert_outbound_event(pg_pool, chat_id=chat_id, reply_text=text)
<span class="kw">await</span> sender.send_message(token, chat_id, text, reply_markup=reply_markup)
<span class="kw">await</span> postgres.mark_outbound_sent(pg_pool, event_id)`
  },
  {
    icon: "💾",
    name: "Save History (PG)",
    file: "src/db/postgres.py:194-200",
    description: "The user and assistant messages are appended to chat history.",
    input: ["user text", "assistant reply", "update_id"],
    output: ["Two chat_messages rows", "processed_updates completed"],
    network: "asyncpg writes over localhost:5432.",
    state: ["INSERT chat_messages x2", "UPDATE processed_updates status='completed'."],
    risks: [{ level: "timeout", label: "Late DB failure marks job failed" }],
    timing: "2-10ms",
    code: `<span class="kw">await</span> postgres.insert_chat_message(pg_pool, job.chat_id, <span class="str">"user"</span>, job.text)
<span class="kw">await</span> postgres.insert_chat_message(pg_pool, job.chat_id, <span class="str">"assistant"</span>, parsed.reply_text)
<span class="kw">await</span> postgres.mark_update_status(pg_pool, job.update_id, <span class="str">"completed"</span>)`
  },
  {
    icon: "🔓",
    name: "Release Lock",
    file: "src/db/redis_client.py:49-50",
    description: "The per-user Redis lock is removed in a finally block after processing.",
    input: ["chat_id"],
    output: ["Redis DEL count"],
    network: "Redis DEL over localhost:6379.",
    state: ["Deletes lock:user:{chat_id}."],
    risks: [{ level: "none", label: "finally cleanup" }],
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
    description: "A background task retries pending outbound events every 15 seconds.",
    input: ["pending outbound_events rows where attempts < 5"],
    output: ["sent or failed status"],
    network: "PostgreSQL polling plus Telegram HTTPS send retry.",
    state: ["UPDATE attempts/last_attempt_at/error_message or status='failed'."],
    risks: [{ level: "timeout", label: "At-least-once delivery" }],
    timing: "15s poll interval",
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
      <span class="hop-index"><span class="hop-icon">${hop.icon}</span>HOP ${index + 1}</span>
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
    <div class="detail-kicker">Hop ${index + 1}</div>
    <h2 class="detail-title">${hop.name}</h2>
    <div class="file-ref">${hop.file}</div>
    <div class="detail-grid">
      <section class="detail-section">
        <h3>Input / Output</h3>
        ${list([`Input: ${hop.input.join("; ")}`, `Output: ${hop.output.join("; ")}`])}
      </section>
      <section class="detail-section">
        <h3>Network / IPC</h3>
        <p>${hop.network}</p>
      </section>
      <section class="detail-section">
        <h3>Code snippet</h3>
        <pre class="code-block"><code>${hop.code}</code></pre>
      </section>
      <section class="detail-section">
        <h3>State changes</h3>
        ${list(hop.state)}
      </section>
      <section class="detail-section">
        <h3>Risk / Timing</h3>
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
    playToggle.textContent = "Pause";
    playTimer = window.setInterval(() => {
      selectHop((activeIndex + 1) % hops.length, true);
    }, 3000);
  } else {
    playToggle.textContent = "Play";
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
