import { describe, it, expect, vi, beforeEach } from 'vitest';
import express from 'express';
import request from 'supertest';
import { setupSendRoute } from '../src/routes/send.js';
import { setupPairRoute } from '../src/routes/pair.js';
import { state } from '../src/lib/baileys-client.js';
import RedisMock from 'ioredis-mock';

const Redis = (RedisMock as any).default || RedisMock;

describe('X-Bridge-Secret constant-time auth', () => {
  let app: express.Express;
  let redis: any;

  beforeEach(() => {
    process.env.BRIDGE_SHARED_SECRET = 'secure_secret_123';
    redis = new Redis();
    app = express();
    app.use(express.json());
    app.use('/send', setupSendRoute(redis));
    app.use('/pair', setupPairRoute());
  });

  it('should return 401 for /send with wrong secret', async () => {
    const res = await request(app).post('/send').set('x-bridge-secret', 'wrong').send({});
    expect(res.status).toBe(401);
  });

  it('should return 401 for /pair with wrong secret', async () => {
    const res = await request(app).post('/pair').set('x-bridge-secret', 'wrong').send({});
    expect(res.status).toBe(401);
  });

  it('should return 401 for /send with missing secret', async () => {
    const res = await request(app).post('/send').send({});
    expect(res.status).toBe(401);
  });

  it('should allow /pair when socket is open before a user is registered', async () => {
    state.sock = {
      ws: { isOpen: true },
      authState: { creds: { registered: false } },
      requestPairingCode: vi.fn().mockResolvedValue('ABCD-1234'),
    } as any;

    const res = await request(app)
      .post('/pair')
      .set('x-bridge-secret', 'secure_secret_123')
      .send({ phone: '996555111222' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ code: 'ABCD-1234' });
    expect(state.sock.requestPairingCode).toHaveBeenCalledWith('996555111222');
  });
});
