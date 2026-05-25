import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

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
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  // Auto-close the drawer on route change so a nav tap doesn't leave it open.
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-dvh bg-bone text-ink md:flex">
      {/* Mobile top bar */}
      <header className="md:hidden sticky top-0 z-30 flex items-center gap-3 border-b border-ink/10 bg-bone/95 backdrop-blur px-4 py-3">
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          className="rounded-md border border-ink/15 p-1.5 active:bg-ink/5"
        >
          <Hamburger />
        </button>
        <img src="/logo.png" alt="" className="w-6 h-6 object-contain" />
        <div className="font-semibold tracking-tight">HollerBox</div>
      </header>

      {/* Backdrop for mobile drawer */}
      {mobileOpen && (
        <button
          aria-label="Close menu"
          onClick={() => setMobileOpen(false)}
          className="md:hidden fixed inset-0 z-40 bg-black/30"
        />
      )}

      {/* Sidebar — drawer on mobile, static on md+ */}
      <aside
        className={[
          "fixed md:static inset-y-0 left-0 z-50 w-64 md:w-56 shrink-0",
          "border-r border-ink/10 bg-bone px-5 py-6 flex flex-col gap-6",
          "transition-transform md:transition-none",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        ].join(" ")}
      >
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

      <main className="flex-1 overflow-x-hidden min-w-0">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 md:px-8 py-4 md:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Hamburger() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
    </svg>
  );
}
