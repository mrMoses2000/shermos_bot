# Phase 4.4 — Client Case Regression Matrix (C-01..C-30)

## How to run

```bash
bash scripts/test_integration.sh tests/test_e2e_client_cases.py -v
```

Or with pytest directly on the server:

```bash
INTEGRATION_DB_DSN="postgres://..." INTEGRATION_REDIS_URL="redis://..." \
  .venv/bin/python -m pytest -m integration tests/test_e2e_client_cases.py -v
```

## Case table

| # | Test function | Strategy | Status |
|---|---|---|---|
| C-01 | `test_C01_telegram_start_command` | `/start` update → outbound greeting | PASS |
| C-02 | `test_C02_whatsapp_first_hello_from_new_number` | First WA inbound → queued in queue:incoming | PASS |
| C-03 | `test_C03_param_collection_happy_path` | LLM state_patch → conversation_state.collected_params updated | PASS |
| C-04 | `test_C04_decimal_dimensions_no_crash` | Decimal width/height → no exception, status=completed | PASS |
| C-05 | `test_C05_price_with_dot_no_crash` | Budget "1500.50" → no parse crash, status=completed | PASS |
| C-06 | `test_C06_voice_transcription_no_echo` | Voice job → transcript NOT echoed in outbound (fix 7ff1625) | PASS |
| C-07 | `test_C07_render_request_creates_order` | render_partition action → outbound produced, no crash | PASS |
| C-08 | `test_C08_schedule_measurement_happy_path` | schedule_measurement → measurements row created | PASS |
| C-09 | `test_C09_schedule_measurement_conflict` | Conflicting slot → ValueError with "занято" | PASS |
| C-10 | `test_C10_schedule_measurement_sunday` | Sunday date → ValueError with "воскресень" | PASS |
| C-11 | `test_C11_manager_meas_confirm_telegram` | Manager Telegram callback meas_confirm:N → status=confirmed | PASS |
| C-12 | `test_C12_manager_meas_confirm_whatsapp` | Manager WA allowlisted phone meas_confirm:N → status=confirmed | PASS |
| C-13 | `test_C13_auto_confirm_after_15_min` | auto_confirm_due_measurements → confirmed + manager outbox rows | PASS |
| C-14 | `test_C14_manager_meas_reject` | Manager meas_reject:N → status=rejected | PASS |
| C-15 | `test_C15_manager_alternative_time_proposal` | Manager free-text "DD.MM.YYYY в HH:MM" → slot created or outbound | PASS |
| C-16 | `test_C16_telegram_duplicate_update_id_skipped` | Same update_id twice → only 1 inbound_events row | PASS |
| C-17 | `test_C17_whatsapp_duplicate_external_id_skipped` | Same WA external_id twice → {queued:false, duplicate:true} | PASS |
| C-18 | ~~`test_C18_telegram_403_no_retry_spam`~~ | Telegram-specific test — **deleted** in Phase 10 decommission | REMOVED |
| C-19 | `test_C19_worker_recovery_after_kill_simulation` | Stuck jobs in processing queue → auto-recovered mid-loop | XFAIL |
| C-20 | `test_C20_llm_timeout_user_gets_fallback` | TimeoutError from call_llm → fallback reply sent, status=failed | PASS |
| C-21 | `test_C21_llm_garbage_no_actions_applied` | Non-JSON LLM output → parse fallback, no crash, outbound exists | PASS |
| C-22 | `test_C22_mini_app_gallery_list` | GET /api/gallery/works with initData → returns seeded works | PASS |
| C-23 | `test_C23_mini_app_telegram_init_data_auth` | Valid initData → HTTP 200, auth passes | PASS |
| C-24 | `test_C24_cms_otp_flow` | OTP send + verify → access_token returned | PASS |
| C-25 | `test_C25_otp_brute_force_blocked` | 6 wrong OTP codes → 401 or 429 | PASS |
| C-26 | `test_C26_long_dialog_memory_keeps_key_params` | 100 messages → key facts survive in memory summary | XFAIL |
| C-27 | `test_C27_reset_command_clears_state` | /reset command → state cleared | XFAIL |
| C-28 | `test_C28_off_topic_polite_refusal` | Mocked refusal reply → delivered verbatim to user | PASS |
| C-29 | `test_C29_minimal_config_pricing` | calculate_price minimal params → total_price > 0 | PASS |
| C-30 | `test_C30_concurrent_messages_serialized` | 2 concurrent jobs for same chat_id → both eventually complete | PASS |

