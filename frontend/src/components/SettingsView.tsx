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
  const [openaiKeyInput, setOpenaiKeyInput] = useState("");
  const [anthropicKeyInput, setAnthropicKeyInput] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setSettings(null));
  }, []);

  if (!settings) return <section className="settings-section">読み込み中…</section>;

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
    setSavedMessage("OpenAI互換のAPIキーを保存しました。プロバイダーを openai_compatible に切り替えました。");
  };

  const saveAnthropicKey = async () => {
    if (!anthropicKeyInput.trim()) return;
    await update({ anthropic_api_key: anthropicKeyInput.trim() });
    setAnthropicKeyInput("");
    setSavedMessage("Anthropic のAPIキーを保存しました。");
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

      <label className="settings-row">
        <span>OpenAI APIキー（{settings.has_openai_compatible_key ? "設定済み" : "未設定"}）</span>
        <span className="settings-key-input">
          <input
            type="password"
            placeholder="sk-..."
            value={openaiKeyInput}
            onChange={(e) => setOpenaiKeyInput(e.target.value)}
            disabled={saving}
          />
          <button onClick={saveOpenaiKey} disabled={saving || !openaiKeyInput.trim()}>
            保存
          </button>
        </span>
      </label>

      <label className="settings-row">
        <span>Anthropic APIキー（{settings.has_anthropic_key ? "設定済み" : "未設定"}）</span>
        <span className="settings-key-input">
          <input
            type="password"
            placeholder="sk-ant-..."
            value={anthropicKeyInput}
            onChange={(e) => setAnthropicKeyInput(e.target.value)}
            disabled={saving}
          />
          <button onClick={saveAnthropicKey} disabled={saving || !anthropicKeyInput.trim()}>
            保存
          </button>
        </span>
      </label>

      {savedMessage && <p className="reply-status">{savedMessage}</p>}

      <p className="ai-empty">
        保存したキーはこの画面に再表示されません。GPT-4o miniなど低コストモデルが既定のため、まずはOpenAIキーの保存だけで動作確認できます。
      </p>
    </section>
  );
}
