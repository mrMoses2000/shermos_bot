import { describe, it, expect } from 'vitest';
import { safeCompare, extractTimestamp, isConnectedSock, isPathInsideAllowedDirs } from '../src/lib/utils.js';

describe('utils', () => {
  describe('safeCompare', () => {
    it('should return true for identical strings', () => {
      expect(safeCompare('secret123', 'secret123')).toBe(true);
    });

    it('should return false for different strings', () => {
      expect(safeCompare('secret123', 'wrong')).toBe(false);
    });

    it('should return false for different length strings', () => {
      expect(safeCompare('secret123', 'secret1234')).toBe(false);
    });

    it('should return false for undefined input', () => {
      expect(safeCompare(undefined, 'secret123')).toBe(false);
    });

    it('should return false for empty expected secret', () => {
      expect(safeCompare('any', '')).toBe(false);
    });
  });

  describe('isConnectedSock', () => {
    it('should return true if socket is open and user is set', () => {
      expect(isConnectedSock({ ws: { isOpen: true }, user: { id: 'test' } })).toBe(true);
    });

    it('should return false if socket is closed', () => {
      expect(isConnectedSock({ ws: { isOpen: false }, user: { id: 'test' } })).toBe(false);
    });

    it('should return false if user is missing', () => {
      expect(isConnectedSock({ ws: { isOpen: true } })).toBe(false);
    });
  });

  describe('isPathInsideAllowedDirs', () => {
    const mediaDir = '/data/incoming';
    const renderDir = '/data/renders';
    const allowed = [mediaDir, renderDir];

    it('should allow file inside media dir', () => {
      expect(isPathInsideAllowedDirs('/data/incoming/test.jpg', allowed)).toBe(true);
    });

    it('should allow file inside render dir', () => {
      expect(isPathInsideAllowedDirs('/data/renders/output.mp4', allowed)).toBe(true);
    });

    it('should reject file outside allowed dirs', () => {
      expect(isPathInsideAllowedDirs('/etc/passwd', allowed)).toBe(false);
    });

    it('should reject sibling directory with same prefix', () => {
      expect(isPathInsideAllowedDirs('/data/incoming_secret/test.jpg', allowed)).toBe(false);
    });

    it('should reject path traversal', () => {
      expect(isPathInsideAllowedDirs('/data/incoming/../secret/test.jpg', allowed)).toBe(false);
    });
  });

  describe('extractTimestamp', () => {
    it('should handle number', () => {
      expect(extractTimestamp({ messageTimestamp: 1234567890 })).toBe(1234567890);
    });

    it('should handle string', () => {
      expect(extractTimestamp({ messageTimestamp: '1234567890' })).toBe(1234567890);
    });

    it('should handle bigint', () => {
      expect(extractTimestamp({ messageTimestamp: BigInt(1234567890) })).toBe(1234567890);
    });

    it('should handle Long-like object (low/high)', () => {
      expect(extractTimestamp({ messageTimestamp: { low: 1234567890, high: 0, unsigned: true } })).toBe(1234567890);
    });

    it('should handle object with toNumber()', () => {
      expect(extractTimestamp({ messageTimestamp: { toNumber: () => 1234567890 } })).toBe(1234567890);
    });

    it('should return current time if missing or invalid', () => {
      const now = Math.floor(Date.now() / 1000);
      const ts = extractTimestamp({});
      expect(ts).toBeGreaterThanOrEqual(now);
    });
  });
});