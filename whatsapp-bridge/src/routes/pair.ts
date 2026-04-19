import { Router, Request, Response } from 'express';
import { sock } from '../lib/baileys-client.js';

const router = Router();
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || '';

export const setupPairRoute = () => {
  router.post('/', async (req: Request, res: Response): Promise<any> => {
    const secret = req.headers['x-bridge-secret'];
    if (secret !== bridgeSecret) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    const { phone } = req.body;
    if (!phone || typeof phone !== 'string') {
      return res.status(400).json({ error: 'Phone required (E.164 without +)' });
    }

    if (sock?.authState?.creds?.registered) {
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