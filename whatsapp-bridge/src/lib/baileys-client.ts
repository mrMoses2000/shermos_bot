import makeWASocket, { DisconnectReason, getContentType, downloadMediaMessage, WAMessage } from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import { useRedisAuthState } from './auth-state-redis.js';
import Redis from 'ioredis';
import pino from 'pino';
import fs from 'fs/promises';
import path from 'path';
import { createWriteStream } from 'fs';
import { extractTimestamp } from './utils.js';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });
const ingressUrl = process.env.INGRESS_URL || 'http://localhost:9443/internal/whatsapp/inbound';
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || '';
const mediaDir = process.env.MEDIA_DIR || '/data/incoming';
const SPOOL_KEY = 'bridge:spool:inbound';

export const state = {
  sock: null as ReturnType<typeof makeWASocket> | null,
  redisClient: null as Redis | null,
  forwardDelays: [200, 1000, 5000],
};

export const createBaileysClient = async (redis: Redis) => {
  state.redisClient = redis;
  const prefix = process.env.BAILEYS_AUTH_PREFIX || 'baileys:auth:';
  const { state: authState, saveCreds } = await useRedisAuthState(redis, prefix);

  const connect = () => {
    state.sock = makeWASocket({
      auth: authState,
      printQRInTerminal: false,
      logger: logger.child({ module: 'baileys' }) as any,
      browser: ['Shermos', 'Chrome', '1.0'],
    });

    let reconnectAttempts = 0;

    state.sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect } = update;
      if (connection === 'close') {
        const error = lastDisconnect?.error as Boom;
        const statusCode = error?.output?.statusCode;
        if (statusCode === DisconnectReason.loggedOut) {
          logger.fatal('Logged out from WhatsApp. Re-pairing required.');
          process.exit(1);
        } else {
          reconnectAttempts++;
          const delayMs = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000);
          logger.warn({ statusCode, delayMs }, 'Connection closed, reconnecting...');
          setTimeout(connect, delayMs);
        }
      } else if (connection === 'open') {
        logger.info('WhatsApp connection opened');
        reconnectAttempts = 0;
        // Start spool processor on connection
        startSpoolProcessor();
      }
    });

    state.sock.ev.on('creds.update', saveCreds);

    state.sock.ev.on('messages.upsert', async (event) => {
      if (event.type !== 'notify') return;

      for (const m of event.messages) {
        if (m.key.fromMe || !m.key.remoteJid || m.key.remoteJid.endsWith('@g.us')) continue;

        try {
          await handleIncomingMessage(m);
        } catch (err) {
          logger.error({ err, msgId: m.key.id }, 'Error handling incoming message');
        }
      }
    });
  };

  connect();
  return state.sock;
};

