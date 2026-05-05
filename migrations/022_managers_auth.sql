-- Managers allowlist for CMS OTP authentication
CREATE TABLE IF NOT EXISTS managers (
    phone_e164  TEXT PRIMARY KEY,
    name        TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OTP codes (one active per phone at a time)
CREATE TABLE IF NOT EXISTS auth_otps (
    phone_e164  TEXT PRIMARY KEY,
    code_hash   TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rate-limit counters for OTP sends (per phone, 1-hour window)
CREATE TABLE IF NOT EXISTS auth_otp_rate_limit (
    phone_e164    TEXT PRIMARY KEY,
    last_sent_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    send_count_1h INT NOT NULL DEFAULT 0
);
