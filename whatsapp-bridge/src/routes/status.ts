import { Router, Request, Response } from 'express';
import { sock } from '../lib/baileys-client.js';

const router = Router();

export const setupStatusRoute = () => {
  router.get('/', (req: Request, res: Response) => {
    return res.json({
      connection: sock?.ws?.isOpen ? 'open' : (sock?.ws?.isClosed ? 'close' : 'connecting'),
      registered: !!sock?.authState?.creds?.registered,
      jid: sock?.user?.id || null,
      last_event_at: new Date().toISOString()
    });
  });

  return router;
};