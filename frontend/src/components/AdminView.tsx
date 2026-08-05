import { useEffect, useState } from "react";
import type { PluginInfo, PromptTemplate, Rule, RuleAction, RuleCondition } from "../api/client";
import { api } from "../api/client";

type AdminTab = "prompts" | "rules" | "plugins";

export function AdminView() {
  const [tab, setTab] = useState<AdminTab>("prompts");

  return (
    <div className="view-container admin-view">
      <h2>管理</h2>
      <div className="admin-tabs">
        <button className={tab === "prompts" ? "active" : ""} onClick={() => setTab("prompts")}>
          プロンプト
        </button>
        <button className={tab === "rules" ? "active" : ""} onClick={() => setTab("rules")}>
          ルール
        </button>
        <button className={tab === "plugins" ? "active" : ""} onClick={() => setTab("plugins")}>
          プラグイン
        </button>
      </div>

      {tab === "prompts" && <PromptsPanel />}
      {tab === "rules" && <RulesPanel />}
      {tab === "plugins" && <PluginsPanel />}
    </div>
  );
}

const TASKS = ["classification", "extraction", "summary", "reply_suggestion", "duplicate_check", "chat"];

function PromptsPanel() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [form, setForm] = useState({ name: "", task: TASKS[0], system_prompt: "", user_prompt_template: "" });
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [versionDraft, setVersionDraft] = useState({ system_prompt: "", user_prompt_template: "", notes: "" });

  const load = () => api.listPrompts().then(setTemplates).catch(() => setTemplates([]));

  useEffect(() => {
    load();
  }, []);

  const createTemplate = async () => {
    if (!form.name || !form.system_prompt || !form.user_prompt_template) return;
    setSaving(true);
    try {
      await api.createPrompt(form);
      setForm({ ...form, name: "", system_prompt: "", user_prompt_template: "" });
      await load();
    } finally {
      setSaving(false);
    }
  };

  const startEditVersion = (template: PromptTemplate) => {
    const active = template.versions.find((v) => v.id === template.active_version_id) ?? template.versions[0];
    setVersionDraft({
      system_prompt: active?.system_prompt ?? "",
      user_prompt_template: active?.user_prompt_template ?? "",
      notes: "",
    });
    setExpanded(template.id);
  };

  const addVersion = async (templateId: string) => {
    setSaving(true);
    try {
      await api.addPromptVersion(templateId, { ...versionDraft, activate: true });
      setExpanded(null);
      await load();
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="admin-panel">
      <p className="ai-empty">
        分類・抽出タスクは、ここでtask="classification"/"extraction"のテンプレートを有効化すると、
        バックエンドのデフォルトプロンプトの代わりに使用されます。
      </p>

      <ul className="prompt-list">
        {templates.map((t) => (
          <li key={t.id} className="prompt-card">
            <div className="prompt-card-header">
              <strong>{t.name}</strong>
              <span className="task-badge">{t.task}</span>
              <button onClick={() => (expanded === t.id ? setExpanded(null) : startEditVersion(t))}>
                {expanded === t.id ? "閉じる" : "新バージョン追加"}
              </button>
            </div>
            {expanded === t.id && (
              <div className="prompt-version-form">
                <label>
                  システムプロンプト
                  <textarea
                    rows={4}
                    value={versionDraft.system_prompt}
                    onChange={(e) => setVersionDraft({ ...versionDraft, system_prompt: e.target.value })}
                  />
                </label>
                <label>
                  ユーザープロンプトテンプレート（{"{{ subject }} {{ body }}"} 等の変数が使えます）
                  <textarea
                    rows={4}
                    value={versionDraft.user_prompt_template}
                    onChange={(e) => setVersionDraft({ ...versionDraft, user_prompt_template: e.target.value })}
                  />
                </label>
                <label>
                  変更メモ
                  <input value={versionDraft.notes} onChange={(e) => setVersionDraft({ ...versionDraft, notes: e.target.value })} />
                </label>
                <button className="primary" onClick={() => addVersion(t.id)} disabled={saving}>
                  保存して有効化
                </button>
              </div>
            )}
          </li>
        ))}
        {templates.length === 0 && <li className="ai-empty">プロンプトテンプレートはまだありません。</li>}
      </ul>

      <div className="prompt-create-form">
        <h4>新規テンプレート作成</h4>
        <input placeholder="名前" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })}>
          {TASKS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <textarea
          rows={3}
          placeholder="システムプロンプト"
          value={form.system_prompt}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
        />
        <textarea
          rows={3}
          placeholder="ユーザープロンプトテンプレート"
          value={form.user_prompt_template}
          onChange={(e) => setForm({ ...form, user_prompt_template: e.target.value })}
        />
        <button onClick={createTemplate} disabled={saving}>
          作成
        </button>
      </div>
    </section>
  );
}

const RULE_FIELDS = ["subject", "sender_address", "sender_name", "body_text", "mail_type", "priority"];
const RULE_OPERATORS = ["equals", "contains", "starts_with", "in"];

