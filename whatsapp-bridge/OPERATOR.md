# WhatsApp Bridge Operator Guide

This document describes how to manage and maintain the `whatsapp-bridge` service.

## Pairing

Current preferred path: QR linking. Phone-code linking is kept as a fallback because it can fail with Baileys/WhatsApp `401` or `405` during the registration handshake.

To pair the bridge with a WhatsApp account by QR:

1. Stop the systemd service for the role you are re-pairing (do NOT use `wa-bridge-stop` — that pkills BOTH client and manager bridges):
   ```bash
   sudo systemctl stop shermos-wa-client     # or shermos-wa-manager
   ```
2. Reset only the Baileys auth state for that role. Pass the role explicitly so you don't wipe the other bridge's session:
   ```bash
   ./run.sh wa-bridge-reset-auth client      # or 'manager', or 'both'
   ```
3. Start the bridge with QR output:
   ```bash
   ./run.sh wa-bridge-start-qr
   ```
4. Open WhatsApp on your phone, go to **Settings > Linked Devices > Link a Device**, and scan the QR printed in the terminal.
5. After logs show that the connection is open, Ctrl+C the QR session and bring the systemd service back up:
   ```bash
   sudo systemctl start shermos-wa-client    # or shermos-wa-manager
   ```

Fallback phone-code pairing:

1. Ensure the bridge is running.
2. Send a POST request to `/pair` with the phone number in E.164 format without `+`:
   ```bash
   curl -X POST http://localhost:3001/pair \
     -H "X-Bridge-Secret: <your_secret>" \
     -H "Content-Type: application/json" \
     -d '{"phone":"996555111222"}'
   ```
3. The response will contain an 8-character pairing code:
   ```json
   { "code": "ABCD-1234" }
   ```
4. Open WhatsApp on your phone, go to **Settings > Linked Devices > Link a Device > Link with phone number instead**, and enter the code.

If the phone-code flow returns `Couldn't link device` on the phone and logs `401` or `405`, use the QR path above.

## Re-pairing

If the session is lost or you get a `Logged out` error in logs:

1. The bridge will exit with code 1.
2. Ensure you have the correct `BRIDGE_SHARED_SECRET`.
3. Reset auth for the affected role only: `./run.sh wa-bridge-reset-auth client` (or `manager`).
4. Follow the QR **Pairing** steps above.

## Redis Auth Backup

The authentication state is stored in Redis under the prefix `baileys:auth:` (configurable via `BAILEYS_AUTH_PREFIX`).

To backup the session:
1. Export all keys matching the prefix.
2. To restore, import them back into Redis before starting the bridge.

**WARNING:** If these keys are lost, you will need to re-pair the device.

## Logout Handling

If you want to intentionally log out:
1. Use the WhatsApp mobile app to "Unlink" the device named "Shermos".
2. The bridge will detect the logout and exit.
3. Clean up Redis keys if you want to start fresh.

## Troubleshooting

- **503 Service Unavailable:** The bridge is either not initialized or lost connection to WhatsApp. Check logs for reconnection attempts.
- **401 Unauthorized on HTTP routes:** The `X-Bridge-Secret` header is missing or incorrect.
- **401/405 during Baileys login:** Phone-code pairing failed in the WhatsApp Web handshake. Reset auth and use QR pairing.
- **502 Bad Gateway:** Failed to send a message via WhatsApp (Baileys error).
- **Spooling:** If the Python ingress is down, the bridge will spool inbound messages in Redis (`bridge:spool:inbound`) and retry automatically when the connection is restored.

---

## Dual-Bot Architecture (Two WhatsApp Numbers)

### Overview

The service runs **two independent bridge instances** — one per WhatsApp number — and a single Python backend that routes messages based on sender identity.

```
Client WhatsApp → shermos-wa-client (port 3001) ──┐
                                                    ├──► POST /internal/whatsapp/inbound ──► Worker
Manager WhatsApp → shermos-wa-manager (port 3002) ─┘
```

### systemd services

| Service | EnvironmentFile | Port | BRIDGE_ROLE | BAILEYS_AUTH_PREFIX |
|---------|----------------|------|-------------|----------------------|
| `shermos-wa-client` | `whatsapp-bridge/.env` | 3001 | `client` | `baileys:auth:` |
| `shermos-wa-manager` | `whatsapp-bridge/.env.manager` | 3002 | `manager` | `baileys:auth:manager:` |

Both services run the same binary (`dist/index.js`) with different env files. Redis auth namespaces never overlap.

### Message routing logic

Every inbound message arrives at `POST /internal/whatsapp/inbound` with `bridge_role` = `client` or `manager` (set by the bridge based on `BRIDGE_ROLE` env).

The Python ingress (`src/bot/whatsapp_ingress.py`) applies this rule:

```
sender_is_staff = sender_phone ∈ MANAGER_WHATSAPP_NUMBERS
bot_type = "manager" if sender_is_staff else "client"
queue  = "queue:manager" if bot_type == "manager" else "queue:incoming"
```

Key point: **`bridge_role` tells you WHICH number the message arrived on; `bot_type` tells you WHO sent it.** A regular client writing to the manager number is valid — their message goes to `queue:incoming` as usual.

### Allowlist (staff phones)

Only phones listed in `MANAGER_WHATSAPP_NUMBERS` (env var, comma-separated E.164 digits without `+`) are treated as staff. Messages from those phones → `queue:manager`. Everyone else → `queue:incoming`, regardless of which bridge received the message.

To add a new staff number: append the E.164 digits to `MANAGER_WHATSAPP_NUMBERS` in `.env` (or the server environment) and restart the worker.

### Pairing each bridge

Pair client bridge: stop `shermos-wa-client`, run QR flow on port 3001.
Pair manager bridge: stop `shermos-wa-manager`, temporarily set `BRIDGE_PORT=3002` and run QR flow on port 3002.

See **Pairing** section above for full steps.
