import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

const DEFAULT_FOLDERS = ["INBOX", "Drafts", "Sent", "Archive", "Trash", "案件", "人材", "要返信", "重要"];

// Classification-based auto-routing (see backend analysis_service.py's
// _route_to_category_folder) can file a message into one of these even on
// an account whose real IMAP mailbox has none of them (e.g. a fresh Gmail
// account only has INBOX/Junk/Trash/Sent/Drafts) — always show them so a
// routed message never effectively disappears from the sidebar. A rule's
// "move_to_folder" action can also target an arbitrary custom folder name
// (see GET /mail/folders below), so this is just the pre-emptive baseline
// shown even before any mail has actually been routed there yet.
const ROUTING_FOLDERS = ["案件", "人材", "要返信", "重要", "Junk"];

function dedupe(folders: string[]): string[] {
  return [...new Set(folders)];
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

    Promise.all([api.listAccounts(), api.listLocalFolders().catch(() => [] as string[])])
      .then(async ([accounts, localFolders]) => {
        const imapAccount = accounts.find((a) => a.protocol === "imap_smtp");
        let base = DEFAULT_FOLDERS;
        if (imapAccount) {
          try {
            const realFolders = await api.getAccountFolders(imapAccount.id);
            base = realFolders.length > 0 ? realFolders : DEFAULT_FOLDERS;
          } catch {
            base = DEFAULT_FOLDERS;
          }
        }
        if (!cancelled) setFolders(sortFolders(dedupe([...base, ...localFolders, ...ROUTING_FOLDERS])));
      })
      .catch(() => {
        if (!cancelled) setFolders(dedupe([...DEFAULT_FOLDERS, ...ROUTING_FOLDERS]));
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