function RulesPanel() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [name, setName] = useState("");
  const [priority, setPriority] = useState(100);
  const [matchMode, setMatchMode] = useState<"all" | "any">("all");
  const [conditions, setConditions] = useState<RuleCondition[]>([{ field: RULE_FIELDS[0], operator: "contains", value: "" }]);
  const [actions, setActions] = useState<RuleAction[]>([{ type: "tag", params: { tag: "重要" } }]);
  const [saving, setSaving] = useState(false);

  const load = () => api.listRules().then(setRules).catch(() => setRules([]));

  useEffect(() => {
    load();
  }, []);

  const addConditionRow = () => setConditions([...conditions, { field: RULE_FIELDS[0], operator: "contains", value: "" }]);
  const updateCondition = (index: number, patch: Partial<RuleCondition>) =>
    setConditions(conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  const removeCondition = (index: number) => setConditions(conditions.filter((_, i) => i !== index));

  const createRule = async () => {
    if (!name || conditions.some((c) => !c.value)) return;
    setSaving(true);
    try {
      await api.createRule({ name, priority, match_mode: matchMode, conditions, actions });
      setName("");
      setConditions([{ field: RULE_FIELDS[0], operator: "contains", value: "" }]);
      await load();
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (id: string) => {
    await api.toggleRule(id);
    await load();
  };

  return (
    <section className="admin-panel">
      <p className="ai-empty">「特定企業は必ず重要」「特定キーワードはSlack通知」のようなノーコード条件分岐を設定できます。</p>

      <ul className="rule-list">
        {rules.map((r) => (
          <li key={r.id} className={`rule-card ${r.is_active ? "" : "inactive"}`}>
            <div className="rule-card-header">
              <strong>{r.name}</strong>
              <span>優先度 {r.priority}</span>
              <button onClick={() => toggle(r.id)}>{r.is_active ? "無効化" : "有効化"}</button>
            </div>
            <div className="rule-summary">
              条件({r.match_mode === "all" ? "すべて一致" : "いずれか一致"}):{" "}
              {r.conditions.map((c) => `${c.field} ${c.operator} "${c.value}"`).join(" / ")}
            </div>
            <div className="rule-summary">アクション: {r.actions.map((a) => a.type).join(", ")}</div>
          </li>
        ))}
        {rules.length === 0 && <li className="ai-empty">ルールはまだありません。</li>}
      </ul>

      <div className="rule-create-form">
        <h4>新規ルール作成</h4>
        <input placeholder="ルール名" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="rule-inline-fields">
          <label>
            優先度
            <input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} />
          </label>
          <label>
            条件の一致方法
            <select value={matchMode} onChange={(e) => setMatchMode(e.target.value as "all" | "any")}>
              <option value="all">すべて一致</option>
              <option value="any">いずれか一致</option>
            </select>
          </label>
        </div>

        {conditions.map((c, i) => (
          <div key={i} className="rule-condition-row">
            <select value={c.field} onChange={(e) => updateCondition(i, { field: e.target.value })}>
              {RULE_FIELDS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <select value={c.operator} onChange={(e) => updateCondition(i, { operator: e.target.value })}>
              {RULE_OPERATORS.map((op) => (
                <option key={op} value={op}>
                  {op}
                </option>
              ))}
            </select>
            <input placeholder="値" value={c.value} onChange={(e) => updateCondition(i, { value: e.target.value })} />
            <button onClick={() => removeCondition(i)}>削除</button>
          </div>
        ))}
        <button onClick={addConditionRow}>条件を追加</button>

        <label className="rule-action-field">
          アクション種別（tag / notify_slack 等）
          <input
            value={actions[0]?.type ?? ""}
            onChange={(e) => setActions([{ ...actions[0], type: e.target.value }])}
          />
        </label>
        <label className="rule-action-field">
          タグ名（アクションtype=tagの場合）
          <input
            value={actions[0]?.params?.tag ?? ""}
            onChange={(e) => setActions([{ ...actions[0], params: { ...actions[0]?.params, tag: e.target.value } }])}
          />
        </label>

        <button className="primary" onClick={createRule} disabled={saving}>
          ルール作成
        </button>
      </div>
    </section>
  );
}

function PluginsPanel() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [webhookUrls, setWebhookUrls] = useState<Record<string, string>>({});

  const load = () => api.listPlugins().then(setPlugins).catch(() => setPlugins([]));

  useEffect(() => {
    load();
  }, []);

  const toggle = async (plugin: PluginInfo) => {
    await api.updatePlugin(plugin.key, {
      is_enabled: !plugin.is_enabled,
      config: webhookUrls[plugin.key] ? { webhook_url: webhookUrls[plugin.key] } : {},
    });
    await load();
  };

  return (
    <section className="admin-panel">
      <ul className="plugin-list">
        {plugins.map((p) => (
          <li key={p.key} className="plugin-card">
            <div className="plugin-card-header">
              <strong>{p.name}</strong>
              <span className="task-badge">v{p.version}</span>
              <button onClick={() => toggle(p)}>{p.is_enabled ? "無効化" : "有効化"}</button>
            </div>
            <input
              placeholder="Slack Webhook URL（サンプルプラグイン用）"
              value={webhookUrls[p.key] ?? ""}
              onChange={(e) => setWebhookUrls({ ...webhookUrls, [p.key]: e.target.value })}
            />
          </li>
        ))}
        {plugins.length === 0 && <li className="ai-empty">プラグインが見つかりません（plugins/ ディレクトリを確認してください）。</li>}
      </ul>
    </section>
  );
}
