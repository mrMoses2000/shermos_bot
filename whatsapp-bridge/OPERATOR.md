# WhatsApp Bridge Operator Guide

This document describes how to manage and maintain the `whatsapp-bridge` service.

## Pairing

To pair the bridge with a WhatsApp account:

1. Ensure the bridge is running.
2. Send a POST request to `/pair` with the phone number in E.164 format (without `+`):
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

## Re-pairing

If the session is lost or you get a `Logged out` error in logs:

1. The bridge will exit with code 1.
2. Ensure you have the correct `BRIDGE_SHARED_SECRET`.
3. Restart the bridge.
4. Follow the **Pairing** steps again.

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
- **401 Unauthorized:** The `X-Bridge-Secret` header is missing or incorrect.
- **502 Bad Gateway:** Failed to send a message via WhatsApp (Baileys error).
- **Spooling:** If the Python ingress is down, the bridge will spool inbound messages in Redis (`bridge:spool:inbound`) and retry automatically when the connection is restored.
