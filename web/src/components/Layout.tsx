import { NavLink, Outlet } from "react-router-dom";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Chat", end: true },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/workflows", label: "Workflows" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  return (
    <div className="min-h-dvh bg-bone text-ink flex">
      <aside className="w-56 shrink-0 border-r border-ink/10 px-5 py-6 flex flex-col gap-6">
        <header className="flex items-center gap-3">
          <img src="/logo.png" alt="" className="w-8 h-8 object-contain" />
          <div>
            <div className="font-semibold tracking-tight">HollerBox</div>
            <div className="text-xs text-ink/50">v0.0.1 · local</div>
          </div>
        </header>

        <nav className="flex flex-col gap-1 text-sm">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                [
                  "px-3 py-2 rounded-md transition-colors",
                  isActive
                    ? "bg-terracotta/15 text-terracotta font-medium"
                    : "text-ink/70 hover:bg-ink/5 hover:text-ink",
                ].join(" ")
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <footer className="mt-auto text-[10px] uppercase tracking-widest text-ink/40">
          open source · runs on your machine
        </footer>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