export const handleIncomingMessage = async (m: WAMessage) => {
  if (!m.message) return;

  const messageType = getContentType(m.message);
  let text = '';
  let msg_type = 'text';
  let callback_data: string | null = null;
  let media_path: string | null = null;
  let media_mime: string | null = null;

  if (messageType === 'conversation') {
    text = m.message.conversation || '';
  } else if (messageType === 'extendedTextMessage') {
    text = m.message.extendedTextMessage?.text || '';
  } else if (messageType === 'imageMessage') {
    msg_type = 'image';
    text = m.message.imageMessage?.caption || '';
    media_mime = m.message.imageMessage?.mimetype || 'image/jpeg';
  } else if (messageType === 'audioMessage') {
    msg_type = 'voice';
    media_mime = m.message.audioMessage?.mimetype || 'audio/ogg; codecs=opus';
  } else if (messageType === 'documentMessage') {
    msg_type = 'document';
    text = m.message.documentMessage?.caption || '';
    media_mime = m.message.documentMessage?.mimetype || 'application/octet-stream';
  } else if (messageType === 'buttonsResponseMessage') {
    msg_type = 'button_reply';
    callback_data = m.message.buttonsResponseMessage?.selectedButtonId || null;
    text = m.message.buttonsResponseMessage?.selectedDisplayText || '';
  } else if (messageType === 'listResponseMessage') {
    msg_type = 'list_reply';
    callback_data = m.message.listResponseMessage?.singleSelectReply?.selectedRowId || null;
    text = m.message.listResponseMessage?.title || '';
  } else if (messageType === 'interactiveResponseMessage') {
     const intMsg = m.message.interactiveResponseMessage;
     if (intMsg?.nativeFlowResponseMessage) {
         try {
             const params = JSON.parse(intMsg.nativeFlowResponseMessage.paramsJson || '{}');
             callback_data = params.id || null;
             msg_type = 'button_reply';
         } catch { /* ignore */ }
     }
  } else {
    // Unsupported message type
    return;
  }

  // Handle media download
  if (['image', 'voice', 'document'].includes(msg_type) && state.sock) {
    try {
      const ext = media_mime?.split('/')[1]?.split(';')[0] || 'bin';
      const filename = `${m.key.id}.${ext}`;
      const fullPath = path.join(mediaDir, filename);

      await fs.mkdir(mediaDir, { recursive: true });

      const stream = (await downloadMediaMessage(
        m,
        'stream',
        {},
        { logger: logger as any, reuploadRequest: state.sock.updateMediaMessage }
      )) as any;

      const writeStream = createWriteStream(fullPath);
      await new Promise((resolve, reject) => {
        stream.pipe(writeStream);
        stream.on('finish', resolve);
        stream.on('error', reject);
      });

      media_path = fullPath;
    } catch (err) {
      logger.error({ err, msgId: m.key.id }, 'Failed to download media');
    }
  }

  const jid = m.key.remoteJid!;
  const phoneE164 = jid.split('@')[0];

  const payload = {
    external_id: m.key.id,
    external_chat_id: jid,
    jid: jid,
    phone_e164: phoneE164,
    text: text,
    msg_type,
    callback_data,
    media_path,
    media_mime,
    raw: m,
    received_at: new Date(extractTimestamp(m) * 1000).toISOString(),
  };

  await forwardToIngress(payload);
};

export async function forwardToIngress(payload: any) {
  let attempts = 0;
  const maxAttempts = 3;
  const delays = state.forwardDelays;

  while (attempts < maxAttempts) {
    try {
      const response = await fetch(ingressUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Bridge-Secret': bridgeSecret,
        },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        logger.info({ msgId: payload.external_id }, 'Message forwarded to ingress');
        return true;
      }
      throw new Error(`HTTP ${response.status}`);
    } catch (err) {
      attempts++;
      if (attempts >= maxAttempts) {
        logger.warn({ err, msgId: payload.external_id }, 'Failed to forward to ingress, spooling...');
        if (state.redisClient) {
          await state.redisClient.lpush(SPOOL_KEY, JSON.stringify(payload));
        }
        return false;
      } else {
        await new Promise((res) => setTimeout(res, delays[attempts - 1]));
      }
    }
  }
  return false;
}

export async function processNextSpoolItem() {
  if (!state.redisClient) return false;
  
  const item = await state.redisClient.rpop(SPOOL_KEY);
  if (!item) return false;
  
  try {
    const payload = JSON.parse(item);
    const success = await forwardToIngress(payload);
    return success;
  } catch (err) {
    logger.error({ err }, 'Failed to process spooled item');
    return false;
  }
}

let spoolProcessorRunning = false;
export async function startSpoolProcessor() {
  if (spoolProcessorRunning || !state.redisClient) return;
  spoolProcessorRunning = true;
  
  logger.info('Starting spool processor');
  
  while (true) {
    try {
      const processed = await processNextSpoolItem();
      if (!processed) {
        // Wait a bit if no items were processed or forward failed (it re-spooled)
        await new Promise(res => setTimeout(res, 10000));
      }
    } catch (err) {
      logger.error({ err }, 'Spool processor loop error');
      await new Promise(res => setTimeout(res, 5000));
    }
  }
}