const FOLDERS = ["INBOX", "Drafts", "Sent", "案件", "人材", "要返信", "重要"];

interface Props {
  active: string;
  onSelect: (folder: string) => void;
}

export function FolderList({ active, onSelect }: Props) {
  return (
    <nav className="folder-list" aria-label="フォルダ">
      {FOLDERS.map((folder) => (
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
