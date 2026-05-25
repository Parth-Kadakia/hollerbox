import { useEffect, useRef, useState } from "react";
import {
  approveRun,
  createConversation,
  listMessages,
  rejectRun,
  sendMessage,
  streamConversationEvents,
} from "../api/client";
import type { ChatMessage, MessageAttachment } from "../api/types";
import { ErrorBox } from "./Dashboard";

const API_BASE = "/api";

export default function ChatPage() {
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  // Create a conversation on first render so the user can start typing.
  useEffect(() => {
    createConversation()
      .then((c) => setConvId(c.id))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  // Auto-scroll to bottom on new messages. jsdom doesn't implement scrollTo,
  // so we guard it for tests; real browsers always have it.
  useEffect(() => {
    const el = threadRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  // Subscribe to server-side events whenever the worker might be progressing.
  // We open a stream right after a user sends a message and close on `done`.
  const streamRef = useRef<EventSource | null>(null);
  function openStream(id: string) {
    streamRef.current?.close();
    streamRef.current = streamConversationEvents(
      id,
      (m) =>
        setMessages((prev) =>
          prev.some((p) => p.id === m.id) ? prev : [...prev, m],
        ),
      () => {
        streamRef.current = null;
      },
    );
  }
  useEffect(() => () => streamRef.current?.close(), []);

  async function send() {
    if (!convId || !input.trim() || busy) return;
    setBusy(true);
    setError(null);
    const text = input;
    setInput("");
    try {
      const resp = await sendMessage(convId, text);
      setMessages(resp.messages);
      openStream(convId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function approveOrReject(runId: string, action: "approve" | "reject") {
    if (!convId) return;
    setBusy(true);
    try {
      if (action === "approve") await approveRun(runId);
      else await rejectRun(runId);
      const fresh = await listMessages(convId);
      setMessages(fresh);
      openStream(convId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-4rem)] -my-8 -mr-8 pr-8 py-8 max-w-3xl mx-auto">
      <header className="pb-3 border-b border-ink/10">
        <h1 className="text-xl font-semibold tracking-tight">Chat</h1>
        <p className="text-xs text-ink/50 mt-1">
          Text the engine. It picks a workflow, runs it, and asks before
          anything destructive.
        </p>
      </header>

      {error && <ErrorBox error={error} />}

      <div
        ref={threadRef}
        className="flex-1 overflow-y-auto py-6 space-y-4"
      >
        {messages.length === 0 && (
          <p className="text-center text-sm text-ink/50 pt-12">
            Say hello, or describe a task — e.g. "run the demo workflow".
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            msg={m}
            busy={busy}
            onApprove={() => m.run_id && approveOrReject(m.run_id, "approve")}
            onReject={() => m.run_id && approveOrReject(m.run_id, "reject")}
          />
        ))}
        {busy && (
          <div className="text-xs text-ink/50 italic flex items-center gap-2">
            <Dots /> thinking…
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="border-t border-ink/10 pt-3 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={convId ? "Message…" : "starting conversation…"}
          disabled={!convId || busy}
          className="flex-1 rounded-md border border-ink/15 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        />
        <button
          type="submit"
          disabled={!convId || busy || !input.trim()}
          className="rounded-md bg-terracotta px-4 py-2 text-sm font-medium text-white hover:bg-terracotta/90 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function MessageBubble({
  msg,
  busy,
  onApprove,
  onReject,
}: {
  msg: ChatMessage;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const isUser = msg.role === "user";
  const isApproval = msg.kind === "approval_request";
  const isError = msg.kind === "error";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={[
          "max-w-[80%] rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap break-words",
          isUser
            ? "bg-terracotta text-white"
            : isApproval
              ? "bg-amber-50 border border-amber-300 text-amber-900"
              : isError
                ? "bg-red-50 border border-red-200 text-red-800"
                : "bg-ink/5 text-ink",
        ].join(" ")}
      >
        <BodyWithMarkdownLite text={msg.content} />
        {msg.attachments.length > 0 && (
          <div className="mt-3 space-y-2">
            {msg.attachments.map((a) => (
              <Attachment key={a.path} att={a} />
            ))}
          </div>
        )}
        {isApproval && msg.run_id && (
          <div className="mt-3 flex gap-2">
            <button
              disabled={busy}
              onClick={onApprove}
              className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Yes, approve
            </button>
            <button
              disabled={busy}
              onClick={onReject}
              className="rounded-md border border-amber-300 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
            >
              No, cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Attachment({ att }: { att: MessageAttachment }) {
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

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// Tiny renderer: backticks → <code>, **bold** → <strong>. Avoids pulling in
// a full markdown lib for chat that's mostly plain text.
function BodyWithMarkdownLite({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      parts.push(
        <code key={parts.length} className="font-mono text-[12px] px-1 rounded bg-black/10">
          {tok.slice(1, -1)}
        </code>,
      );
    } else {
      parts.push(<strong key={parts.length}>{tok.slice(2, -2)}</strong>);
    }
    last = regex.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function Dots() {
  return (
    <span className="inline-flex gap-0.5">
      <span className="w-1 h-1 rounded-full bg-ink/40 animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="w-1 h-1 rounded-full bg-ink/40 animate-bounce" style={{ animationDelay: "120ms" }} />
      <span className="w-1 h-1 rounded-full bg-ink/40 animate-bounce" style={{ animationDelay: "240ms" }} />
    </span>
  );
}
