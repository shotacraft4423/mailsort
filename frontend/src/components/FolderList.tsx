import { useEffect, useState } from "react";
import { api } from "../api/client";

const DEFAULT_FOLDERS = ["INBOX", "Drafts", "Sent", "Archive", "Trash", "案件", "人材", "要返信", "重要"];

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
          if (!cancelled) setFolders(DEFAULT_FOLDERS);
          return;
        }
        try {
          const realFolders = await api.getAccountFolders(imapAccount.id);
          if (!cancelled) setFolders(realFolders.length > 0 ? sortFolders(realFolders) : DEFAULT_FOLDERS);
        } catch {
          if (!cancelled) setFolders(DEFAULT_FOLDERS);
        }
      })
      .catch(() => {
        if (!cancelled) setFolders(DEFAULT_FOLDERS);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (folders === null) {
    return <nav className="folder-list" aria-label="フォルダ" />;
  }

  return (
    <nav className="folder-list" aria-label="フォルダ">
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
