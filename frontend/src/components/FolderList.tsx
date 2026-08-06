import { useEffect, useState } from "react";
import type { AccountSummary } from "../api/client";
import { api } from "../api/client";
import { useTranslation } from "../i18n/I18nContext";

const DEFAULT_FOLDERS = ["INBOX", "Drafts", "Sent", "Archive", "Trash", "案件", "人材", "要返信", "重要"];

// Classification-based auto-routing (see backend analysis_service.py's
// _route_to_category_folder) can file a message into one of these even on
// an account whose real IMAP mailbox has none of them (e.g. a fresh Gmail
// account only has INBOX/Junk/Trash/Sent/Drafts) — always show them in the
// unified view so a routed message never effectively disappears from the
// sidebar. A rule's "move_to_folder" action can also target an arbitrary
// custom folder name (see GET /mail/folders below).
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
  activeAccountId: string | null;
  onSelect: (folder: string, accountId: string | null) => void;
}

export function FolderList({ active, activeAccountId, onSelect }: Props) {
  const { t } = useTranslation();
  // null = still resolving which folder list to show. Starting from
  // DEFAULT_FOLDERS and swapping to the real list once fetched caused a
  // visible flash (wrong folders shown for a moment, then replaced) —
  // showing nothing until resolved avoids that instead.
  const [unifiedFolders, setUnifiedFolders] = useState<string[] | null>(null);
  const [imapAccounts, setImapAccounts] = useState<AccountSummary[]>([]);
  const [accountFolders, setAccountFolders] = useState<Record<string, string[]>>({});
  const [collapsedAccounts, setCollapsedAccounts] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;

    Promise.all([api.listAccounts(), api.listLocalFolders().catch(() => [] as string[])])
      .then(async ([accounts, localFolders]) => {
        const accountsWithImap = accounts.filter((a) => a.protocol === "imap_smtp");
        if (!cancelled) setImapAccounts(accountsWithImap);

        let base = DEFAULT_FOLDERS;
        if (accountsWithImap[0]) {
          try {
            const realFolders = await api.getAccountFolders(accountsWithImap[0].id);
            base = realFolders.length > 0 ? realFolders : DEFAULT_FOLDERS;
          } catch {
            base = DEFAULT_FOLDERS;
          }
        }
        if (!cancelled) setUnifiedFolders(sortFolders(dedupe([...base, ...localFolders, ...ROUTING_FOLDERS])));

        // Only worth fetching per-account folder lists once there's
        // actually more than one account to distinguish between —
        // "複数アカウントの場合、表示される場所を分けてください".
        if (accountsWithImap.length > 1) {
          const entries = await Promise.all(
            accountsWithImap.map(async (account): Promise<[string, string[]]> => {
              try {
                const folders = await api.getAccountFolders(account.id);
                return [account.id, sortFolders(folders.length > 0 ? folders : DEFAULT_FOLDERS)];
              } catch {
                return [account.id, sortFolders(DEFAULT_FOLDERS)];
              }
            })
          );
          if (!cancelled) setAccountFolders(Object.fromEntries(entries));
        }
      })
      .catch(() => {
        if (!cancelled) setUnifiedFolders(dedupe([...DEFAULT_FOLDERS, ...ROUTING_FOLDERS]));
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const toggleAccountCollapsed = (accountId: string) =>
    setCollapsedAccounts((prev) => ({ ...prev, [accountId]: !prev[accountId] }));

  if (unifiedFolders === null) {
    return <nav className="folder-list" aria-label={t("folder.aria")} />;
  }

  return (
    <nav className="folder-list" aria-label={t("folder.aria")}>
      {imapAccounts.length > 1 && <div className="folder-section-label">{t("folder.unifiedHeading")}</div>}
      {unifiedFolders.map((folder) => (
        <button
          key={folder}
          className={`folder-item ${folder === active && activeAccountId === null ? "active" : ""}`}
          onClick={() => onSelect(folder, null)}
        >
          {folder}
        </button>
      ))}

      {imapAccounts.length > 1 &&
        imapAccounts.map((account) => (
          <div key={account.id} className="folder-account-group">
            <button className="folder-account-header" onClick={() => toggleAccountCollapsed(account.id)}>
              <span className="folder-account-chevron">{collapsedAccounts[account.id] ? "▸" : "▾"}</span>
              {account.email_address}
            </button>
            {!collapsedAccounts[account.id] &&
              (accountFolders[account.id] ?? []).map((folder) => (
                <button
                  key={folder}
                  className={`folder-item folder-item-nested ${
                    folder === active && activeAccountId === account.id ? "active" : ""
                  }`}
                  onClick={() => onSelect(folder, account.id)}
                >
                  {folder}
                </button>
              ))}
          </div>
        ))}
    </nav>
  );
}
