import { describe, it, expect, vi, beforeEach } from 'vitest';
import express from 'express';
import request from 'supertest';
import { setupSendRoute } from '../src/routes/send.js';
import * as baileysClient from '../src/lib/baileys-client.js';
import { getMessage } from '../src/lib/message-store.js';
import RedisMock from 'ioredis-mock';

// Mock supertest might need this
const Redis = (RedisMock as any).default || RedisMock;

describe('POST /send', () => {
  let app: express.Express;
  let redis: any;

  beforeEach(() => {
    vi.resetModules();
    process.env.BRIDGE_SHARED_SECRET = 'test_secret';
    redis = new Redis();
    app = express();
    app.use(express.json());
    app.use('/send', setupSendRoute(redis));
  });

  it('should return 401 if secret is missing', async () => {
    const response = await request(app).post('/send').send({});
    expect(response.status).toBe(401);
  });

  it('should return 401 if secret is wrong', async () => {
    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'wrong')
      .send({});
    expect(response.status).toBe(401);
  });

  it('should return 503 if socket is not connected', async () => {
    baileysClient.state.sock = null;
    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({});
    expect(response.status).toBe(503);
  });

  it('should return 503 if socket exists but websocket is closed', async () => {
    const mockSock = {
      ws: { isOpen: false },
      user: { id: 'bot@s.whatsapp.net' },
      sendMessage: vi.fn(),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({});

    expect(response.status).toBe(503);
    expect(mockSock.sendMessage).not.toHaveBeenCalled();
  });

  it('should return 200 and send message if everything is correct', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
      authState: { creds: { registered: true } },
      sendMessage: vi.fn().mockResolvedValue({
        key: { id: 'msg123', remoteJid: '123456789@s.whatsapp.net', fromMe: true },
        message: { conversation: 'hello' }
      }),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const payload = {
      to: '123456789',
      idempotency_key: '550e8400-e29b-41d4-a716-446655440000',
      text: 'hello'
    };

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send(payload);

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ message_id: 'msg123', status: 'sent' });
    expect(mockSock.sendMessage).toHaveBeenCalledWith('123456789@s.whatsapp.net', { text: 'hello' });

    const stored = await getMessage(redis, { remoteJid: '123456789@s.whatsapp.net', id: 'msg123' } as any);
    expect(stored).toEqual({ conversation: 'hello' });

    // Verify idempotency
    const cached = await redis.get(`bridge:idem:${payload.idempotency_key}`);
    expect(cached).toBeDefined();
    await expect(redis.get('bridge:sent:msg123')).resolves.toBe('1');

    // Call again with same key
    const response2 = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send(payload);

    expect(response2.status).toBe(200);
    expect(mockSock.sendMessage).toHaveBeenCalledTimes(1); // Should NOT be called again
  });

  it('should keep a fully qualified JID unchanged', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
      authState: { creds: { registered: true } },
      sendMessage: vi.fn().mockResolvedValue({ key: { id: 'jid-msg' } }),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789@s.whatsapp.net',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440010',
        text: 'hello jid'
      });

    expect(response.status).toBe(200);
    expect(mockSock.sendMessage).toHaveBeenCalledWith('123456789@s.whatsapp.net', { text: 'hello jid' });
  });

  it('should send interactive buttons payload', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
      authState: { creds: { registered: true } },
      sendMessage: vi.fn().mockResolvedValue({ key: { id: 'buttons123' } }),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440011',
        text: 'Выберите действие',
        interactive: {
          type: 'buttons',
          buttons: [
            { id: 'gallery_yes', title: 'Да' },
            { id: 'gallery_no', title: 'Нет' }
          ]
        }
      });

    expect(response.status).toBe(200);
    expect(mockSock.sendMessage).toHaveBeenCalledWith('123456789@s.whatsapp.net', {
      text: 'Выберите действие',
      buttons: [
        { buttonId: 'gallery_yes', buttonText: { displayText: 'Да' }, type: 1 },
        { buttonId: 'gallery_no', buttonText: { displayText: 'Нет' }, type: 1 },
      ],
      headerType: 1
    });
  });

  it('should send interactive list payload', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
      authState: { creds: { registered: true } },
      sendMessage: vi.fn().mockResolvedValue({ key: { id: 'list123' } }),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440012',
        text: 'Оцените рендер',
        interactive: {
          type: 'list',
          list: {
            button_text: 'Выбрать',
            sections: [
              {
                title: 'Действия',
                rows: [
                  { id: 'rate:1', title: '⭐1' },
                  { id: 'rate:2', title: '⭐2' },
                  { id: 'rate:3', title: '⭐3' },
                  { id: 'rate:4', title: '⭐4' },
                  { id: 'rate:5', title: '⭐5' },
                ]
              }
            ]
          }
        }
      });

    expect(response.status).toBe(200);
    expect(mockSock.sendMessage).toHaveBeenCalledWith('123456789@s.whatsapp.net', {
      text: 'Оцените рендер',
      buttonText: 'Выбрать',
      sections: [
        {
          title: 'Действия',
          rows: [
            { rowId: 'rate:1', title: '⭐1', description: undefined },
            { rowId: 'rate:2', title: '⭐2', description: undefined },
            { rowId: 'rate:3', title: '⭐3', description: undefined },
            { rowId: 'rate:4', title: '⭐4', description: undefined },
            { rowId: 'rate:5', title: '⭐5', description: undefined },
          ]
        }
      ]
    });
  });

  it('should fall back to plain text when Baileys rejects interactive buttons', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
      authState: { creds: { registered: true } },
      sendMessage: vi.fn()
        .mockRejectedValueOnce(new Error('buttons not supported'))
        .mockResolvedValueOnce({ key: { id: 'fallback123' } }),
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440013',
        text: 'Выберите действие',
        interactive: {
          type: 'buttons',
          buttons: [
            { id: 'gallery_yes', title: 'Да' },
            { id: 'gallery_no', title: 'Нет' },
          ]
        }
      });

    expect(response.status).toBe(200);
    expect(response.body.message_id).toBe('fallback123');
    // First call was interactive (failed), second call was plain text fallback
    expect(mockSock.sendMessage).toHaveBeenCalledTimes(2);
    const [, secondCallPayload] = mockSock.sendMessage.mock.calls[1];
    expect(secondCallPayload.text).toContain('👉 Да: /gallery_yes');
    expect(secondCallPayload.text).toContain('👉 Нет: /gallery_no');
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('whatsapp_button_fallback'),
      expect.anything()
    );

    warnSpy.mockRestore();
  });

  it('should return 403 for disallowed media path', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: 'bot@s.whatsapp.net' },
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const payload = {
      to: '123456789',
      idempotency_key: '550e8400-e29b-41d4-a716-446655440001',
      media: { type: 'image', path: '/etc/passwd' }
    };

    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send(payload);

    expect(response.status).toBe(403);
    expect(response.body.error).toContain('Forbidden');
  });

  it('should return 403 for sibling-prefix directory attack', async () => {
     // @ts-ignore
    baileysClient.state.sock = { ws: { isOpen: true }, user: { id: 'bot' } };
    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440002',
        media: { type: 'image', path: '/data/incoming_secret/test.jpg' }
      });
    expect(response.status).toBe(403);
  });

  it('should return 404 for missing media file', async () => {
    // @ts-ignore
    baileysClient.state.sock = { ws: { isOpen: true }, user: { id: 'bot' } };
    const response = await request(app)
      .post('/send')
      .set('x-bridge-secret', 'test_secret')
      .send({
        to: '123456789',
        idempotency_key: '550e8400-e29b-41d4-a716-446655440003',
        media: { type: 'image', path: '/data/incoming/missing.jpg' }
      });
    expect(response.status).toBe(404);
  });
});
