import { BufferJSON, proto } from '@whiskeysockets/baileys';
import Redis from 'ioredis';

const DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60;

const ttlSeconds = () => {
  const parsed = Number(process.env.MESSAGE_STORE_TTL_SECONDS || DEFAULT_TTL_SECONDS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TTL_SECONDS;
};

const fullKey = (key: proto.IMessageKey) => {
  const remoteJid = key.remoteJid || '';
  const participant = key.participant || '';
  const id = key.id || '';
  return `bridge:msg:${remoteJid}:${participant}:${id}`;
};

const idOnlyKey = (id: string) => `bridge:msgid:${id}`;
const sentByBridgeKey = (id: string) => `bridge:sent:${id}`;

export const saveMessage = async (
  redis: Redis,
  key: proto.IMessageKey | null | undefined,
  message: proto.IMessage | null | undefined
) => {
  if (!key?.id || !message) {
    return;
  }

  const payload = JSON.stringify(message, BufferJSON.replacer);
  const ttl = ttlSeconds();
  await redis.set(fullKey(key), payload, 'EX', ttl);
  await redis.set(idOnlyKey(key.id), payload, 'EX', ttl);
};

export const markSentByBridge = async (
  redis: Redis,
  key: proto.IMessageKey | null | undefined
) => {
  if (!key?.id) {
    return;
  }
  await redis.set(sentByBridgeKey(key.id), '1', 'EX', ttlSeconds());
};

export const isSentByBridge = async (
  redis: Redis,
  key: proto.IMessageKey | null | undefined
): Promise<boolean> => {
  if (!key?.id) {
    return false;
  }
  return Boolean(await redis.get(sentByBridgeKey(key.id)));
};

export const getMessage = async (
  redis: Redis,
  key: proto.IMessageKey | null | undefined
): Promise<proto.IMessage | undefined> => {
  if (!key?.id) {
    return undefined;
  }

  const raw = (await redis.get(fullKey(key))) || (await redis.get(idOnlyKey(key.id)));
  if (!raw) {
    return undefined;
  }

  return JSON.parse(raw, BufferJSON.reviver) as proto.IMessage;
};
