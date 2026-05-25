export default function App() {
  return (
    <main className="min-h-dvh bg-bone text-ink flex flex-col items-center justify-center gap-6 px-6 text-center">
      <img
        src="/logo.png"
        alt="HollerBox"
        className="w-24 h-24 object-contain"
      />
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">HollerBox</h1>
        <p className="text-ink/70 max-w-md">
          Local-first, chat-driven AI workflow engine. Phase 0 shell — talk to it
          once the chat brain is wired in Phase 5.
        </p>
      </div>
      <p className="text-xs uppercase tracking-widest text-terracotta">
        v0.0.1 · open source · runs on your machine
      </p>
    </main>
  );
}
