import { type FormEvent, useState } from "react";
import { ApiError, requestOtp, verifyOtp } from "../api/client";
import { setAccessToken } from "../auth";

interface LoginProps {
  onSuccess: () => void;
}

type Step = "phone" | "otp";

/**
 * Strip everything except digits and a leading `+`.
 * Empty result => not a usable phone.
 */
export function normalizePhoneInput(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  const hasPlus = trimmed.startsWith("+");
  const digits = trimmed.replace(/\D+/g, "");
  if (!digits) return "";
  return hasPlus ? `+${digits}` : digits;
}

/**
 * Convert ApiError / unknown into a Russian, user-actionable message.
 * Includes the HTTP status when present so support can diagnose without devtools.
 */
export function describeApiError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 0) {
      return `${fallback} (сервер недоступен или CORS блокирует домен фронта)`;
    }
    if (err.status === 429) {
      return `Слишком много попыток. Подождите минуту и повторите. (HTTP 429: ${err.detail})`;
    }
    if (err.status === 400) {
      return `Неверный формат данных: ${err.detail || "проверьте номер."} (HTTP 400)`;
    }
    if (err.status === 401) {
      return `Не авторизовано: ${err.detail || "код не подходит."} (HTTP 401)`;
    }
    if (err.status >= 500) {
      return `Сервер ответил ошибкой ${err.status}. Попробуйте через минуту.`;
    }
    return `${fallback} (HTTP ${err.status}: ${err.detail || "без деталей"})`;
  }
  const msg = err instanceof Error ? err.message : String(err);
  return `${fallback} (${msg})`;
}

export default function Login({ onSuccess }: LoginProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSendOtp = async (e: FormEvent) => {
    e.preventDefault();
    const normalized = normalizePhoneInput(phone);
    if (!normalized) {
      setError("Введите номер телефона.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await requestOtp(normalized);
      setPhone(normalized);
      setStep("otp");
    } catch (err) {
      setError(describeApiError(err, "Не удалось отправить код."));
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: FormEvent) => {
    e.preventDefault();
    const code = otp.trim();
    if (code.length !== 8) {
      setError("Код должен содержать 8 цифр.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const token = await verifyOtp(phone, code);
      setAccessToken(token);
      onSuccess();
    } catch (err) {
      setError(describeApiError(err, "Неверный или просроченный код."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="browser-login" aria-labelledby="cms-login-title">
      <div className="empty-state-icon" aria-hidden="true">🔐</div>
      <h1 id="cms-login-title" className="browser-login-title">Вход в CMS</h1>

      {step === "phone" ? (
        <>
          <p className="empty-state-text">
            Введите номер телефона. Вам придёт код подтверждения в WhatsApp.
          </p>
          <form className="browser-login-form" onSubmit={handleSendOtp}>
            <label className="form-group">
              <span className="form-label">Номер телефона</span>
              <input
                className="form-input"
                type="tel"
                autoComplete="tel"
                placeholder="+7 700 000 00 00"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={loading}
              />
            </label>
            {error ? <p className="error-banner">{error}</p> : null}
            <button
              className="btn btn-primary"
              type="submit"
              disabled={loading || !phone.trim()}
            >
              {loading ? "Отправка..." : "Отправить код"}
            </button>
          </form>
        </>
      ) : (
        <>
          <p className="empty-state-text">
            Код отправлен в WhatsApp на номер <strong>{phone}</strong>.
            Введите 8-значный код ниже.
          </p>
          <form className="browser-login-form" onSubmit={handleVerifyOtp}>
            <label className="form-group">
              <span className="form-label">Код подтверждения</span>
              <input
                className="form-input"
                type="text"
                inputMode="numeric"
                pattern="[0-9]{8}"
                maxLength={8}
                autoComplete="one-time-code"
                placeholder="12345678"
                value={otp}
                onChange={(e) =>
                  setOtp(e.target.value.replace(/\D/g, "").slice(0, 8))
                }
                disabled={loading}
              />
            </label>
            {error ? <p className="error-banner">{error}</p> : null}
            <button
              className="btn btn-primary"
              type="submit"
              disabled={loading || otp.length !== 8}
            >
              {loading ? "Проверка..." : "Войти"}
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              disabled={loading}
              onClick={() => {
                setStep("phone");
                setOtp("");
                setError("");
              }}
            >
              Изменить номер
            </button>
          </form>
        </>
      )}
    </section>
  );
}
