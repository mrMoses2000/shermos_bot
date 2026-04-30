import crypto from 'crypto';
import path from 'path';

/**
 * Constant-time string comparison to prevent timing attacks.
 */
export function safeCompare(a: string | undefined, b: string): boolean {
  if (typeof a !== 'string' || typeof b !== 'string' || b.length === 0) {
    return false;
  }

  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);

  if (bufA.length !== bufB.length) {
    // Still do a dummy comparison to keep timing somewhat consistent,
    // though length difference is often leaked by other means.
    crypto.timingSafeEqual(bufA, bufA);
    return false;
  }

  return crypto.timingSafeEqual(bufA, bufB);
}

export function isConnectedSock(sock: { ws?: { isOpen?: boolean }; user?: unknown } | null | undefined): boolean {
  return Boolean(sock?.ws?.isOpen && sock.user);
}

export function isPathInsideAllowedDirs(filePath: string, allowedDirs: string[]): boolean {
  const fullPath = path.resolve(filePath);
  return allowedDirs.some((dir) => {
    const base = path.resolve(dir);
    const relative = path.relative(base, fullPath);
    return relative === '' || Boolean(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
  });
}

/**
 * Robustly extract timestamp from Baileys message.
 */
export function extractTimestamp(m: any): number {
  let ts = m.messageTimestamp;
  if (typeof ts === 'string') {
    const parsed = Number(ts);
    if (Number.isFinite(parsed)) return parsed;
  }
  if (typeof ts === 'bigint') {
    return Number(ts);
  }
  if (typeof ts === 'object' && ts !== null && typeof ts.toNumber === 'function') {
    const parsed = ts.toNumber();
    if (Number.isFinite(parsed)) return parsed;
  }
  if (typeof ts === 'object' && ts !== null && 'low' in ts) {
    ts = Number(ts.low);
    if (ts < 0 && m.messageTimestamp.unsigned) {
      ts += 2 ** 32;
    }
  }
  return typeof ts === 'number' ? ts : Math.floor(Date.now() / 1000);
}
