"use client";

import React, { useEffect } from "react";
import {
  LayoutDashboard,
  BarChart3,
  Database,
  Waypoints,
  ShieldCheck,
  Search,
  Bell,
  ArrowUpFromLine,
  LogOut,
} from "lucide-react";
import { useClientId } from "./ClientContext";
import type { HealthData } from "./SystemHealthStrip";

// AppShell -- the sidebar + topbar chrome for the one-page Eivanta
// Console layout, ported from the approved static design mockup
// (eivanta_console.html). This replaces the old page.tsx pattern of
// stacking every widget vertically down one long scrolling page (the
// direct cause of the "it auto-scrolls back to the middle" complaint --
// a 5000px-tall page made any programmatic scroll, even one scoped
// correctly to a single panel, feel like it was fighting the user).
// Every widget INSIDE each section below is unchanged, real, and
// already wired to real backend data -- only the navigation chrome
// around them is new.
export type ViewId = "overview" | "analytics" | "ledger" | "swarm" | "trust";

const VIEW_META: Record<ViewId, { label: string; title: string; subtitle: string; icon: React.ElementType }> = {
  overview: {
    label: "Overview",
    title: "Overview",
    subtitle: "Real-time snapshot across your ledger and swarm.",
    icon: LayoutDashboard,
  },
  analytics: {
    label: "Analytics",
    title: "Analytics",
    subtitle: "Statistical, BI, and forecasting agents grounded in this tenant's ledger.",
    icon: BarChart3,
  },
  ledger: {
    label: "Ledger & Data",
    title: "Ledger & Data",
    subtitle: "Ingestion, row-level evidence, and category cleanup.",
    icon: Database,
  },
  swarm: {
    label: "Swarm",
    title: "Swarm",
    subtitle: "Live telemetry and the sub-agent roster behind every query.",
    icon: Waypoints,
  },
  trust: {
    label: "Trust & Gaps",
    title: "Trust & Gaps",
    subtitle: "What Eivanta knows for certain, and what it doesn't yet.",
    icon: ShieldCheck,
  },
};

const VIEW_ORDER: ViewId[] = ["overview", "analytics", "ledger", "swarm", "trust"];

interface AppShellProps {
  activeView: ViewId;
  onChangeView: (view: ViewId) => void;
  onOpenCommandPalette: () => void;
  // Health is fetched once in page.tsx (same real GET /api/v1/health call
  // the old page.tsx made) and passed down here, so the topbar pill and
  // the Overview tab's System State / Runtime Security tiles always agree
  // -- rather than each independently polling and briefly disagreeing.
  health: HealthData | null;
  healthChecked: boolean;
  children: React.ReactNode;
}

export default function AppShell({ activeView, onChangeView, onOpenCommandPalette, health, healthChecked, children }: AppShellProps) {
  const clientCtx = useClientId();
  const clientId: string = clientCtx.clientId || "CLI-001";
  const authReady: boolean = clientCtx.authReady;
  const authToken: string | null = clientCtx.authToken;
  const user = clientCtx.user;
  const logout = clientCtx.logout;

  // RBAC-01: the "Upload Ledger" shortcut in the topbar hits the same
  // upload endpoint the Ledger view's own uploader does, and that endpoint
  // now requires owner/admin/member -- a viewer clicking this would just
  // get a 403 from the backend, so hide it for viewers rather than let
  // them find that out the hard way. The Ledger view itself is still
  // reachable via the sidebar for viewers (read-only content there).
  const canUpload = user?.role !== "viewer";

  const meta = VIEW_META[activeView];
  const accentAttr = activeView === "overview" ? undefined : activeView;

  useEffect(() => {
    if (accentAttr) {
      document.body.setAttribute("data-nf-accent", accentAttr);
    } else {
      document.body.removeAttribute("data-nf-accent");
    }
  }, [accentAttr]);

  const isOnline = healthChecked && health !== null;
  const initials = (user?.email || clientId).replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "NF";

  return (
    <div className="nf-shell">
      <div className="nf-ambient" />
      <div className="nf-dot-grain" />

      <aside className="nf-sidebar">
        <div className="nf-brand">
          <svg width="30" height="30" viewBox="0 0 32 32" fill="none">
            <path d="M4 22 L14 8 L20 16 L28 6" stroke="url(#nfg1)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="28" cy="6" r="3" fill="#2fd199" />
            <circle cx="4" cy="22" r="3" fill="#5b6ef0" />
            <defs>
              <linearGradient id="nfg1" x1="4" y1="22" x2="28" y2="6" gradientUnits="userSpaceOnUse">
                <stop stopColor="#5b6ef0" /><stop offset="1" stopColor="#2fd199" />
              </linearGradient>
            </defs>
          </svg>
          <div className="nf-brand-word">Eivanta<small>ANALYTICS CONSOLE</small></div>
        </div>

        <nav className="nf-nav-group">
          <div className="nf-nav-eyebrow">Workspace</div>
          {VIEW_ORDER.map((id) => {
            const item = VIEW_META[id];
            const Icon = item.icon;
            return (
              <button
                key={id}
                className="nf-nav-item"
                onClick={() => onChangeView(id)}
                aria-current={activeView === id ? "page" : undefined}
              >
                <Icon />
                <span className="nf-nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="nf-sidebar-spacer" />

        <div className="nf-sidebar-foot">
          <span className="nf-tenant-dot" style={{ background: authReady && authToken ? undefined : "#545d82" }} />
          <div className="nf-sidebar-foot-text">
            <div className="t1" title={user?.email}>{user?.email ?? clientId}</div>
            <div className="t2">
              {user ? `${user.role.charAt(0).toUpperCase()}${user.role.slice(1)} · ${clientId}` : authReady ? "Auth unavailable" : "Authenticating..."}
            </div>
          </div>
          {user && (
            <button
              className="nf-icon-btn"
              title="Sign out"
              aria-label="Sign out"
              onClick={logout}
            >
              <LogOut />
            </button>
          )}
        </div>
      </aside>

      <div className="nf-main">
        <header className="nf-topbar">
          <div className="nf-topbar-title">
            <h1>{meta.title}</h1>
            <p>{meta.subtitle}</p>
          </div>
          <div className="nf-topbar-actions">
            <span className={`nf-status-pill${isOnline ? "" : " nf-offline"}`}>
              <span className="nf-dot" />
              {!healthChecked ? "Checking..." : isOnline ? "Supervisor Online" : "Supervisor Offline"}
            </span>
            <button className="nf-icon-btn" title="Quick search (⌘K)" aria-label="Quick search" onClick={onOpenCommandPalette}>
              <Search />
            </button>
            <button className="nf-icon-btn" title="System status" aria-label="System status">
              {!isOnline && healthChecked && <span className="nf-ping" />}
              <Bell />
            </button>
            {canUpload && (
              <button className="nf-btn-primary" onClick={() => onChangeView("ledger")}>
                <ArrowUpFromLine />
                Upload Ledger
              </button>
            )}
            <div className="nf-avatar-badge" title={user?.email}>{initials}</div>
          </div>
        </header>

        <main className="nf-content">{children}</main>
      </div>
    </div>
  );
}
