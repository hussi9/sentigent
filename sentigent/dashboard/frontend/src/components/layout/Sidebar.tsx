import { Link } from "react-router-dom";
import {
  LayoutDashboard,
  Bot,
  ShieldCheck,
  Sparkles,
  Globe,
  TrendingUp,
  Activity,
  BookOpen,
  Zap,
  Settings,
  Users,
  Shield,
  Brain,
  HelpCircle,
  Library,
} from "lucide-react";
import type { NavPage } from "@/types";

interface NavItem {
  id: NavPage;
  label: string;
  icon: React.ReactNode;
  badge?: string;
  section?: string;
}

const NAV_SECTIONS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "",
    items: [
      { id: "onboarding", label: "Getting Started", icon: <BookOpen size={15} /> },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { id: "intelligence", label: "Hub", icon: <Brain size={15} /> },
    ],
  },
  {
    label: "Monitoring",
    items: [
      { id: "dashboard", label: "Org Dashboard", icon: <LayoutDashboard size={15} /> },
      { id: "agents", label: "Agent Explorer", icon: <Bot size={15} /> },
      { id: "proof", label: "Proof of Value", icon: <TrendingUp size={15} /> },
    ],
  },
  {
    label: "My Layer 1",
    items: [
      { id: "my-agent", label: "My Agent", icon: <Bot size={15} /> },
      { id: "admin/layer1", label: "All Agents", icon: <Shield size={15} /> },
    ],
  },
  {
    label: "Governance",
    items: [
      { id: "policies", label: "Policy Manager", icon: <ShieldCheck size={15} /> },
      { id: "org-knowledge", label: "Org Knowledge", icon: <Library size={15} /> },
      { id: "collective", label: "Collective Intel", icon: <Globe size={15} /> },
    ],
  },
  {
    label: "Tools",
    items: [
      { id: "prompt-builder", label: "Prompt Builder", icon: <Sparkles size={15} /> },
    ],
  },
  {
    label: "Org",
    items: [
      { id: "settings/org", label: "Org Settings", icon: <Settings size={15} /> },
      { id: "settings/members", label: "Members", icon: <Users size={15} /> },
    ],
  },
  {
    label: "",
    items: [
      { id: "help", label: "Documentation", icon: <HelpCircle size={15} /> },
    ],
  },
];

interface Props {
  current: NavPage;
  liveCount: number;
}

export function Sidebar({ current, liveCount }: Props) {
  return (
    <aside className="w-[220px] shrink-0 flex flex-col border-r border-bg-border relative overflow-hidden"
      style={{ background: "linear-gradient(180deg, #0a0f1a 0%, #07090f 100%)" }}>

      {/* Ambient glow top-left */}
      <div className="absolute top-0 left-0 w-32 h-32 rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(124,58,237,0.08) 0%, transparent 70%)" }} />

      {/* Brand */}
      <div className="px-4 pt-5 pb-4 border-b border-bg-border/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-accent flex items-center justify-center shadow-glow-sm flex-shrink-0">
            <Activity size={15} className="text-white" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-bold text-white tracking-tight">Sentigent</div>
            <div className="text-[10px] text-muted/80 flex items-center gap-1">
              <Zap size={8} className="text-accent-light" />
              AI Judgment Layer
            </div>
          </div>
        </div>
      </div>

      {/* Live indicator */}
      {liveCount > 0 && (
        <div className="mx-3 mt-3 px-3 py-2 rounded-lg bg-success-dim border border-success/20 flex items-center gap-2 animate-ticker">
          <div className="relative flex-shrink-0">
            <span className="w-2 h-2 rounded-full bg-success block" />
            <span className="w-2 h-2 rounded-full bg-success block absolute inset-0 animate-ping opacity-60" />
          </div>
          <span className="text-xs text-success font-semibold tabular">{liveCount} live</span>
          <span className="text-[10px] text-success/60 ml-auto">decisions</span>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-4 overflow-y-auto">
        {NAV_SECTIONS.map((section, si) => (
          <div key={si}>
            {section.label && (
              <div className="px-3 mb-1">
                <span className="text-[10px] font-semibold text-muted/50 uppercase tracking-widest">
                  {section.label}
                </span>
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const active = current === item.id;
                return (
                  <Link
                    key={item.id}
                    to={`/${item.id}`}
                    className={`
                      flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm
                      transition-all duration-150 group relative overflow-hidden
                      ${active ? "text-white" : "text-muted hover:text-white/90"}
                    `}
                    style={active ? {
                      background: "linear-gradient(90deg, rgba(124,58,237,0.18), rgba(124,58,237,0.06))",
                      borderLeft: "2px solid #7c3aed",
                      paddingLeft: "calc(0.75rem - 2px)",
                    } : {}}
                  >
                    {!active && (
                      <span className="absolute inset-0 rounded-lg bg-bg-hover opacity-0 group-hover:opacity-100 transition-opacity duration-150" />
                    )}
                    <span className={`relative z-10 transition-colors duration-150 ${active ? "text-accent-light" : "text-muted/70 group-hover:text-muted"}`}>
                      {item.icon}
                    </span>
                    <span className="relative z-10 flex-1 font-medium text-sm">{item.label}</span>
                    {active && (
                      <span className="relative z-10 w-1.5 h-1.5 rounded-full bg-accent-light flex-shrink-0" />
                    )}
                    {item.badge && (
                      <span className="relative z-10 text-[10px] bg-accent/20 text-accent-light px-1.5 py-0.5 rounded-full font-medium">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-bg-border/60">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse-slow" />
          <div className="text-[10px] text-muted/50">
            <span className="text-muted font-medium">v1.0</span> · 3-layer architecture
          </div>
        </div>
      </div>
    </aside>
  );
}
