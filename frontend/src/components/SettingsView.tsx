import { useEffect, useState } from "react";
import type { AccountSummary, SettingsData } from "../api/client";
import { api } from "../api/client";

export function SettingsView() {
  return (
    <div className="view-container settings-view">
      <h2>設定</h2>
      <AccountsSection />
      <AISettingsSection />
    </div>
  );
}

function AccountsSection() {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [form, setForm] = useState({
    display_name: "",
    email_address: "",
    imap_host: "",
    imap_port: 993,
    smtp_host: "",
    smtp_port: 465,
    password: "",
  });
  const [saving, setSaving] = useState(false);

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

  return (
    <section className="settings-section">
      <h3>メールアカウント</h3>
      <ul className="account-list">
        {accounts.map((a) => (
          <li key={a.id}>
            <span>
              {a.display_name} ({a.email_address})
            </span>
            <button onClick={() => removeAccount(a.id)}>削除</button>
          </li>
        ))}
        {accounts.length === 0 && <li className="ai-empty">登録済みアカウントはありません。</li>}
      </ul>

      <div className="account-form">
        <input
          placeholder="表示名"
          value={form.display_name}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })}
        />
        <input
          placeholder="メールアドレス"
          value={form.email_address}
          onChange={(e) => setForm({ ...form, email_address: e.target.value })}
        />
        <input
          placeholder="IMAPホスト"
          value={form.imap_host}
          onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
        />
        <input
          placeholder="SMTPホスト"
          value={form.smtp_host}
          onChange={(e) => setForm({ ...form, smtp_host: e.target.value })}
        />
        <input
          type="password"
          placeholder="パスワード（暗号化して保存されます）"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
        />
        <button onClick={addAccount} disabled={saving}>
          アカウント追加
        </button>
      </div>
    </section>
  );
}

function AISettingsSection() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setSettings(null));
  }, []);

  if (!settings) return <section className="settings-section">読み込み中…</section>;

  const update = async (patch: Partial<SettingsData>) => {
    setSaving(true);
    try {
      const next = await api.updateSettings(patch);
      setSettings(next);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>AI設定</h3>

      <label className="settings-row">
        <span>AI機能を有効化</span>
        <input
          type="checkbox"
          checked={settings.ai_enabled}
          onChange={(e) => update({ ai_enabled: e.target.checked })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>LLMプロバイダー</span>
        <select value={settings.llm_provider} onChange={(e) => update({ llm_provider: e.target.value })} disabled={saving}>
          {settings.available_llm_providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-row">
        <span>OpenAI互換 base_url</span>
        <input
          value={settings.openai_compatible_base_url}
          onChange={(e) => update({ openai_compatible_base_url: e.target.value })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>OpenAI互換モデル</span>
        <input
          value={settings.openai_compatible_model}
          onChange={(e) => update({ openai_compatible_model: e.target.value })}
          disabled={saving}
        />
      </label>

      <label className="settings-row">
        <span>APIキー送信前に匿名化する</span>
        <input
          type="checkbox"
          checked={settings.anonymize_before_send}
          onChange={(e) => update({ anonymize_before_send: e.target.checked })}
          disabled={saving}
        />
      </label>

      <p className="ai-empty">
        APIキーはこの画面からは表示されません（設定済み: OpenAI互換={settings.has_openai_compatible_key ? "あり" : "なし"} /
        Anthropic={settings.has_anthropic_key ? "あり" : "なし"}）。
      </p>
    </section>
  );
}
