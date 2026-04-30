import 'dotenv/config';
import express from 'express';
import Redis from 'ioredis';
import pino from 'pino';
import { createBaileysClient, state } from './lib/baileys-client.js';
import { setupSendRoute } from './routes/send.js';
import { setupPairRoute } from './routes/pair.js';
import { setupStatusRoute } from './routes/status.js';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });
const port = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379/0';

const redis = new Redis(redisUrl);
const app = express();

app.use(express.json());

app.use('/send', setupSendRoute(redis));
app.use('/pair', setupPairRoute());
app.use('/status', setupStatusRoute());

const server = app.listen(port, async () => {
  logger.info(`Bridge listening on port ${port}`);
  await createBaileysClient(redis);
});

process.on('SIGTERM', async () => {
  logger.info('SIGTERM received, shutting down gracefully');
  server.close();
  if (state.sock) state.sock.ws.close();
  await redis.quit();
  process.exit(0);
});