## Known limitations (XFAIL cases)

### C-19 — Worker recovery of stuck jobs mid-loop

**Reason:** `recover_stuck_jobs` is called once at startup in `run_worker()`. If a worker
process crashes mid-job, the job remains in `queue:processing:client` until the next restart.
There is no periodic mid-loop recovery pass.

**Impact:** Production crash leaves jobs stuck until manual restart or process supervisor
restarts the worker.

**Fix location:** `src/queue/worker.py` — `_client_loop` function. Add a periodic call to
`redis_client.recover_stuck_jobs(CLIENT_PROCESSING_QUEUE, CLIENT_QUEUE)` with a timeout
(e.g., every 60 loop iterations or using a separate background task).

**Phase:** Implement in Phase 5 — operational reliability.

---

### C-26 — Long dialog memory preserves key dimension facts

**Reason:** `refresh_conversation_memory_if_needed` in `src/llm/conversation_memory.py`
summarizes by appending message text up to `MAX_SUMMARY_CHARS = 900` and then truncating
from the *left* (`summary[-MAX_SUMMARY_CHARS:]`). Early facts (width, height) inserted in
the first 1–2 messages of a 100-message dialog will be truncated once the rolling window
fills up. The `facts_json` field is updated from live `conversation_state.collected_params`
so it may survive — but the `summary_text` will lose early messages.

**Impact:** In a very long dialog, the LLM may forget dimension facts stated at the start
if the user never repeats them and if the FSM's `collected_params` was cleared mid-session.

**Fix location:** `src/llm/conversation_memory.py` — `merge_memory_summary`. Instead of
naive string concatenation + truncation, extract structured facts (height, width, shape)
from early messages and preserve them in `facts_json` regardless of summary length.

**Phase:** Implement in Phase 5 — conversation quality.

---

### C-27 — /reset command not implemented

**Reason:** `src/queue/worker.py` handles `/clear`, `/cancel`, `/status`, `/start`, `/help`,
`/examples` in `_handle_client_command`. There is no `/reset` or "начать сначала" command.
`grep -rn "/reset\|сброс\|начать сначала" src/` returns no results.

**Impact:** Users who want a "fresh start" equivalent to `/clear` have no discoverability;
`/clear` is not documented in the bot's help text.

**Fix location:** `src/queue/worker.py` — `_handle_client_command`. Add `/reset` as an
alias for `/clear` and update `CLIENT_COMMANDS["/help"]` to mention it.

**Phase:** Implement in Phase 5 — UX improvements.

---

## Notes on C-20 (LLM timeout fallback)

The `process_client_job` function in `src/queue/worker.py` catches `TimeoutError` and
sends the message:

> "Запрос занял слишком много времени. Я сохранил ваше сообщение. Напишите «продолжи», и я продолжу с него."

This means C-20 is not an xfail — the fallback exists and C-20 verifies it works correctly.
The update is marked `failed` (not `completed`) which is also tested.

## Notes on C-06 (voice echo fix 7ff1625)

The voice transcription path in `_resolve_voice_text` sets `job.text = transcript` and
`job.msg_type = "text"`, then returns `True`. The worker then calls `call_llm(prompt)` and
sends `parsed.reply_text` — NOT the raw transcript. This is the fix from commit `7ff1625`.
C-06 tests that no outbound message contains the raw transcript string.
