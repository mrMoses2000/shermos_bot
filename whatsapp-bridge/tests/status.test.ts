import { describe, it, expect, vi, beforeEach } from 'vitest';
import express from 'express';
import request from 'supertest';
import { setupStatusRoute } from '../src/routes/status.js';
import * as baileysClient from '../src/lib/baileys-client.js';

describe('GET /status', () => {
  let app: express.Express;

  beforeEach(() => {
    vi.resetModules();
    app = express();
    app.use('/status', setupStatusRoute());
  });

  it('should return masked JID and connection status', async () => {
    const mockSock = {
      ws: { isOpen: true },
      user: { id: '996555111222:4@s.whatsapp.net' },
      authState: { creds: { registered: true } }
    };
    // @ts-ignore
    baileysClient.state.sock = mockSock;

    const response = await request(app).get('/status');

    expect(response.status).toBe(200);
    expect(response.body.connection).toBe('open');
    expect(response.body.registered).toBe(true);
    expect(response.body.jid).toBe('9965...net');
  });

  it('should handle missing user', async () => {
    // @ts-ignore
    baileysClient.state.sock = { ws: { isOpen: false, isClosed: true }, authState: { creds: { registered: false } } };

    const response = await request(app).get('/status');

    expect(response.status).toBe(200);
    expect(response.body.connection).toBe('close');
    expect(response.body.registered).toBe(false);
    expect(response.body.jid).toBeNull();
  });
});