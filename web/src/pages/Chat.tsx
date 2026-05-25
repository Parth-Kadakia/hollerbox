export default function ChatPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <p className="text-sm text-ink/60 mt-1">
          Conversational interface — the chat brain ships in Phase 5.
        </p>
      </header>
      <div className="rounded-lg border border-dashed border-ink/15 px-6 py-12 text-center">
        <p className="text-sm text-ink/60">
          Once Phase 5 lands, you'll text the engine here. It'll pick the right
          workflow, run it, and ask "reply YES to confirm" before anything
          destructive.
        </p>
      </div>
    </div>
  );
}
