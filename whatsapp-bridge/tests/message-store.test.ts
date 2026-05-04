import { describe, expect, it } from 'vitest';
import RedisMock from 'ioredis-mock';
import { getMessage, saveMessage } from '../src/lib/message-store.js';

const Redis = (RedisMock as any).default || RedisMock;

describe('message-store', () => {
  it('stores and loads a message by full key', async () => {
    const redis = new Redis();
    const key = {
      remoteJid: '123456789@s.whatsapp.net',
      id: 'wamid-1',
      fromMe: true,
    };
    const message = {
      conversation: 'hello',
    };

    await saveMessage(redis, key, message as any);
    const loaded = await getMessage(redis, key as any);

    expect(loaded).toEqual(message);
  });

  it('falls back to id-only lookup when remoteJid differs', async () => {
    const redis = new Redis();
    await saveMessage(
      redis,
      {
        remoteJid: '123456789@s.whatsapp.net',
        id: 'wamid-2',
        fromMe: true,
      } as any,
      {
        conversation: 'retry me',
      } as any
    );

    const loaded = await getMessage(
      redis,
      {
        remoteJid: '123456789@lid',
        id: 'wamid-2',
        fromMe: true,
      } as any
    );

    expect(loaded).toEqual({ conversation: 'retry me' });
  });
});
