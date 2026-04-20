import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  handleIncomingMessage,
  forwardToIngress,
  state,
  processNextSpoolItem
} from '../src/lib/baileys-client.js';
import RedisMock from 'ioredis-mock';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

const Redis = (RedisMock as any).default || RedisMock;
const INGRESS_URL = 'http://localhost:9443/internal/whatsapp/inbound';

const handlers = [
  http.post(INGRESS_URL, async ({ request }) => {
    return HttpResponse.json({ status: 'queued' });
  }),
];

const server = setupServer(...handlers);

describe('Inbound Messaging', () => {
  let redis: any;

  beforeEach(async () => {
    vi.resetModules();
    state.forwardDelays = [0, 0, 0]; // No delays in tests
    process.env.BRIDGE_SHARED_SECRET = 'test_secret';
    process.env.INGRESS_URL = INGRESS_URL;
    redis = new Redis();
    state.redisClient = redis;
    // Clear spool to avoid leak between tests
    await redis.del('bridge:spool:inbound');
    server.listen({ onUnhandledRequest: 'error' });
  });

  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it('should create inbound payload with string identifiers and forward it', async () => {
    const mockMsg: any = {
      key: { id: 'msg123', remoteJid: '996555111222@s.whatsapp.net', fromMe: false },
      message: { conversation: 'hello' },
      messageTimestamp: 1234567890
    };

    let capturedPayload: any;
    server.use(
      http.post(INGRESS_URL, async ({ request }) => {
        capturedPayload = await request.json();
        return HttpResponse.json({ status: 'queued' });
      })
    );

    state.sock = { updateMediaMessage: vi.fn() } as any;

    await handleIncomingMessage(mockMsg);

    expect(capturedPayload).toBeDefined();
    expect(capturedPayload.external_id).toBe('msg123');
    expect(capturedPayload.external_chat_id).toBe('996555111222@s.whatsapp.net');
    expect(capturedPayload.phone_e164).toBe('996555111222');
    expect(typeof capturedPayload.chat_id).toBe('undefined'); // No numeric chat_id
    expect(capturedPayload.received_at).toBe(new Date(1234567890 * 1000).toISOString());
  });

  it('should spool to Redis when ingress fails after 3 attempts', async () => {
    server.use(
      http.post(INGRESS_URL, () => {
        return new HttpResponse(null, { status: 500 });
      })
    );

    const payload = { external_id: 'fail123' };
    const result = await forwardToIngress(payload);

    expect(result).toBe(false);
    const spooled = await redis.lrange('bridge:spool:inbound', 0, -1);
    expect(spooled.length).toBe(1);
    expect(JSON.parse(spooled[0])).toEqual(payload);
  });

  it('should allow spool processor to retry and clear queue on success', async () => {
    const payload = { external_id: 'spooled123' };
    await redis.lpush('bridge:spool:inbound', JSON.stringify(payload));

    let callCount = 0;
    server.use(
      http.post(INGRESS_URL, () => {
        callCount++;
        return HttpResponse.json({ status: 'ok' });
      })
    );

    const result = await processNextSpoolItem();

    expect(result).toBe(true);
    expect(callCount).toBe(1);
    const spooled = await redis.lrange('bridge:spool:inbound', 0, -1);
    expect(spooled.length).toBe(0);
  });

  it('should keep item in spool if retry fails', async () => {
    const payload = { external_id: 'retry-fail' };
    await redis.lpush('bridge:spool:inbound', JSON.stringify(payload));

    server.use(
      http.post(INGRESS_URL, () => {
        return new HttpResponse(null, { status: 502 });
      })
    );

    const result = await processNextSpoolItem();
    expect(result).toBe(false);

    // forwardToIngress should have re-spooled it
    const spooled = await redis.lrange('bridge:spool:inbound', 0, -1);
    expect(spooled.length).toBe(1);
    expect(JSON.parse(spooled[0])).toEqual(payload);
  });
});