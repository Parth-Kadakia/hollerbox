import type { FileAttachment } from "../api/types";

const API_BASE = "/api";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function Attachment({ att }: { att: FileAttachment }) {
  const fullUrl = `${API_BASE}${att.url}`;
  if (att.kind === "image") {
    return (
      <a href={fullUrl} target="_blank" rel="noreferrer" className="block">
        <img
          src={fullUrl}
          alt={att.name}
          className="rounded-md max-h-96 w-auto border border-ink/10"
        />
        <div className="mt-1 text-[11px] text-ink/50">{att.name}</div>
      </a>
    );
  }
  return (
    <a
      href={fullUrl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-2 rounded-md border border-ink/15 px-2 py-1 text-xs text-ink hover:bg-ink/5"
    >
      📎 {att.name}
      {typeof att.size_bytes === "number" && (
        <span className="text-ink/40">({formatBytes(att.size_bytes)})</span>
      )}
    </a>
  );
}
