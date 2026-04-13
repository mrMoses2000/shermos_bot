type TelegramWebApp = {
  initData: string;
  ready: () => void;
  expand: () => void;
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export function useTelegram() {
  const webApp = window.Telegram?.WebApp;
  webApp?.ready();
  webApp?.expand();
  return {
    initData: webApp?.initData || "",
    isTelegram: Boolean(webApp)
  };
}
