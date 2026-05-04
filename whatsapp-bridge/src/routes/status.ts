import { Router, Request, Response } from 'express';
import { state } from '../lib/baileys-client.js';

const router = Router();

export const setupStatusRoute = () => {
  router.get('/', (req: Request, res: Response) => {
    const rawJid = state.sock?.user?.id;
    // Mask JID: e.g. "996555111222:4@s.whatsapp.net" -> "9965...net"
    const maskedJid = rawJid
      ? `${rawJid.split(':')[0].split('@')[0].substring(0, 4)}...net`
      : null;

    let connection = 'connecting';
    if (state.sock?.ws?.isClosed) {
      connection = 'close';
    } else if (state.sock?.ws?.isOpen) {
      connection = 'open';
    }

    const registered = !!state.sock?.authState?.creds?.registered || !!state.sock?.user?.id;

    return res.json({
      connection,
      registered,
      role: process.env.BRIDGE_ROLE || 'client',
      jid: maskedJid,
      last_event_at: new Date().toISOString()
    });
  });

  return router;
};
