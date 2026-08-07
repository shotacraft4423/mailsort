import { useEffect, useState } from "react";
import type { CustomFolder, PluginInfo, PromptTemplate, Rule, RuleAction, RuleCondition } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

type AdminTab = "prompts" | "rules" | "plugins" | "folders";

export function AdminView() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<AdminTab>("prompts");
  // Set by FoldersPanel's "set routing rule" button so RulesPanel can open
  // pre-filled with a move_to_folder action targeting that folder — without
  // this, "add a folder" and "define what routes into it" would be two
  // disconnected screens the user has to correlate by typing the folder
  // name into the rule form themselves.
  const [rulePrefillFolder, setRulePrefillFolder] = useState<string | null>(null);

  const requestRuleForFolder = (folder: string) => {
    setRulePrefillFolder(folder);
    setTab("rules");
  };

  return (
    <div className="view-container admin-view">
      <h2>{t("nav.admin")}</h2>
      <div className="admin-tabs">
        <button className={tab === "prompts" ? "active" : ""} onClick={() => setTab("prompts")}>
          {t("admin.tabPrompts")}
        </button>
        <button className={tab === "rules" ? "active" : ""} onClick={() => setTab("rules")}>
          {t("admin.tabRules")}
        </button>
        <button className={tab === "folders" ? "active" : ""} onClick={() => setTab("folders")}>
          {t("admin.tabFolders")}
        </button>
        <button className={tab === "plugins" ? "active" : ""} onClick={() => setTab("plugins")}>
          {t("admin.tabPlugins")}
        </button>
      </div>

      {tab === "prompts" && <PromptsPanel />}
      {tab === "rules" && (
        <RulesPanel prefillFolder={rulePrefillFolder} onPrefillConsumed={() => setRulePrefillFolder(null)} />
      )}
      {tab === "plugins" && <PluginsPanel />}
      {tab === "folders" && <FoldersPanel onRequestRuleForFolder={requestRuleForFolder} />}
    </div>
  );
}

// Underlying values sent to the backend never change with display
// language — only the label shown in the dropdown does (see
// translations.ts "task.*" / "ruleField.*" / "ruleOperator.*" / "actionType.*").
//
// Limited to the two tasks the pipeline actually reads a PromptTemplate
// for (see backend/app/api/routes/prompts.py's _DEFAULTS_BY_TASK comment).
// summary/reply_suggestion/duplicate_check/chat used to be selectable here
// too, but creating a template for them did nothing — no service ever
// calls get_active_prompt() for those tasks — which is exactly the kind of
// "what do I even put here" confusion this screen should not produce.
const TASKS = ["classification", "extraction"];

