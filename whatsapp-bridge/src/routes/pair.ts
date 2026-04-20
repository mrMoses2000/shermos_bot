import { Router, Request, Response } from 'express';
import { state } from '../lib/baileys-client.js';
import { safeCompare } from '../lib/utils.js';

const router = Router();

export const setupPairRoute = () => {
  router.post('/', async (req: Request, res: Response): Promise<any> => {
    const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || '';
    const secret = req.headers['x-bridge-secret'] as string | undefined;
    if (!safeCompare(secret, bridgeSecret)) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    if (!state.sock || !state.sock.ws?.isOpen) {
      return res.status(503).json({ error: 'Service Unavailable: Bridge not initialized' });
    }
    const sock = state.sock!;

    const { phone } = req.body;
    if (!phone || typeof phone !== 'string') {
      return res.status(400).json({ error: 'Phone required (E.164 without +)' });
    }

    if (sock.authState?.creds?.registered) {
      return res.status(409).json({ error: 'Already paired' });
    }

    try {
      const code = await sock.requestPairingCode(phone);
      return res.json({ code });
    } catch (err: any) {
      return res.status(500).json({ error: 'Failed to request code', detail: err.message });
    }
  });

  return router;
};
