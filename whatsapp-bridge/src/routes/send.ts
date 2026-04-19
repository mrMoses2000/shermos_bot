import { Router, Request, Response } from 'express';
import { z } from 'zod';
import { sock } from '../lib/baileys-client.js';
import Redis from 'ioredis';

const router = Router();
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || '';

const sendSchema = z.object({
  to: z.string(),
  idempotency_key: z.string().uuid(),
  text: z.string().optional(),
  interactive: z.object({
    type: z.enum(['buttons', 'list']),
    buttons: z.array(z.object({ id: z.string(), title: z.string().max(20) })).max(3).optional(),
    list: z.object({
      button_text: z.string().max(20),
      sections: z.array(z.object({
        title: z.string(),
        rows: z.array(z.object({ id: z.string(), title: z.string(), description: z.string().optional() }))
      }))
    }).optional()
  }).optional(),
  media: z.object({
    type: z.enum(['image', 'document']),
    path: z.string(),
    caption: z.string().optional()
  }).optional()
});

export const setupSendRoute = (redis: Redis) => {
  router.post('/', async (req: Request, res: Response): Promise<any> => {
    const secret = req.headers['x-bridge-secret'];
    if (secret !== bridgeSecret) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    try {
      const body = sendSchema.parse(req.body);
      const jid = `${body.to}@s.whatsapp.net`;
      const idemKey = `bridge:idem:${body.idempotency_key}`;

      const cached = await redis.get(idemKey);
      if (cached) {
        return res.json(JSON.parse(cached));
      }

      let payload: any = {};
      if (body.interactive) {
        if (body.interactive.type === 'buttons' && body.interactive.buttons) {
          payload = {
            text: body.text || '',
            buttons: body.interactive.buttons.map(b => ({
              buttonId: b.id,
              buttonText: { displayText: b.title },
              type: 1
            })),
            headerType: 1
          };
        } else if (body.interactive.type === 'list' && body.interactive.list) {
          payload = {
            text: body.text || '',
            buttonText: body.interactive.list.button_text,
            sections: body.interactive.list.sections.map(s => ({
              title: s.title,
              rows: s.rows.map(r => ({
                rowId: r.id,
                title: r.title,
                description: r.description
              }))
            }))
          };
        }
      } else if (body.media) {
        if (body.media.type === 'image') {
          payload = { image: { url: body.media.path }, caption: body.media.caption || body.text };
        } else {
          payload = { document: { url: body.media.path }, caption: body.media.caption || body.text };
        }
      } else if (body.text) {
        payload = { text: body.text };
      } else {
        return res.status(400).json({ error: 'Message content missing' });
      }

      const sentMsg = await sock.sendMessage(jid, payload);
      const result = { message_id: sentMsg?.key?.id, status: 'sent' };

      await redis.set(idemKey, JSON.stringify(result), 'EX', 3600);
      return res.json(result);
    } catch (err: any) {
      if (err instanceof z.ZodError) {
        return res.status(400).json({ error: 'Validation error', details: err.errors });
      }
      return res.status(502).json({ error: 'Failed to send message', detail: err.message });
    }
  });

  return router;
};