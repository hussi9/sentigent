import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ArrowRight, Zap, Building2, Shield, ChevronDown, ChevronUp } from "lucide-react";

// ── Design tokens (mirror Landing.tsx) ───────────────────────────────────────
const BG      = "#030712";
const SURFACE = "#0A0E17";
const BORDER  = "rgba(30,41,59,0.7)";
const PURPLE  = "#7c3aed";
const CYAN    = "#06b6d4";
const GREEN   = "#10b981";
const DISPLAY = "'Bricolage Grotesque', sans-serif";
const MONO    = "'JetBrains Mono', monospace";

// ── Tier data ─────────────────────────────────────────────────────────────────
const TIERS = [
  {
    id: "starter",
    name: "Starter",
    price: { monthly: 0, annual: 0 },
    tagline: "For individual developers getting started.",
    color: "#64748b",
    icon: <Zap size={18} />,
    cta: "Get started free",
    ctaHref: "/auth/signup",
    highlight: false,
    features: [
      "1 agent",
      "Layer 1 — local SQLite only",
      "30-day episode history",
      "5 MCP tools (evaluate, score, patterns, outcome, prove)",
      "Basic judgment signals",
      "sentigent prove report",
      "Community patterns (read-only)",
      "Email support",
    ],
  },
  {
    id: "team",
    name: "Team",
    price: { monthly: 49, annual: 39 },
    tagline: "For engineering teams that need org-wide intelligence.",
    color: PURPLE,
    icon: <Building2 size={18} />,
    cta: "Start free trial",
    ctaHref: "/auth/signup",
    highlight: true,
    badge: "Most popular",
    features: [
      "Up to 10 agents",
      "Layer 1 + Layer 2 (Supabase org-wide)",
      "Unlimited episode history",
      "All 24 MCP tools",
      "Org policies & enforcement",
      "Agent profiles (PM, security, devops)",
      "LLM Judge (ambiguous zone routing)",
      "AgentBus — inter-agent messaging",
      "Proof of Value report + PDF export",
      "Collective patterns (read + contribute)",
      "Webhook escalations (Slack / PagerDuty)",
      "Priority email support",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: { monthly: 199, annual: 159 },
    tagline: "For orgs that need compliance, audit, and unlimited scale.",
    color: CYAN,
    icon: <Shield size={18} />,
    cta: "Contact sales",
    ctaHref: "/auth/signup",
    highlight: false,
    features: [
      "Unlimited agents",
      "All layers (1 + 2 + 3)",
      "SOC 2 immutable audit log",
      "Custom policy bundles",
      "Human-in-the-loop approval queue",
      "RBAC — policy management permissions",
      "Policy-as-Code (GitOps integration)",
      "SSO / SAML",
      "Agent Trust Score & autonomy tiers",
      "Multi-org / multi-tenant support",
      "Pattern bundles + private registry",
      "SLA guarantee (99.9% uptime)",
      "Dedicated Slack channel support",
      "Custom onboarding & training",
    ],
  },
] as const;

// ── Feature comparison table ──────────────────────────────────────────────────
type RowValue = boolean | string;
interface CompareRow { feature: string; starter: RowValue; team: RowValue; enterprise: RowValue }

const COMPARE_SECTIONS: { heading: string; rows: CompareRow[] }[] = [
  {
    heading: "Core judgment",
    rows: [
      { feature: "evaluate() calls",        starter: "Unlimited",  team: "Unlimited",  enterprise: "Unlimited" },
      { feature: "Judgment signals",         starter: "5",          team: "5",          enterprise: "5 + custom" },
      { feature: "LLM Judge",                starter: false,        team: true,         enterprise: true },
      { feature: "Brier score tracking",     starter: true,         team: true,         enterprise: true },
      { feature: "Episode history",          starter: "30 days",    team: "Unlimited",  enterprise: "Unlimited" },
      { feature: "sentigent prove report",   starter: true,         team: true,         enterprise: true },
      { feature: "PDF export",               starter: false,        team: true,         enterprise: true },
    ],
  },
  {
    heading: "Org intelligence",
    rows: [
      { feature: "Org policies",             starter: false,        team: true,         enterprise: true },
      { feature: "Agent profiles",           starter: false,        team: true,         enterprise: true },
      { feature: "Shared org patterns",      starter: false,        team: true,         enterprise: true },
      { feature: "AgentBus",                 starter: false,        team: true,         enterprise: true },
      { feature: "Multi-agent support",      starter: "1",          team: "Up to 10",   enterprise: "Unlimited" },
      { feature: "Row-level security (RLS)", starter: false,        team: true,         enterprise: true },
    ],
  },
  {
    heading: "Human-agent collaboration",
    rows: [
      { feature: "Escalation routing",       starter: false,        team: "Webhooks",   enterprise: "Full routing" },
      { feature: "Slack integration",        starter: false,        team: true,         enterprise: true },
      { feature: "PagerDuty integration",    starter: false,        team: true,         enterprise: true },
      { feature: "Approval queue UI",        starter: false,        team: false,        enterprise: true },
      { feature: "Audit trail",              starter: "30 days",    team: "Unlimited",  enterprise: "Immutable + SOC 2" },
    ],
  },
  {
    heading: "Collective intelligence (Layer 3)",
    rows: [
      { feature: "Read community patterns",  starter: true,         team: true,         enterprise: true },
      { feature: "Contribute patterns",      starter: false,        team: true,         enterprise: true },
      { feature: "Private pattern registry", starter: false,        team: false,        enterprise: true },
      { feature: "Pattern bundles",          starter: false,        team: "Read",       enterprise: "Read + create" },
    ],
  },
  {
    heading: "Enterprise & compliance",
    rows: [
      { feature: "SSO / SAML",               starter: false,        team: false,        enterprise: true },
      { feature: "RBAC (policy management)", starter: false,        team: false,        enterprise: true },
      { feature: "SOC 2 audit mode",         starter: false,        team: false,        enterprise: true },
      { feature: "Agent Trust Score tiers",  starter: false,        team: false,        enterprise: true },
      { feature: "Policy-as-Code (GitOps)",  starter: false,        team: false,        enterprise: true },
      { feature: "Custom SLA",               starter: false,        team: false,        enterprise: true },
    ],
  },
  {
    heading: "Support",
    rows: [
      { feature: "Community forum",          starter: true,         team: true,         enterprise: true },
      { feature: "Email support",            starter: true,         team: "Priority",   enterprise: "Dedicated" },
      { feature: "Slack channel support",    starter: false,        team: false,        enterprise: true },
      { feature: "Onboarding & training",    starter: false,        team: false,        enterprise: true },
    ],
  },
];

function CellValue({ val }: { val: RowValue }) {
  if (val === true) return <Check size={15} style={{ color: GREEN, margin: "0 auto" }} />;
  if (val === false) return <span className="text-slate-700 text-lg leading-none block text-center">—</span>;
  return <span className="text-xs text-slate-300 block text-center" style={{ fontFamily: MONO }}>{val}</span>;
}

// ── FAQ ────────────────────────────────────────────────────────────────────────
const FAQ = [
  { q: "What is a Brier score?",
    a: "Brier score is a calibrated probability accuracy metric. It measures how well your confidence estimates match actual outcomes. 0.0 is perfect (every confidence of 0.9 is correct 90% of the time), 0.25 is random. Sentigent tracks your score over time so you can see judgment accuracy improving — not just 'accuracy' but properly calibrated confidence." },
  { q: "Does my data leave my machine on the Starter plan?",
    a: "No. On the Starter plan, all data stays in a local SQLite database at ~/.sentigent/memory.db. You control it completely. Layer 2 (Supabase org sync) and Layer 3 (collective patterns) are opt-in features on Team and Enterprise." },
  { q: "Which AI agents does Sentigent support?",
    a: "Currently Sentigent has deep integration with Claude Code (Cursor, terminal) via hooks and MCP. SDK support for LangChain, OpenAI Agents SDK, AutoGen, and CrewAI is on the roadmap. The evaluate() API is framework-agnostic — any agent that can make an HTTP call or use MCP can integrate." },
  { q: "What is the AgentBus?",
    a: "AgentBus is an inter-agent messaging layer that lets multiple agents coordinate without sharing a context window. Agents register capabilities (e.g., 'code_review', 'security_scan'), then delegate tasks to the most qualified agent. Uncertainty signals propagate across the bus before errors can cascade." },
  { q: "How does collective intelligence (Layer 3) work?",
    a: "If you opt in, Sentigent anonymizes and contributes your learned patterns to a shared pool. No org identifiers, no agent names, no task content — only the pattern structure and statistical outcomes. You also pull patterns from the pool, which boosts your day-1 accuracy significantly." },
  { q: "Can I cancel anytime?",
    a: "Yes. Monthly plans cancel at the end of the billing period. Annual plans can be cancelled with a prorated refund in the first 30 days. Your local data and episode history always remain accessible — it's your data." },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b py-5 cursor-pointer" style={{ borderColor: BORDER }} onClick={() => setOpen(o => !o)}>
      <div className="flex items-start justify-between gap-4">
        <span className="font-semibold text-white text-sm">{q}</span>
        {open
          ? <ChevronUp size={16} className="flex-shrink-0 mt-0.5" style={{ color: PURPLE }} />
          : <ChevronDown size={16} className="flex-shrink-0 mt-0.5 text-slate-500" />}
      </div>
      {open && <p className="mt-3 text-sm text-slate-400 leading-relaxed">{a}</p>}
    </div>
  );
}

