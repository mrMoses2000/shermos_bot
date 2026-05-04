import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import fs from 'fs/promises';
import path from 'path';
import pino from 'pino';

type Mode = 'pair' | 'qr';

const mode = (process.argv[2] || 'qr') as Mode;
const phoneNumber = process.argv[3] || '77064264520';
const maxCloses = Number(process.env.SMOKE_MAX_CLOSES || '5');
const timeoutMs = Number(process.env.SMOKE_TIMEOUT_MS || '120000');
const authDir = path.resolve(
  process.env.SMOKE_AUTH_DIR || `.smoke-auth-${mode}`,
);

if (mode !== 'pair' && mode !== 'qr') {
  console.error('Usage: pnpm exec tsx scripts/smoke-test.ts <pair|qr> [phone_without_plus]');
  process.exit(2);
}

const logger = pino({
  level: process.env.LOG_LEVEL || 'debug',
  redact: ['*.noiseKey', '*.signedIdentityKey', '*.advSecretKey'],
});

let closeCount = 0;
let pairingRequested = false;
let pairingRequestInFlight = false;
let stopped = false;
let reconnectTimer: NodeJS.Timeout | undefined;
let activeSock: ReturnType<typeof makeWASocket> | undefined;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function boomDetails(error: unknown) {
  const boom = error as Boom | undefined;
  return {
    statusCode: boom?.output?.statusCode,
    message: boom?.message,
    payload: boom?.output?.payload,
    data: (boom as any)?.data,
  };
}

async function stop(exitCode: number) {
  if (stopped) return;
  stopped = true;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  try {
    activeSock?.ws?.close();
  } catch {
    // ignore shutdown races
  }
  process.exit(exitCode);
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version, isLatest } = await fetchLatestBaileysVersion();

  logger.info(
    {
      mode,
      phone: mode === 'pair' ? phoneNumber : undefined,
      authDir,
      waVersion: version,
      isLatest,
      maxCloses,
      timeoutMs,
    },
    'starting_baileys_smoke_socket',
  );

  const sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: mode === 'qr',
    logger: logger.child({ module: 'baileys' }) as any,
    browser: Browsers.ubuntu('Chrome'),
    generateHighQualityLinkPreview: false,
  });
  activeSock = sock;

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    logger.info(
      {
        connection: update.connection,
        receivedPendingNotifications: update.receivedPendingNotifications,
        isNewLogin: update.isNewLogin,
        qr: update.qr ? 'received' : undefined,
        lastDisconnect: update.lastDisconnect
          ? boomDetails(update.lastDisconnect.error)
          : undefined,
      },
      'connection_update',
    );

    if (update.qr) {
      logger.info('qr_received_scan_with_whatsapp_linked_devices');
    }

    if (update.connection === 'open') {
      logger.info('smoke_test_registered_and_open');
      void stop(0);
      return;
    }

    if (update.connection === 'close') {
      closeCount += 1;
      const details = boomDetails(update.lastDisconnect?.error);
      logger.warn({ closeCount, ...details }, 'socket_closed');

      if (details.statusCode === DisconnectReason.loggedOut) {
        logger.fatal('logged_out_repair_required');
        void stop(1);
        return;
      }

      if (closeCount >= maxCloses) {
        logger.fatal({ closeCount }, 'max_close_attempts_reached');
        void stop(1);
        return;
      }

      reconnectTimer = setTimeout(() => {
        if (!stopped) void connect();
      }, 1000);
    }
  });

  if (mode === 'pair' && !sock.authState.creds.registered && !pairingRequested) {
    void requestPairingCodeWhenReady(sock);
  }
}

async function requestPairingCodeWhenReady(sock: ReturnType<typeof makeWASocket>) {
  if (pairingRequestInFlight || pairingRequested || stopped) return;
  pairingRequestInFlight = true;

  try {
    const deadline = Date.now() + 10000;
    while (!sock.ws?.isOpen) {
      if (stopped || sock.ws?.isClosed || Date.now() > deadline) {
        pairingRequestInFlight = false;
        logger.warn('socket_closed_before_pairing_code_request');
        return;
      }
      await delay(100);
    }

    try {
      const code = await sock.requestPairingCode(phoneNumber);
      pairingRequested = true;
      logger.info({ code }, 'pairing_code_requested_enter_immediately');
      console.log(`PAIRING_CODE=${code}`);
    } catch (error) {
      logger.error({ error: boomDetails(error) }, 'request_pairing_code_failed');
      await stop(1);
    }
  } finally {
    pairingRequestInFlight = false;
  }
}

async function main() {
  await fs.rm(authDir, { recursive: true, force: true });
  setTimeout(() => {
    logger.fatal({ timeoutMs }, 'smoke_test_timeout');
    void stop(2);
  }, timeoutMs).unref();

  await connect();
}

main().catch((error) => {
  logger.fatal({ error: boomDetails(error) }, 'smoke_test_unhandled_error');
  process.exit(1);
});
