import { useEffect, useState } from "react";
import type { AccountSummary, SettingsData } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";
import type { Language } from "../i18n/translations";

export function SettingsView() {
  const { t } = useTranslation();
  return (
    <div className="view-container settings-view">
      <h2>{t("nav.settings")}</h2>
      <DisplaySection />
      <AccountsSection />
      <AISettingsSection />
    </div>
  );
}

function DisplaySection() {
  const { t, language, setLanguage } = useTranslation();
  const [saved, setSaved] = useState(false);

  const onChange = (lang: Language) => {
    setLanguage(lang);
    setSaved(true);
  };

  return (
    <section className="settings-section">
      <h3>{t("settings.displayHeading")}</h3>
      <label className="settings-row">
        <span>{t("settings.languageLabel")}</span>
        <select value={language} onChange={(e) => onChange(e.target.value as Language)}>
          <option value="ja">日本語</option>
          <option value="en">English</option>
        </select>
      </label>
      {saved && <p className="reply-status">{t("settings.languageSaved")}</p>}
    </section>
  );
}

function AccountsSection() {
  const { t } = useTranslation();
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [form, setForm] = useState({
    display_name: "",
    email_address: "",
    imap_host: "",
    imap_port: 993,
    smtp_host: "",
    smtp_port: 465,
    use_ssl: true,
    password: "",
  });
  const [saving, setSaving] = useState(false);
  const [syncStatus, setSyncStatus] = useState<Record<string, string>>({});

  const load = () => api.listAccounts().then(setAccounts).catch(() => setAccounts([]));

  useEffect(() => {
    load();
  }, []);

  const addAccount = async () => {
    if (!form.display_name || !form.email_address) return;
    setSaving(true);
    try {
      await api.createAccount(form);
      setForm({ ...form, display_name: "", email_address: "", password: "" });
      await load();
    } finally {
      setSaving(false);
    }
  };

  const removeAccount = async (id: string) => {
    await api.deleteAccount(id);
    await load();
  };

  const syncNow = async (id: string) => {
    setSyncStatus((prev) => ({ ...prev, [id]: t("settings.syncing") }));
    try {
      const messages = await api.syncAccount(id, "INBOX");
      setSyncStatus((prev) => ({ ...prev, [id]: t("settings.syncResult", { count: messages.length }) }));
    } catch (err) {
      setSyncStatus((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : t("settings.syncFailed") }));
    }
  };

  return (
    <section className="settings-section">
      <h3>{t("settings.accountsHeading")}</h3>
      <ul className="account-list">
        {accounts.map((a) => (
          <li key={a.id} className="account-list-row">
            <span>
              {a.display_name} ({a.email_address})
            </span>
            <span className="account-list-actions">
              <button onClick={() => syncNow(a.id)}>{t("settings.syncNow")}</button>
              <button onClick={() => removeAccount(a.id)}>{t("common.delete")}</button>
            </span>
            {syncStatus[a.id] && <p className="reply-status account-sync-status">{syncStatus[a.id]}</p>}
          </li>
        ))}
        {accounts.length === 0 && <li className="ai-empty">{t("settings.noAccounts")}</li>}
      </ul>

      <div className="account-form">
        <input
          placeholder={t("settings.displayNamePlaceholder")}
          value={form.display_name}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })}
        />
        <input
          placeholder={t("settings.emailPlaceholder")}
          value={form.email_address}
          onChange={(e) => setForm({ ...form, email_address: e.target.value })}
        />
        <div className="account-form-row">
          <input
            placeholder={t("settings.imapHostPlaceholder")}
            value={form.imap_host}
            onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
          />
          <input
            type="number"
            placeholder={t("settings.imapPortPlaceholder")}
            value={form.imap_port}
            onChange={(e) => setForm({ ...form, imap_port: Number(e.target.value) })}
          />
        </div>
        <div className="account-form-row">
          <input
            placeholder={t("settings.smtpHostPlaceholder")}
            value={form.smtp_host}
            onChange={(e) => setForm({ ...form, smtp_host: e.target.value })}
          />
          <input
            type="number"
            placeholder={t("settings.smtpPortPlaceholder")}
            value={form.smtp_port}
            onChange={(e) => setForm({ ...form, smtp_port: Number(e.target.value) })}
          />
        </div>
        <label className="settings-row">
          <span>{t("settings.useSslLabel")}</span>
          <input
            type="checkbox"
            checked={form.use_ssl}
            onChange={(e) => setForm({ ...form, use_ssl: e.target.checked })}
          />
        </label>
        <input
          type="password"
          placeholder={t("settings.passwordPlaceholder")}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
        />
        <button onClick={addAccount} disabled={saving}>
          {t("settings.addAccount")}
        </button>
      </div>
      <p className="ai-empty">{t("settings.portsHelp")}</p>
    </section>
  );
}