// ── Nav (minimal) ─────────────────────────────────────────────────────────────
function PricingNav() {
  return (
    <nav className="sticky top-0 z-50 border-b" style={{ background: "rgba(3,7,18,0.92)", backdropFilter: "blur(16px)", borderColor: BORDER }}>
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${PURPLE}, ${CYAN})` }}>
            <span className="text-white text-[11px] font-black">S</span>
          </div>
          <span className="font-bold text-white text-[15px]" style={{ fontFamily: DISPLAY }}>Sentigent</span>
        </Link>
        <div className="hidden md:flex items-center gap-6 text-sm text-slate-400">
          <Link to="/" className="hover:text-white transition-colors">Home</Link>
          <Link to="/help" className="hover:text-white transition-colors">Docs</Link>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/auth/login" className="text-sm text-slate-400 hover:text-white transition-colors px-3 py-1.5">Sign in</Link>
          <Link to="/auth/signup"
            className="px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all hover:opacity-90"
            style={{ background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)` }}>
            Get started
          </Link>
        </div>
      </div>
    </nav>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function Pricing() {
  const [annual, setAnnual] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <div className="min-h-screen text-white" style={{ background: BG, fontFamily: "'Inter', sans-serif" }}>
      <PricingNav />

      {/* Hero */}
      <section className="pt-24 pb-16 text-center relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[400px] blur-[120px] opacity-[0.12]"
            style={{ background: `radial-gradient(ellipse, ${PURPLE}, transparent)` }} />
        </div>
        <div className="relative max-w-3xl mx-auto px-6">
          <h1 className="text-5xl font-extrabold text-white mb-4" style={{ fontFamily: DISPLAY }}>
            Simple, transparent pricing
          </h1>
          <p className="text-lg text-slate-400 mb-10">
            Start free, no card required. Upgrade when your team needs org-wide intelligence.
          </p>
          {/* Toggle */}
          <div className="inline-flex items-center gap-3 p-1 rounded-full" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <button onClick={() => setAnnual(false)}
              className="px-5 py-2 rounded-full text-sm font-medium transition-all"
              style={{ background: !annual ? PURPLE : "transparent", color: !annual ? "white" : "#94a3b8" }}>
              Monthly
            </button>
            <button onClick={() => setAnnual(true)}
              className="px-5 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2"
              style={{ background: annual ? PURPLE : "transparent", color: annual ? "white" : "#94a3b8" }}>
              Annual
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${GREEN}20`, color: GREEN }}>–20%</span>
            </button>
          </div>
        </div>
      </section>

      {/* Tier cards */}
      <section className="pb-24 max-w-7xl mx-auto px-6">
        <div className="grid md:grid-cols-3 gap-6">
          {TIERS.map(tier => {
            const price = annual ? tier.price.annual : tier.price.monthly;
            return (
              <div key={tier.id} className="relative rounded-2xl p-8 flex flex-col"
                style={{
                  background: tier.highlight ? `linear-gradient(180deg, ${PURPLE}12, ${SURFACE})` : SURFACE,
                  border: `1px solid ${tier.highlight ? PURPLE + "50" : BORDER}`,
                  boxShadow: tier.highlight ? `0 0 60px ${PURPLE}20` : "none",
                }}>
                {tier.highlight && tier.badge && (
                  <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full text-xs font-bold text-white"
                    style={{ background: `linear-gradient(90deg, ${PURPLE}, #6d28d9)` }}>
                    {tier.badge}
                  </div>
                )}

                {/* Header */}
                <div className="mb-6">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                    style={{ background: `${tier.color}18`, color: tier.color }}>
                    {tier.icon}
                  </div>
                  <div className="font-bold text-xl text-white mb-1" style={{ fontFamily: DISPLAY }}>{tier.name}</div>
                  <div className="text-xs text-slate-500 leading-snug">{tier.tagline}</div>
                </div>

                {/* Price */}
                <div className="mb-6">
                  <div className="flex items-end gap-1.5">
                    <span className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
                      {price === 0 ? "Free" : `$${price}`}
                    </span>
                    {price > 0 && <span className="text-slate-500 text-sm mb-1.5">/mo{annual ? " (billed annually)" : ""}</span>}
                  </div>
                  {annual && price > 0 && (
                    <div className="text-xs mt-1" style={{ color: GREEN }}>
                      Save ${(tier.price.monthly - tier.price.annual) * 12}/year
                    </div>
                  )}
                </div>

                {/* CTA */}
                <Link to={tier.ctaHref}
                  className="flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm mb-8 transition-all hover:opacity-90"
                  style={tier.highlight
                    ? { background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`, color: "white", boxShadow: `0 0 24px ${PURPLE}40` }
                    : { background: `${tier.color}15`, color: tier.color, border: `1px solid ${tier.color}25` }}>
                  {tier.cta} {tier.highlight && <ArrowRight size={15} />}
                </Link>

                {/* Features */}
                <ul className="space-y-3 flex-1">
                  {tier.features.map(f => (
                    <li key={f} className="flex items-start gap-2.5">
                      <Check size={13} className="mt-0.5 flex-shrink-0" style={{ color: tier.color }} />
                      <span className="text-xs text-slate-400 leading-relaxed">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>

        {/* Trust note */}
        <div className="mt-8 text-center">
          <p className="text-xs text-slate-600">
            No credit card required to start · Cancel anytime · Local data always yours · SOC 2 on Enterprise
          </p>
        </div>
      </section>

      {/* Full comparison table */}
      <section className="pb-24 max-w-7xl mx-auto px-6">
        <button onClick={() => setCompareOpen(o => !o)}
          className="flex items-center gap-2 mx-auto mb-8 text-sm text-slate-400 hover:text-white transition-colors">
          {compareOpen ? <><ChevronUp size={16} /> Hide full comparison</> : <><ChevronDown size={16} /> Show full feature comparison</>}
        </button>

        {compareOpen && (
          <div className="rounded-2xl overflow-hidden border" style={{ border: `1px solid ${BORDER}` }}>
            {/* Header row */}
            <div className="grid grid-cols-4 border-b" style={{ background: SURFACE, borderColor: BORDER }}>
              <div className="p-5 text-xs text-slate-500 uppercase tracking-wider">Feature</div>
              {TIERS.map(t => (
                <div key={t.id} className="p-5 text-center">
                  <div className="font-bold text-sm text-white mb-0.5" style={{ fontFamily: DISPLAY, color: t.color }}>{t.name}</div>
                </div>
              ))}
            </div>

            {COMPARE_SECTIONS.map(section => (
              <div key={section.heading}>
                <div className="px-5 py-3 border-b" style={{ background: "#070B12", borderColor: BORDER }}>
                  <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500" style={{ fontFamily: MONO }}>{section.heading}</span>
                </div>
                {section.rows.map((row, i) => (
                  <div key={row.feature} className="grid grid-cols-4 border-b last:border-0"
                    style={{ borderColor: BORDER, background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)" }}>
                    <div className="px-5 py-3.5 text-xs text-slate-400">{row.feature}</div>
                    <div className="px-5 py-3.5 flex items-center justify-center"><CellValue val={row.starter} /></div>
                    <div className="px-5 py-3.5 flex items-center justify-center" style={{ background: `${PURPLE}06` }}><CellValue val={row.team} /></div>
                    <div className="px-5 py-3.5 flex items-center justify-center"><CellValue val={row.enterprise} /></div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* FAQ */}
      <section className="pb-24 max-w-3xl mx-auto px-6">
        <h2 className="text-3xl font-extrabold text-white text-center mb-12" style={{ fontFamily: DISPLAY }}>
          Frequently asked questions
        </h2>
        <div>
          {FAQ.map(item => <FAQItem key={item.q} q={item.q} a={item.a} />)}
        </div>
      </section>

      {/* CTA */}
      <section className="pb-32 text-center">
        <div className="max-w-2xl mx-auto px-6">
          <h2 className="text-4xl font-extrabold text-white mb-4" style={{ fontFamily: DISPLAY }}>
            Start free. Prove value in 90 days.
          </h2>
          <p className="text-slate-400 mb-8">No card required. Install in 60 seconds. See your Brier score on day 1.</p>
          <Link to="/auth/signup"
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-bold text-white text-[15px] transition-all hover:scale-105"
            style={{ background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`, boxShadow: `0 0 40px ${PURPLE}40` }}>
            Get started free <ArrowRight size={18} />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-8 text-center text-xs text-slate-700" style={{ borderColor: BORDER }}>
        <div className="flex items-center justify-center gap-2 mb-2">
          <div className="w-5 h-5 rounded-md flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${PURPLE}, ${CYAN})` }}>
            <span className="text-white text-[9px] font-black">S</span>
          </div>
          <span style={{ fontFamily: DISPLAY, color: "#94a3b8" }}>Sentigent</span>
        </div>
        <span style={{ fontFamily: MONO }}>© 2025 Sentigent · brier_score: 0.087 · proven ✓</span>
      </footer>
    </div>
  );
}
