import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  getContentType,
  WAMessage,
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import { useRedisAuthState } from './auth-state-redis.js';
import { getMessage as getStoredMessage, isSentByBridge } from './message-store.js';
import Redis from 'ioredis';
import pino from 'pino';
import fs from 'fs/promises';
import path from 'path';
import { createWriteStream } from 'fs';
import { createRequire } from 'module';
import { extractTimestamp } from './utils.js';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });
const require = createRequire(import.meta.url);
const qrcodeTerminal = require('qrcode-terminal') as {
  generate: (input: string, opts?: { small?: boolean }) => void;
};
const ingressUrl = process.env.INGRESS_URL || 'http://localhost:9443/internal/whatsapp/inbound';
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || '';
const mediaDir = process.env.MEDIA_DIR || '/data/incoming';

export const getBridgeRole = () => {
  const role = (process.env.BRIDGE_ROLE || 'client').trim().toLowerCase();
  return role === 'manager' ? 'manager' : 'client';
};

export const getSpoolKey = () => {
  if (process.env.BRIDGE_SPOOL_KEY) return process.env.BRIDGE_SPOOL_KEY;
  return getBridgeRole() === 'manager' ? 'bridge:manager:spool:inbound' : 'bridge:spool:inbound';
};

const jidUser = (jid: string | null | undefined) => (jid || '').split('@')[0].split(':')[0];
const jidServer = (jid: string | null | undefined) => (jid || '').split('@')[1]?.split(':')[0];

const baseJid = (jid: string | null | undefined) => {
  const user = jidUser(jid);
  const server = jidServer(jid);
  return user && server ? `${user}@${server}` : undefined;
};

const ownJidCandidates = () => {
  const sockAny = state.sock as any;
  const me = sockAny?.authState?.creds?.me || {};
  const user = sockAny?.user || {};
  return [
    me.id,
    me.lid,
    user.id,
    user.lid,
  ].filter(Boolean) as string[];
};

const isOwnChat = (jid: string | null | undefined) => {
  if (!jid) return false;
  return ownJidCandidates().some((ownJid) => (
    jidUser(jid) === jidUser(ownJid) && jidServer(jid) === jidServer(ownJid)
  ));
};

const ownPhoneJid = () => ownJidCandidates()
  .map(baseJid)
  .find((jid) => jid?.endsWith('@s.whatsapp.net'));

export const getManagerSelfSessionJids = () => {
  if (getBridgeRole() !== 'manager') {
    return [];
  }
  return [...new Set(ownJidCandidates().map(baseJid).filter(Boolean))] as string[];
};

export const shouldProcessUpsertEventType = (type: string | undefined) => (
  type === 'notify' || (getBridgeRole() === 'manager' && type === 'append')
);

export const refreshManagerSelfSessions = async () => {
  const sockAny = state.sock as any;
  if (getBridgeRole() !== 'manager' || !sockAny?.assertSessions) {
    return;
  }

  const jids = getManagerSelfSessionJids();
  if (!jids.length) {
    return;
  }

  try {
    await sockAny.assertSessions(jids, true);
    logger.info({ count: jids.length }, 'Manager self sessions refreshed');
  } catch (err) {
    logger.warn({ err }, 'Failed to refresh manager self sessions');
  }
};

// JIDs we never want to forward to the Python ingress.
// Without these filters, contact status updates ("status@broadcast"),
// newsletter posts and broadcast-list messages were being processed as if
// they were direct messages — the bot then replied into the void and burned
// Gemini calls on noise.
const NON_DM_JID_SUFFIXES = [
  '@g.us',          // group chats
  '@broadcast',     // status@broadcast and user broadcast lists
  '@newsletter',    // WhatsApp channels
];

export const isDirectChatJid = (jid: string | null | undefined): boolean => {
  if (!jid) return false;
  if (jid === 'status@s.whatsapp.net') return false;  // legacy status JID
  for (const suffix of NON_DM_JID_SUFFIXES) {
    if (jid.endsWith(suffix)) return false;
  }
  return true;
};

