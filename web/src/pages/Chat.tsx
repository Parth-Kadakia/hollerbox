import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  approveRun,
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  listProviders,
  rejectRun,
  sendMessage,
  streamConversationEvents,
} from "../api/client";
import type {
  ChatMessage,
  ConversationSummary,
  ProviderStatus,
} from "../api/types";
import Attachment from "../components/Attachment";
import { ErrorBox } from "./Dashboard";

const PROVIDER_PREF_KEY = "hollerbox.chat.provider";
const MODEL_PREF_KEY = "hollerbox.chat.model";

export default function ChatPage() {
  const navigate = useNavigate();
  const { convId: urlConvId } = useParams<{ convId: string }>();
  const [convId, setConvId] = useState<string | null>(urlConvId ?? null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [provider, setProvider] = useState<string>(
    () => localStorage.getItem(PROVIDER_PREF_KEY) ?? "",
  );
  const [model, setModel] = useState<string>(
    () => localStorage.getItem(MODEL_PREF_KEY) ?? "",
  );
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listProviders()
      .then((p) => setProviders(p.text.filter((x) => x.status === "ready")))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (provider) localStorage.setItem(PROVIDER_PREF_KEY, provider);
    else localStorage.removeItem(PROVIDER_PREF_KEY);
  }, [provider]);
  useEffect(() => {
    if (model) localStorage.setItem(MODEL_PREF_KEY, model);
    else localStorage.removeItem(MODEL_PREF_KEY);
  }, [model]);

  // Load history list on mount and after every change.
  async function refreshList() {
    try {
      const list = await listConversations();
      setConversations(list);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    }
  }

  // Resolve the active conversation:
  //   /chat/:id  → use the id from the URL
  //   /         → if there's a most-recent conv, navigate to it; else create one.
  useEffect(() => {
    if (urlConvId) {
      setConvId(urlConvId);
      return;
    }
    (async () => {
      const list = await refreshList();
      if (list.length > 0) {
        navigate(`/chat/${list[0].id}`, { replace: true });
      } else {
        try {
          const c = await createConversation();
          await refreshList();
          navigate(`/chat/${c.id}`, { replace: true });
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlConvId]);

  // Load messages whenever the active conv changes.
  useEffect(() => {
    if (!convId) return;
    setMessages([]);
    listMessages(convId)
      .then(setMessages)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
    void refreshList();
  }, [convId]);

  async function startNewConversation() {
    try {
      const c = await createConversation();
      await refreshList();
      navigate(`/chat/${c.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function removeConversation(id: string) {
    if (!confirm("Delete this chat? The runs it triggered will stay in /runs.")) return;
    try {
      await deleteConversation(id);
      const list = await refreshList();
      if (id === convId) {
        // Active conversation got deleted — bounce to the next one or start fresh.
        if (list.length > 0) navigate(`/chat/${list[0].id}`, { replace: true });
        else navigate("/", { replace: true });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

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
      const resp = await sendMessage(convId, text, {
        provider: provider || undefined,
        model: model || undefined,
      });
      setMessages(resp.messages);
      openStream(convId);
      void refreshList();
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
    <div className="grid grid-cols-[220px_1fr] gap-6 h-[calc(100dvh-4rem)] -my-8">
      <aside className="border-r border-ink/10 pr-4 py-8 overflow-y-auto">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-xs uppercase tracking-wider text-ink/50">History</h2>
          <button
            onClick={startNewConversation}
            className="text-xs text-terracotta hover:underline"
          >
            + New
          </button>
        </div>
        {conversations.length === 0 && (
          <p className="text-xs text-ink/40">no past chats</p>
        )}
        <ul className="space-y-0.5">
          {conversations.map((c) => {
            const label = c.title?.trim() || "New chat";
            const active = c.id === convId;
            return (
              <li key={c.id} className="group flex items-center gap-1">
                <Link
                  to={`/chat/${c.id}`}
                  className={[
                    "flex-1 min-w-0 px-2 py-1.5 rounded",
                    active
                      ? "bg-terracotta/15 text-terracotta"
                      : "hover:bg-ink/5",
                  ].join(" ")}
                  title={`${label}\n${timeAgo(c.updated_at)}`}
                >
                  <div
                    className={[
                      "text-xs truncate",
                      active ? "font-medium" : "text-ink/80",
                    ].join(" ")}
                  >
                    {label}
                  </div>
                  <div className="text-[10px] text-ink/40 truncate">
                    {timeAgo(c.updated_at)}
                  </div>
                </Link>
                <button
                  onClick={() => removeConversation(c.id)}
                  aria-label="Delete chat"
                  title="Delete chat"
                  className="opacity-0 group-hover:opacity-100 transition-opacity text-ink/40 hover:text-red-600 px-1 text-xs"
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <div className="flex flex-col py-8 pr-8 min-w-0">
        <header className="pb-3 border-b border-ink/10">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Chat</h1>
              <p className="text-xs text-ink/50 mt-1">
                Text the engine. It picks a workflow, runs it, and asks before
                anything destructive.
              </p>
            </div>
            <ModelPicker
              providers={providers}
              provider={provider}
              setProvider={setProvider}
              model={model}
              setModel={setModel}
            />
          </div>
        </header>

        {error && <ErrorBox error={error} />}

        <div ref={threadRef} className="flex-1 overflow-y-auto py-6 space-y-4">
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
    </div>
  );
}

function ModelPicker({
  providers,
  provider,
  setProvider,
  model,
  setModel,
}: {
  providers: ProviderStatus[];
  provider: string;
  setProvider: (p: string) => void;
  model: string;
  setModel: (m: string) => void;
}) {
  const selected = providers.find((p) => p.name === provider);
  // When we have an enumerated model list (Ollama), render a select so the
  // user picks from what's actually installed. Otherwise a freeform input
  // so they can pin any model id the hosted provider supports.
  const knownModels = selected?.models ?? [];
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <select
        value={provider}
        onChange={(e) => {
          setProvider(e.target.value);
          // Reset the model when switching providers — model ids don't
          // cross provider lines.
          setModel("");
        }}
        title="Provider for the chat router"
        className="rounded-md border border-ink/15 bg-white/50 px-2 py-1 focus:outline-none focus:ring-2 focus:ring-terracotta/40"
      >
        <option value="">auto</option>
        {providers.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>
      {knownModels.length > 0 ? (
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          title="Model — populated from the provider's local install"
          className="rounded-md border border-ink/15 bg-white/50 px-2 py-1 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        >
          <option value="">default ({knownModels[0]})</option>
          {knownModels.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      ) : (
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="default model"
          title="Optional model id; leave blank for the provider's default"
          className="w-32 rounded-md border border-ink/15 bg-white/50 px-2 py-1 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        />
      )}
    </div>
  );
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  return `${days}d ago`;
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
        {(msg.attachments ?? []).length > 0 && (
          <div className="mt-3 space-y-2">
            {(msg.attachments ?? []).map((a) => (
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
