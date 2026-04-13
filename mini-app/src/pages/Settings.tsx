import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import Spinner from "../components/Spinner";

type SettingsResponse = {
  webhook_url_client: string;
  webhook_url_manager: string;
  mini_app_url: string;
};

export default function Settings({ initData }: { initData: string }) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);

  useEffect(() => {
    apiGet<SettingsResponse>("/api/settings", initData).then(setSettings).catch(() => setSettings(null));
  }, [initData]);

  if (!settings) return <Spinner />;
  return (
    <div className="settings-list">
      <article>
        <span>Client webhook</span>
        <code>{settings.webhook_url_client}</code>
      </article>
      <article>
        <span>Manager webhook</span>
        <code>{settings.webhook_url_manager}</code>
      </article>
      <article>
        <span>Mini App</span>
        <code>{settings.mini_app_url || "Не задан"}</code>
      </article>
    </div>
  );
}
