import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { Language } from "./translations";
import { translations } from "./translations";

interface I18nValue {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const I18nCtx = createContext<I18nValue | null>(null);

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  // ui_language is a persisted backend setting (see Settings screen), not a
  // per-browser preference — this lets a shared/desktop install keep one
  // consistent language. Starts "ja" and updates once GET /settings resolves.
  const [language, setLanguageState] = useState<Language>("ja");

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        if (s.ui_language === "en" || s.ui_language === "ja") setLanguageState(s.ui_language);
      })
      .catch(() => {
        // Backend unreachable at startup: keep the "ja" default: App.tsx
        // already surfaces the connection error elsewhere.
      });
  }, []);

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    api.updateSettings({ ui_language: lang }).catch(() => {
      // Best-effort persistence; the in-memory switch above still applies
      // for the rest of this session even if the save fails.
    });
  };

  const value = useMemo<I18nValue>(
    () => ({
      language,
      setLanguage,
      t: (key, params) => interpolate(translations[language][key as keyof (typeof translations)["ja"]] ?? key, params),
    }),
    [language]
  );

  return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>;
}

export function useTranslation(): I18nValue {
  const ctx = useContext(I18nCtx);
  if (!ctx) throw new Error("useTranslation must be used within I18nProvider");
  return ctx;
}