function AISettingsSection() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [saving, setSaving] = useState(false);
  const [openaiKeyInput, setOpenaiKeyInput] = useState("");
  const [anthropicKeyInput, setAnthropicKeyInput] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setSettings(null));
  }, []);

  if (!settings) return <section className="settings-section">{t("common.loading")}</section>;

  const update = async (patch: Partial<SettingsData> & { openai_compatible_api_key?: string; anthropic_api_key?: string }) => {
    setSaving(true);
    try {
      const next = await api.updateSettings(patch);
      setSettings(next);
    } finally {
      setSaving(false);
    }
  };

  const saveOpenaiKey = async () => {
    if (!openaiKeyInput.trim()) return;
    await update({ openai_compatible_api_key: openaiKeyInput.trim(), llm_provider: "openai_compatible" });
    setOpenaiKeyInput("");
    setSavedMessage(t("settings.openaiKeySaved"));
  };

  const saveAnthropicKey = async () => {
    if (!anthropicKeyInput.trim()) return;
    await update({ anthropic_api_key: anthropicKeyInput.trim() });
    setAnthropicKeyInput("");
    setSavedMessage(t("settings.anthropicKeySaved"));
  };

  return (
    <section className="settings-section">
      <h3>{t("settings.aiHeading")}</h3>

      <label className="settings-row">
        <span>{t("settings.aiEnabledLabel")}</span>
        <input
          type="checkbox"
          checked={settings.ai_enabled}
          onChange={(e) => update({ ai_enabled: e.target.checked })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>{t("settings.llmProviderLabel")}</span>
        <select value={settings.llm_provider} onChange={(e) => update({ llm_provider: e.target.value })} disabled={saving}>
          {settings.available_llm_providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-row">
        <span>{t("settings.baseUrlLabel")}</span>
        <input
          value={settings.openai_compatible_base_url}
          onChange={(e) => update({ openai_compatible_base_url: e.target.value })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>{t("settings.modelLabel")}</span>
        <input
          value={settings.openai_compatible_model}
          onChange={(e) => update({ openai_compatible_model: e.target.value })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>{t("settings.anonymizeLabel")}</span>
        <input
          type="checkbox"
          checked={settings.anonymize_before_send}
          onChange={(e) => update({ anonymize_before_send: e.target.checked })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>{t("settings.openaiKeyLabel", { status: settings.has_openai_compatible_key ? t("settings.configured") : t("settings.notConfigured") })}</span>
        <span className="settings-key-input">
          <input
            type="password"
            placeholder="sk-..."
            value={openaiKeyInput}
            onChange={(e) => setOpenaiKeyInput(e.target.value)}
            disabled={saving}
          />
          <button onClick={saveOpenaiKey} disabled={saving || !openaiKeyInput.trim()}>
            {t("common.save")}
          </button>
        </span>
      </label>

      <label className="settings-row">
        <span>{t("settings.anthropicKeyLabel", { status: settings.has_anthropic_key ? t("settings.configured") : t("settings.notConfigured") })}</span>
        <span className="settings-key-input">
          <input
            type="password"
            placeholder="sk-ant-..."
            value={anthropicKeyInput}
            onChange={(e) => setAnthropicKeyInput(e.target.value)}
            disabled={saving}
          />
          <button onClick={saveAnthropicKey} disabled={saving || !anthropicKeyInput.trim()}>
            {t("common.save")}
          </button>
        </span>
      </label>

      {savedMessage && <p className="reply-status">{savedMessage}</p>}

      <p className="ai-empty">{t("settings.aiHelp")}</p>
    </section>
  );
}