export const shouldProcessIncomingMessage = async (m: WAMessage) => {
  if (!isDirectChatJid(m.key.remoteJid)) {
    return false;
  }
  if (!m.key.fromMe) {
    return true;
  }
  if (getBridgeRole() !== 'manager' || !isOwnChat(m.key.remoteJid!)) {
    return false;
  }
  if (state.redisClient && await isSentByBridge(state.redisClient, m.key)) {
    return false;
  }
  return true;
};

export const state = {
  sock: null as ReturnType<typeof makeWASocket> | null,
  redisClient: null as Redis | null,
  forwardDelays: [200, 1000, 5000],
  lastMessageAt: null as string | null,
  reconnectAttempts: 0,
};

export const createBaileysClient = async (redis: Redis) => {
  state.redisClient = redis;
  const prefix = process.env.BAILEYS_AUTH_PREFIX || 'baileys:auth:';
  const printQr = ['1', 'true', 'yes'].includes((process.env.WA_PRINT_QR || '').toLowerCase());
  const { state: authState, saveCreds } = await useRedisAuthState(redis, prefix);
  const { version, isLatest } = await fetchLatestBaileysVersion();

  logger.info({ version, isLatest }, 'Using WhatsApp Web version');

  const connect = () => {
    state.sock = makeWASocket({
      version,
      auth: authState,
      printQRInTerminal: false,
      logger: logger.child({ module: 'baileys' }) as any,
      browser: Browsers.ubuntu('Chrome'),
      getMessage: async (key) => {
        if (!state.redisClient) {
          return undefined;
        }
        return getStoredMessage(state.redisClient, key);
      },
    });

    let reconnectAttempts = 0;

    state.sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr) {
        logger.info('WhatsApp QR received. Scan it from WhatsApp Linked Devices.');
        if (printQr) {
          qrcodeTerminal.generate(qr, { small: true });
        }
      }

      if (connection === 'close') {
        const error = lastDisconnect?.error as Boom;
        const statusCode = error?.output?.statusCode;
        if (statusCode === DisconnectReason.loggedOut) {
          logger.fatal('Logged out from WhatsApp. Re-pairing required.');
          process.exit(1);
        } else {
          reconnectAttempts++;
          state.reconnectAttempts = reconnectAttempts;
          const delayMs = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000);
          logger.warn({ statusCode, delayMs }, 'Connection closed, reconnecting...');
          setTimeout(connect, delayMs);
        }
      } else if (connection === 'open') {
        logger.info('WhatsApp connection opened');
        reconnectAttempts = 0;
        state.reconnectAttempts = 0;
        void refreshManagerSelfSessions();
        // Start spool processor on connection
        startSpoolProcessor();
      }
    });

    state.sock.ev.on('creds.update', saveCreds);

    state.sock.ev.on('messages.upsert', async (event) => {
      if (!shouldProcessUpsertEventType(event.type)) return;

      for (const m of event.messages) {
        if (!await shouldProcessIncomingMessage(m)) continue;

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
  state.lastMessageAt = new Date().toISOString();

  if (!m.message) {
    logger.warn({
      msgId: m.key.id,
      fromMe: m.key.fromMe,
      reason: m.messageStubParameters?.[0],
    }, 'Incoming message has no decrypted content');
    return;
  }

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
  const senderPn = (m.key as { senderPn?: string }).senderPn;
  const participantPn = (m.key as { participantPn?: string }).participantPn;
  const contactJid = senderPn || participantPn || (m.key.fromMe && isOwnChat(jid) ? ownPhoneJid() : undefined) || jid;
  const phoneE164 = contactJid.split('@')[0];
  const externalChatId = contactJid.endsWith('@s.whatsapp.net') ? contactJid : jid;

  const payload = {
    external_id: m.key.id,
    external_chat_id: externalChatId,
    jid: jid,
    phone_e164: phoneE164,
    bridge_role: getBridgeRole(),
    bot_type: getBridgeRole(),
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
          await state.redisClient.lpush(getSpoolKey(), JSON.stringify(payload));
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

  const item = await state.redisClient.rpop(getSpoolKey());
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
