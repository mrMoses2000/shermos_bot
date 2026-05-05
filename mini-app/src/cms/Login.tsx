import { type FormEvent, useState } from "react";
import { requestOtp, verifyOtp } from "../api/client";
import { setAccessToken } from "../auth";

interface LoginProps {
  onSuccess: () => void;
}

type Step = "phone" | "otp";

export default function Login({ onSuccess }: LoginProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSendOtp = async (e: FormEvent) => {
    e.preventDefault();
    const cleaned = phone.trim();
    if (!cleaned) {
      setError("Введите номер телефона.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await requestOtp(cleaned);
      setStep("otp");
    } catch {
      setError("Не удалось отправить код. Проверьте номер и попробуйте снова.");
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
      const token = await verifyOtp(phone.trim(), code);
      setAccessToken(token);
      onSuccess();
    } catch {
      setError("Неверный или просроченный код. Попробуйте ещё раз.");
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
                placeholder="+7 900 000 00 00"
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
