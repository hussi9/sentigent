import { useState, useRef, useEffect } from "react";
import { RefreshCw, Settings, Download, Bell, LogOut, ChevronDown } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { NavPage } from "@/types";
import { useAuth } from "@/context/AuthContext";

const PAGE_TITLES: Record<NavPage, { title: string; subtitle: string }> = {
  onboarding: { title: "Getting Started", subtitle: "Setup guide for admins and developers" },
  dashboard: { title: "Org Dashboard", subtitle: "Judgment health across all agents" },
  agents: { title: "Agent Explorer", subtitle: "Per-agent scores, patterns, and decisions" },
  policies: { title: "Policy Manager", subtitle: "Org-wide enforcement rules and violations" },
  practices: { title: "Practices", subtitle: "Declared development practices and enforcement" },
  escalations: { title: "Escalations", subtitle: "Autonomous loops waiting on a human decision" },
  routing: { title: "Routing", subtitle: "Skill-router seeds and closed-loop reconciliation" },
  "prompt-builder": { title: "Prompt Builder", subtitle: "Template-guided prompt construction" },
  collective: { title: "Collective Intelligence", subtitle: "Cross-org anonymized pattern pool" },
  proof: { title: "Proof of Value", subtitle: "Brier scores, catches, and impact metrics" },
  "intelligence": { title: "Intelligence Hub", subtitle: "Central AI layer — connects agents, reads signals, learns collectively" },
  "my-agent": { title: "My Agent", subtitle: "Your agent's decisions and self-learning progress" },
  "admin/layer1": { title: "Admin — All Agents", subtitle: "Cross-agent judgment health for your org" },
  "settings/org": { title: "Org Settings", subtitle: "Name, API key, and plan management" },
  "settings/members": { title: "Members", subtitle: "Invite teammates and manage roles" },
  "help": { title: "Documentation", subtitle: "Technical reference — architecture, API, MCP tools, configuration" },
  "org-knowledge": { title: "Org Knowledge", subtitle: "Your organization's world model — vocabulary, practices, entities" },
};

interface Props {
  page: NavPage;
  orgId: string;
  onRefresh: () => void;
  isRefreshing?: boolean;
  onExport?: () => void;
  liveCount?: number;
}

export function Header({ page, onRefresh, isRefreshing, onExport, liveCount }: Props) {
  const { title, subtitle } = PAGE_TITLES[page];
  const { user, membership, signOut } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    function onOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [menuOpen]);

  // User initials for avatar
  const initials = user?.email
    ? user.email.slice(0, 2).toUpperCase()
    : "?";

  const orgLabel = membership?.org_name || membership?.org_slug || "—";

  return (
    <header
      className="h-14 shrink-0 flex items-center gap-4 px-5 border-b border-bg-border relative"
      style={{ background: "rgba(7, 9, 15, 0.95)", backdropFilter: "blur(12px)" }}
    >
      {/* Gradient line at bottom */}
      <div
        className="absolute bottom-0 left-0 right-0 h-px"
        style={{ background: "linear-gradient(90deg, transparent, rgba(124,58,237,0.3), transparent)" }}
      />

      {/* Title */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-semibold text-white">{title}</h1>
          <span className="text-[10px] text-muted hidden sm:block">{subtitle}</span>
        </div>
      </div>

      {/* Org badge */}
      <div
        className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs"
        style={{ background: "rgba(124,58,237,0.06)", borderColor: "rgba(124,58,237,0.2)" }}
      >
        <span className="font-mono font-semibold text-accent-light/90 text-[11px]">{orgLabel}</span>
        {membership?.plan && membership.plan !== "free" && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-accent/20 text-accent-light uppercase tracking-wider">
            {membership.plan}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1">
        {/* Live counter */}
        {(liveCount ?? 0) > 0 && (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-success-dim border border-success/20 mr-1">
            <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
            <span className="text-xs font-semibold text-success tabular">{liveCount}</span>
          </div>
        )}

        {onExport && (
          <button onClick={onExport} title="Export CSV" className="btn btn-ghost p-2 rounded-lg">
            <Download size={14} />
          </button>
        )}

        <button
          onClick={onRefresh}
          title="Refresh data"
          className={`btn btn-ghost p-2 rounded-lg ${isRefreshing ? "text-accent-light" : ""}`}
        >
          <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
        </button>

        <button title="Notifications" className="btn btn-ghost p-2 rounded-lg relative">
          <Bell size={14} />
        </button>

        <button
          title="Settings"
          className="btn btn-ghost p-2 rounded-lg"
          onClick={() => navigate("/settings/org")}
        >
          <Settings size={14} />
        </button>

        <div className="w-px h-5 bg-bg-border mx-1" />

        {/* Avatar + dropdown */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen(v => !v)}
            className="flex items-center gap-1.5 rounded-lg px-1 py-0.5 hover:bg-bg-hover transition-colors"
          >
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
              style={{
                background: "linear-gradient(135deg, #7c3aed, #a855f7)",
                boxShadow: "0 0 10px rgba(124, 58, 237, 0.4)",
              }}
            >
              {initials}
            </div>
            <ChevronDown size={10} className="text-muted/60" />
          </button>

          {menuOpen && (
            <div
              className="absolute right-0 top-full mt-2 w-48 rounded-xl border border-bg-border overflow-hidden z-50"
              style={{ background: "#0d1321", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
            >
              <div className="px-3 py-2.5 border-b border-bg-border/60">
                <p className="text-[11px] font-semibold text-white truncate">{user?.email}</p>
                <p className="text-[10px] text-muted/60 capitalize">{membership?.role ?? "member"}</p>
              </div>
              <button
                onClick={async () => { setMenuOpen(false); await signOut(); navigate("/auth/login"); }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-muted/80 hover:text-danger hover:bg-danger/10 transition-colors"
              >
                <LogOut size={13} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
