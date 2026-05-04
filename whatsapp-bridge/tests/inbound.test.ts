import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  handleIncomingMessage,
  forwardToIngress,
  state,
  processNextSpoolItem,
  getSpoolKey,
  shouldProcessIncomingMessage,
  shouldProcessUpsertEventType,
  getManagerSelfSessionJids,
  refreshManagerSelfSessions
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
    process.env.BRIDGE_ROLE = 'client';
    delete process.env.BRIDGE_SPOOL_KEY;
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
    expect(capturedPayload.bridge_role).toBe('client');
    expect(capturedPayload.bot_type).toBe('client');
    expect(typeof capturedPayload.chat_id).toBe('undefined'); // No numeric chat_id
    expect(capturedPayload.received_at).toBe(new Date(1234567890 * 1000).toISOString());
  });

  it('should mark inbound payload as manager when bridge role is manager', async () => {
    process.env.BRIDGE_ROLE = 'manager';
    const mockMsg: any = {
      key: { id: 'manager123', remoteJid: '77067396626@s.whatsapp.net', fromMe: false },
      message: { conversation: '/health' },
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

    expect(capturedPayload.bridge_role).toBe('manager');
    expect(capturedPayload.bot_type).toBe('manager');
    expect(capturedPayload.phone_e164).toBe('77067396626');
  });

  it('should prefer senderPn when WhatsApp delivers an LID remoteJid', async () => {
    const mockMsg: any = {
      key: {
        id: 'lid123',
        remoteJid: '102353885757655@lid',
        senderPn: '77713979524@s.whatsapp.net',
        fromMe: false
      },
      message: { conversation: 'hello from lid' },
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

    expect(capturedPayload.external_chat_id).toBe('77713979524@s.whatsapp.net');
    expect(capturedPayload.jid).toBe('102353885757655@lid');
    expect(capturedPayload.phone_e164).toBe('77713979524');
  });

  it('should map manager self-chat LID messages back to the manager phone number', async () => {
    process.env.BRIDGE_ROLE = 'manager';
    state.sock = {
      user: { id: '77067396626:1@s.whatsapp.net' },
      authState: { creds: { me: { id: '77067396626:1@s.whatsapp.net', lid: '234377036488901:1@lid' } } },
      updateMediaMessage: vi.fn(),
    } as any;

    const mockMsg: any = {
      key: { id: 'self-lid-health', remoteJid: '234377036488901@lid', fromMe: true },
      message: { conversation: '/health' },
      messageTimestamp: 1234567890
    };

    let capturedPayload: any;
    server.use(
      http.post(INGRESS_URL, async ({ request }) => {
        capturedPayload = await request.json();
        return HttpResponse.json({ status: 'queued' });
      })
    );

    await handleIncomingMessage(mockMsg);

    expect(capturedPayload.external_chat_id).toBe('77067396626@s.whatsapp.net');
    expect(capturedPayload.phone_e164).toBe('77067396626');
    expect(capturedPayload.jid).toBe('234377036488901@lid');
    expect(capturedPayload.text).toBe('/health');
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

  it('should use a separate spool key for manager bridge', async () => {
    process.env.BRIDGE_ROLE = 'manager';
    expect(getSpoolKey()).toBe('bridge:manager:spool:inbound');
  });

  it('should process manager self-chat messages but ignore bridge-sent echoes', async () => {
    process.env.BRIDGE_ROLE = 'manager';
    state.sock = {
      user: { id: '77067396626:1@s.whatsapp.net' },
      authState: { creds: { me: { id: '77067396626:1@s.whatsapp.net', lid: '234377036488901:1@lid' } } },
    } as any;

    const masterTyped: any = {
      key: { id: 'typed-by-master', remoteJid: '77067396626@s.whatsapp.net', fromMe: true },
      message: { conversation: '/health' },
    };
    expect(await shouldProcessIncomingMessage(masterTyped)).toBe(true);

    const masterTypedFromLid: any = {
      key: { id: 'typed-by-master-lid', remoteJid: '234377036488901@lid', fromMe: true },
      message: { conversation: '/health' },
    };
    expect(await shouldProcessIncomingMessage(masterTypedFromLid)).toBe(true);

    await redis.set('bridge:sent:sent-by-bridge', '1', 'EX', 60);
    const bridgeEcho: any = {
      key: { id: 'sent-by-bridge', remoteJid: '77067396626@s.whatsapp.net', fromMe: true },
      message: { conversation: 'Shermos manager bot работает.' },
    };
    expect(await shouldProcessIncomingMessage(bridgeEcho)).toBe(false);
  });

  it('should only allow append upsert events for the manager bridge', () => {
    process.env.BRIDGE_ROLE = 'client';
    expect(shouldProcessUpsertEventType('notify')).toBe(true);
    expect(shouldProcessUpsertEventType('append')).toBe(false);

    process.env.BRIDGE_ROLE = 'manager';
    expect(shouldProcessUpsertEventType('notify')).toBe(true);
    expect(shouldProcessUpsertEventType('append')).toBe(true);
  });

  it('should refresh manager self sessions for PN and LID identities', async () => {
    process.env.BRIDGE_ROLE = 'manager';
    const assertSessions = vi.fn().mockResolvedValue(true);
    state.sock = {
      assertSessions,
      authState: { creds: { me: { id: '77067396626:1@s.whatsapp.net', lid: '234377036488901:1@lid' } } },
    } as any;

    expect(getManagerSelfSessionJids()).toEqual([
      '77067396626@s.whatsapp.net',
      '234377036488901@lid',
    ]);

    await refreshManagerSelfSessions();

    expect(assertSessions).toHaveBeenCalledWith([
      '77067396626@s.whatsapp.net',
      '234377036488901@lid',
    ], true);
  });

  it('should continue ignoring client bridge fromMe messages', async () => {
    process.env.BRIDGE_ROLE = 'client';
    state.sock = { user: { id: '77067396626:1@s.whatsapp.net' } } as any;
    const fromMe: any = {
      key: { id: 'client-from-me', remoteJid: '77067396626@s.whatsapp.net', fromMe: true },
      message: { conversation: 'hello' },
    };
    expect(await shouldProcessIncomingMessage(fromMe)).toBe(false);
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
