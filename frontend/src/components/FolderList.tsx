import { useEffect, useState } from "react";
import { api } from "../api/client";

const DEFAULT_FOLDERS = ["INBOX", "Drafts", "Sent", "Archive", "Trash", "案件", "人材", "要返信", "重要"];

interface Props {
  active: string;
  onSelect: (folder: string) => void;
}

export function FolderList({ active, onSelect }: Props) {
  const [folders, setFolders] = useState<string[]>(DEFAULT_FOLDERS);

  useEffect(() => {
    // Real IMAP folders for the first configured account, falling back to
    // the default set when no account is configured yet or the server is
    // unreachable — this used to be a permanently hardcoded list.
    api
      .listAccounts()
      .then(async (accounts) => {
        const imapAccount = accounts.find((a) => a.protocol === "imap_smtp");
        if (!imapAccount) return;
        const realFolders = await api.getAccountFolders(imapAccount.id);
        if (realFolders.length > 0) setFolders(realFolders);
      })
      .catch(() => {
        // Keep the default folder set; account/IMAP may not be configured yet.
      });
  }, []);

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