function PromptsPanel() {
  const { t } = useTranslation();
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

  const fillFromDefault = async () => {
    const defaults = await api.getPromptDefaults(form.task);
    setForm({ ...form, system_prompt: defaults.system_prompt, user_prompt_template: defaults.user_prompt_template });
  };

  const deleteTemplate = async (templateId: string) => {
    await api.deletePrompt(templateId);
    await load();
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
      <p className="ai-empty">{t("admin.promptsHelp")}</p>

      <ul className="prompt-list">
        {templates.map((tpl) => (
          <li key={tpl.id} className="prompt-card">
            <div className="prompt-card-header">
              <strong>{tpl.name}</strong>
              <span className="task-badge">{t(`task.${tpl.task}`)}</span>
              <button onClick={() => (expanded === tpl.id ? setExpanded(null) : startEditVersion(tpl))}>
                {expanded === tpl.id ? t("common.close") : t("admin.addVersion")}
              </button>
              <button onClick={() => deleteTemplate(tpl.id)}>{t("admin.deleteTemplate")}</button>
            </div>
            {expanded === tpl.id && (
              <div className="prompt-version-form">
                <label>
                  {t("admin.systemPromptLabel")}
                  <textarea
                    rows={4}
                    value={versionDraft.system_prompt}
                    onChange={(e) => setVersionDraft({ ...versionDraft, system_prompt: e.target.value })}
                  />
                </label>
                <label>
                  {t("admin.userPromptTemplateLabel")}
                  <textarea
                    rows={4}
                    value={versionDraft.user_prompt_template}
                    onChange={(e) => setVersionDraft({ ...versionDraft, user_prompt_template: e.target.value })}
                  />
                </label>
                <label>
                  {t("admin.notesLabel")}
                  <input value={versionDraft.notes} onChange={(e) => setVersionDraft({ ...versionDraft, notes: e.target.value })} />
                </label>
                <button className="primary" onClick={() => addVersion(tpl.id)} disabled={saving}>
                  {t("admin.saveAndActivate")}
                </button>
              </div>
            )}
          </li>
        ))}
        {templates.length === 0 && <li className="ai-empty">{t("admin.noPrompts")}</li>}
      </ul>

      <div className="prompt-create-form">
        <h4>{t("admin.newTemplateHeading")}</h4>
        <input placeholder={t("admin.namePlaceholder")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <label className="rule-inline-fields">
          {t("admin.taskLabel")}
          <select value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })}>
            {TASKS.map((taskKey) => (
              <option key={taskKey} value={taskKey}>
                {t(`task.${taskKey}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={fillFromDefault} disabled={saving}>
          {t("admin.fillFromDefault")}
        </button>
        <textarea
          rows={3}
          placeholder={t("admin.systemPromptLabel")}
          value={form.system_prompt}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
        />
        <textarea
          rows={3}
          placeholder={t("admin.userPromptTemplateLabel")}
          value={form.user_prompt_template}
          onChange={(e) => setForm({ ...form, user_prompt_template: e.target.value })}
        />
        <button onClick={createTemplate} disabled={saving}>
          {t("common.create")}
        </button>
      </div>
    </section>
  );
}

const RULE_FIELDS = ["subject", "sender_address", "sender_name", "body_text", "mail_type", "priority", "ai_prompt"];
const RULE_OPERATORS = ["equals", "contains", "starts_with", "in"];
const ACTION_TYPES = ["tag", "move_to_folder", "notify_slack"];
const AI_PROMPT_FIELD = "ai_prompt";

const emptyCondition = (): RuleCondition => ({ field: RULE_FIELDS[0], operator: "contains", value: "" });
const emptyAction = (): RuleAction => ({ type: "tag", params: { tag: "重要" } });

interface RulesPanelProps {
  prefillFolder?: string | null;
  onPrefillConsumed?: () => void;
}

function RulesPanel({ prefillFolder, onPrefillConsumed }: RulesPanelProps) {
  const { t } = useTranslation();
  const [rules, setRules] = useState<Rule[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(100);
  const [matchMode, setMatchMode] = useState<"all" | "any">("all");
  const [conditions, setConditions] = useState<RuleCondition[]>([emptyCondition()]);
  const [actions, setActions] = useState<RuleAction[]>([emptyAction()]);
  const [saving, setSaving] = useState(false);
  const [reordering, setReordering] = useState(false);

  const load = () => api.listRules().then(setRules).catch(() => setRules([]));

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!prefillFolder) return;
    setActions([{ type: "move_to_folder", params: { folder: prefillFolder } }]);
    setName((prev) => prev || t("admin.rulePrefillName", { folder: prefillFolder }));
    onPrefillConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillFolder]);

  const resetForm = () => {
    setEditingId(null);
    setName("");
    setDescription("");
    setPriority(100);
    setMatchMode("all");
    setConditions([emptyCondition()]);
    setActions([emptyAction()]);
  };

  // "編集機能" — every field the create form manages gets loaded back in,
  // so editing a rule is the exact same form instead of a separate,
  // narrower one that would drift out of sync with what create supports.
  const startEdit = (rule: Rule) => {
    setEditingId(rule.id);
    setName(rule.name);
    setDescription(rule.description ?? "");
    setPriority(rule.priority);
    setMatchMode(rule.match_mode === "any" ? "any" : "all");
    setConditions(rule.conditions.length ? rule.conditions.map((c) => ({ ...c })) : [emptyCondition()]);
    setActions(rule.actions.length ? rule.actions.map((a) => ({ ...a, params: { ...a.params } })) : [emptyAction()]);
  };

  const addConditionRow = () => setConditions([...conditions, emptyCondition()]);
  const updateCondition = (index: number, patch: Partial<RuleCondition>) =>
    setConditions(conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  const removeCondition = (index: number) => setConditions(conditions.filter((_, i) => i !== index));

  const addActionRow = () => setActions([...actions, emptyAction()]);
  const updateAction = (index: number, patch: Partial<RuleAction>) =>
    setActions(actions.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  const removeAction = (index: number) => setActions(actions.filter((_, i) => i !== index));

  const saveRule = async () => {
    if (!name || conditions.some((c) => !c.value)) return;
    setSaving(true);
    try {
      if (editingId) {
        await api.updateRule(editingId, { name, description, priority, match_mode: matchMode, conditions, actions });
      } else {
        await api.createRule({ name, description, priority, match_mode: matchMode, conditions, actions });
      }
      resetForm();
      await load();
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (id: string) => {
    await api.toggleRule(id);
    await load();
  };

  const deleteRule = async (id: string) => {
    if (editingId === id) resetForm();
    await api.deleteRule(id);
    await load();
  };

  // "優先度の並び替えができるように" — up/down buttons swap this rule with
  // its neighbor in the currently-displayed (priority-sorted) order and
  // send the whole new order to /rules/reorder, which reassigns priority
  // by position; simpler and less error-prone for most users than raw
  // drag-and-drop, and works the same on touch devices.
  const move = async (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= rules.length || reordering) return;
    const reordered = [...rules];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    setRules(reordered);
    setReordering(true);
    try {
      await api.reorderRules(reordered.map((r) => r.id));
      await load();
    } finally {
      setReordering(false);
    }
  };

  const actionLabel = (action: RuleAction) => {
    const label = ACTION_TYPES.includes(action.type) ? t(`actionType.${action.type}`) : action.type;
    if (action.type === "tag" && action.params?.tag) return `${label} 「${action.params.tag}」`;
    if (action.type === "move_to_folder" && action.params?.folder) return `${label} 「${action.params.folder}」`;
    return label;
  };
  const fieldLabel = (field: string) => (RULE_FIELDS.includes(field) ? t(`ruleField.${field}`) : field);
  const operatorLabel = (op: string) => (RULE_OPERATORS.includes(op) ? t(`ruleOperator.${op}`) : op);
  const conditionSummary = (c: RuleCondition) =>
    c.field === AI_PROMPT_FIELD ? `${fieldLabel(c.field)} 「${c.value}」` : `${fieldLabel(c.field)} ${operatorLabel(c.operator)} "${c.value}"`;

  return (
    <section className="admin-panel">
      <p className="ai-empty">{t("admin.rulesHelp")}</p>

      <ul className="rule-list">
        {rules.map((r, i) => (
          <li key={r.id} className={`rule-card ${r.is_active ? "" : "inactive"}`}>
            <div className="rule-card-header">
              <div className="rule-order-buttons">
                <button disabled={i === 0 || reordering} onClick={() => move(i, -1)} title={t("admin.moveUp")}>
                  ▲
                </button>
                <button disabled={i === rules.length - 1 || reordering} onClick={() => move(i, 1)} title={t("admin.moveDown")}>
                  ▼
                </button>
              </div>
              <strong>{r.name}</strong>
              <span>{t("admin.priorityLabel", { priority: r.priority })}</span>
              <button onClick={() => startEdit(r)}>{t("common.edit")}</button>
              <button onClick={() => toggle(r.id)}>{r.is_active ? t("admin.disable") : t("admin.enable")}</button>
              <button onClick={() => deleteRule(r.id)}>{t("common.delete")}</button>
            </div>
            {r.description && <div className="rule-summary rule-description">{r.description}</div>}
            <div className="rule-summary">
              {r.match_mode === "all" ? t("admin.conditionsSummaryAll") : t("admin.conditionsSummaryAny")}{" "}
              {r.conditions.map(conditionSummary).join(" / ")}
            </div>
            <div className="rule-summary">{t("admin.actionsSummary", { actions: r.actions.map(actionLabel).join(", ") })}</div>
          </li>
        ))}
        {rules.length === 0 && <li className="ai-empty">{t("admin.noRules")}</li>}
      </ul>

      <div className="rule-create-form">
        <h4>{editingId ? t("admin.editRuleHeading") : t("admin.newRuleHeading")}</h4>
        <input placeholder={t("admin.ruleNamePlaceholder")} value={name} onChange={(e) => setName(e.target.value)} />
        <textarea
          className="rule-description-input"
          placeholder={t("admin.ruleDescriptionPlaceholder")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="rule-inline-fields">
          <label>
            {t("admin.priorityFieldLabel")}
            <input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} />
          </label>
          <label>
            {t("admin.matchModeLabel")}
            <select value={matchMode} onChange={(e) => setMatchMode(e.target.value as "all" | "any")}>
              <option value="all">{t("admin.matchModeAll")}</option>
              <option value="any">{t("admin.matchModeAny")}</option>
            </select>
          </label>
        </div>

        {conditions.map((c, i) => (
          <div key={i} className="rule-condition-row">
            <select value={c.field} onChange={(e) => updateCondition(i, { field: e.target.value, operator: e.target.value === AI_PROMPT_FIELD ? "matches" : c.operator })}>
              {RULE_FIELDS.map((f) => (
                <option key={f} value={f}>
                  {t(`ruleField.${f}`)}
                </option>
              ))}
            </select>
            {c.field === AI_PROMPT_FIELD ? (
              <textarea
                className="rule-ai-prompt-input"
                placeholder={t("admin.aiPromptValuePlaceholder")}
                value={c.value}
                onChange={(e) => updateCondition(i, { value: e.target.value })}
              />
            ) : (
              <>
                <select value={c.operator} onChange={(e) => updateCondition(i, { operator: e.target.value })}>
                  {RULE_OPERATORS.map((op) => (
                    <option key={op} value={op}>
                      {t(`ruleOperator.${op}`)}
                    </option>
                  ))}
                </select>
                <input
                  placeholder={t("admin.valuePlaceholder")}
                  value={c.value}
                  onChange={(e) => updateCondition(i, { value: e.target.value })}
                />
              </>
            )}
            <button onClick={() => removeCondition(i)}>{t("common.delete")}</button>
          </div>
        ))}
        <button onClick={addConditionRow}>{t("admin.addCondition")}</button>
        {conditions.some((c) => c.field === AI_PROMPT_FIELD) && <p className="ai-empty rule-ai-prompt-help">{t("admin.aiPromptHelp")}</p>}

        {actions.map((a, i) => (
          <div key={i} className="rule-action-row">
            <label className="rule-action-field">
              {t("admin.actionTypeLabel")}
              <select value={a.type} onChange={(e) => updateAction(i, { type: e.target.value })}>
                {ACTION_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`actionType.${type}`)}
                  </option>
                ))}
              </select>
            </label>
            {a.type === "move_to_folder" ? (
              <label className="rule-action-field">
                {t("admin.targetFolderLabel")}
                <input
                  placeholder={t("admin.targetFolderPlaceholder")}
                  value={a.params?.folder ?? ""}
                  onChange={(e) => updateAction(i, { params: { ...a.params, folder: e.target.value } })}
                />
              </label>
            ) : a.type === "tag" ? (
              <label className="rule-action-field">
                {t("admin.tagNameLabel")}
                <input value={a.params?.tag ?? ""} onChange={(e) => updateAction(i, { params: { ...a.params, tag: e.target.value } })} />
              </label>
            ) : null}
            <button onClick={() => removeAction(i)}>{t("common.delete")}</button>
          </div>
        ))}
        <button onClick={addActionRow}>{t("admin.addAction")}</button>

        <div className="rule-form-buttons">
          <button className="primary" onClick={saveRule} disabled={saving}>
            {editingId ? t("admin.updateRule") : t("admin.createRule")}
          </button>
          {editingId && (
            <button onClick={resetForm} disabled={saving}>
              {t("admin.cancelEdit")}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

interface FoldersPanelProps {
  onRequestRuleForFolder: (folder: string) => void;
}

function FoldersPanel({ onRequestRuleForFolder }: FoldersPanelProps) {
  const { t } = useTranslation();
  const [folders, setFolders] = useState<CustomFolder[]>([]);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => api.listCustomFolders().then(setFolders).catch(() => setFolders([]));

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createCustomFolder(name.trim());
      setName("");
      await load();
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    await api.deleteCustomFolder(id);
    await load();
  };

  return (
    <section className="admin-panel">
      <p className="ai-empty">{t("admin.foldersHelp")}</p>

      <ul className="rule-list">
        {folders.map((f) => (
          <li key={f.id} className="rule-card">
            <div className="rule-card-header">
              <strong>{f.name}</strong>
              <button onClick={() => onRequestRuleForFolder(f.name)}>{t("admin.setRoutingRule")}</button>
              <button onClick={() => remove(f.id)}>{t("common.delete")}</button>
            </div>
          </li>
        ))}
        {folders.length === 0 && <li className="ai-empty">{t("admin.noFolders")}</li>}
      </ul>

      <div className="prompt-create-form">
        <h4>{t("admin.newFolderHeading")}</h4>
        <input
          placeholder={t("admin.folderNamePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
        />
        <button className="primary" onClick={create} disabled={saving}>
          {t("common.create")}
        </button>
      </div>
    </section>
  );
}

function PluginsPanel() {
  const { t } = useTranslation();
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
      <p className="ai-empty">{t("admin.pluginsHelp")}</p>
      <ul className="plugin-list">
        {plugins.map((p) => (
          <li key={p.key} className="plugin-card">
            <div className="plugin-card-header">
              <strong>{p.name}</strong>
              <span className="task-badge">v{p.version}</span>
              <button onClick={() => toggle(p)}>{p.is_enabled ? t("admin.disable") : t("admin.enable")}</button>
            </div>
            <input
              placeholder={t("admin.webhookPlaceholder")}
              value={webhookUrls[p.key] ?? ""}
              onChange={(e) => setWebhookUrls({ ...webhookUrls, [p.key]: e.target.value })}
            />
          </li>
        ))}
        {plugins.length === 0 && <li className="ai-empty">{t("admin.noPlugins")}</li>}
      </ul>
    </section>
  );
}
