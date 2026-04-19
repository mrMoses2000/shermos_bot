import { initAuthCreds, BufferJSON, AuthenticationState, SignalDataTypeMap } from '@whiskeysockets/baileys';
import Redis from 'ioredis';

export const useRedisAuthState = async (
  redis: Redis,
  prefix: string
): Promise<{ state: AuthenticationState; saveCreds: () => Promise<void> }> => {
  const readData = async (key: string) => {
    try {
      const data = await redis.get(prefix + key);
      return data ? JSON.parse(data, BufferJSON.reviver) : null;
    } catch {
      return null;
    }
  };

  const writeData = async (data: any, key: string) => {
    await redis.set(prefix + key, JSON.stringify(data, BufferJSON.replacer));
  };

  const removeData = async (key: string) => {
    await redis.del(prefix + key);
  };

  const creds = (await readData('creds')) || initAuthCreds();

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const data: { [id: string]: any } = {};
          await Promise.all(
            ids.map(async (id) => {
              let value = await readData(`keys:${type}-${id}`);
              if (type === 'app-state-sync-key' && value) {
                value = { ...value, syncKey: Buffer.from(value.syncKey.data) };
              }
              data[id] = value;
            })
          );
          return data;
        },
        set: async (data) => {
          const tasks: Promise<void>[] = [];
          for (const category in data) {
            for (const id in data[category as keyof SignalDataTypeMap]) {
              const value = data[category as keyof SignalDataTypeMap]?.[id];
              const key = `keys:${category}-${id}`;
              if (value) {
                tasks.push(writeData(value, key));
              } else {
                tasks.push(removeData(key));
              }
            }
          }
          await Promise.all(tasks);
        },
      },
    },
    saveCreds: () => writeData(creds, 'creds'),
  };
};
