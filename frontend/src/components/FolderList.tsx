import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

const DEFAULT_FOLDERS = ["INBOX", "Drafts", "Sent", "Archive", "Trash", "案件", "人材", "要返信", "重要"];

// Classification-based auto-routing (see backend analysis_service.py's
// _route_to_category_folder) can file a message into one of these even on
// an account whose real IMAP mailbox has none of them (e.g. a fresh Gmail
// account only has INBOX/Junk/Trash/Sent/Drafts) — always show them so a
// routed message never effectively disappears from the sidebar.
const ROUTING_FOLDERS = ["案件", "人材", "要返信", "重要", "Junk"];

function withRoutingFolders(folders: string[]): string[] {
  const missing = ROUTING_FOLDERS.filter((f) => !folders.includes(f));
  return [...folders, ...missing];
}

// IMAP servers return folders in their own order (often not INBOX-first —
// e.g. alphabetical, which buries INBOX under "Junk"/"Trash"). Pin it to
// the top; leave the rest in whatever order the server gave.
function sortFolders(folders: string[]): string[] {
  const withoutInbox = folders.filter((f) => f !== "INBOX");
  return folders.includes("INBOX") ? ["INBOX", ...withoutInbox] : folders;
}

interface Props {
  active: string;
  onSelect: (folder: string) => void;
}

export function FolderList({ active, onSelect }: Props) {
  const { t } = useTranslation();
  // null = still resolving which folder list to show. Starting from
  // DEFAULT_FOLDERS and swapping to the real list once fetched caused a
  // visible flash (wrong folders shown for a moment, then replaced) —
  // showing nothing until resolved avoids that instead.
  const [folders, setFolders] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Real IMAP folders for the first configured account, falling back to
    // the default set when no account is configured yet or the server is
    // unreachable — this used to be a permanently hardcoded list.
    api
      .listAccounts()
      .then(async (accounts) => {
        const imapAccount = accounts.find((a) => a.protocol === "imap_smtp");
        if (!imapAccount) {
          if (!cancelled) setFolders(withRoutingFolders(DEFAULT_FOLDERS));
          return;
        }
        try {
          const realFolders = await api.getAccountFolders(imapAccount.id);
          if (!cancelled) {
            setFolders(sortFolders(withRoutingFolders(realFolders.length > 0 ? realFolders : DEFAULT_FOLDERS)));
          }
        } catch {
          if (!cancelled) setFolders(withRoutingFolders(DEFAULT_FOLDERS));
        }
      })
      .catch(() => {
        if (!cancelled) setFolders(withRoutingFolders(DEFAULT_FOLDERS));
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (folders === null) {
    return <nav className="folder-list" aria-label={t("folder.aria")} />;
  }

  return (
    <nav className="folder-list" aria-label={t("folder.aria")}>
      {folders.map((folder) => (
        <button
          key={folder}
          className={`folder-item ${folder === active ? "active" : ""}`}
          onClick={() => onSelect(folder)}
        >
          {folder}
        </button>
      ))}
    </nav>
  );
}
