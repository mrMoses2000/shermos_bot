import { describe, expect, it } from 'vitest';
import RedisMock from 'ioredis-mock';
import { proto } from '@whiskeysockets/baileys';
import { useRedisAuthState } from '../src/lib/auth-state-redis.js';

const Redis = (RedisMock as any).default || RedisMock;

describe('useRedisAuthState', () => {
  it('round-trips app-state-sync-key values through Redis', async () => {
    const redis = new Redis();
    const { state } = await useRedisAuthState(redis, 'test:auth:');

    const key = proto.Message.AppStateSyncKeyData.fromObject({
      keyData: Buffer.from('key-data'),
      fingerprint: {
        rawId: 123,
        currentIndex: 1,
        deviceIndexes: [1, 0],
      },
      timestamp: '1776717430759',
    });

    await state.keys.set({ 'app-state-sync-key': { testKey: key } });

    const result = await state.keys.get('app-state-sync-key', ['testKey']);

    expect(result.testKey).toBeInstanceOf(proto.Message.AppStateSyncKeyData);
    expect(Buffer.from(result.testKey.keyData as Uint8Array).toString()).toBe('key-data');
    expect(result.testKey.fingerprint?.rawId).toBe(123);
  });

  it('reads app-state-sync-key values stored with base64 fields', async () => {
    const redis = new Redis();
    await redis.set(
      'test:auth:keys:app-state-sync-key-AAAAAFpl',
      JSON.stringify({
        keyData: Buffer.from('from-whatsapp').toString('base64'),
        fingerprint: {
          rawId: 3795243547,
          currentIndex: 1,
          deviceIndexes: [1, 0],
        },
        timestamp: '1776717430759',
      }),
    );

    const { state } = await useRedisAuthState(redis, 'test:auth:');
    const result = await state.keys.get('app-state-sync-key', ['AAAAAFpl']);

    expect(result.AAAAAFpl).toBeInstanceOf(proto.Message.AppStateSyncKeyData);
    expect(Buffer.from(result.AAAAAFpl.keyData as Uint8Array).toString()).toBe('from-whatsapp');
  });
});
