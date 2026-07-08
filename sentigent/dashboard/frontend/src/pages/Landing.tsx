import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, ChevronRight, Check, Shield, Brain, Activity,
  GitFork, Lock, Terminal, Zap, TrendingUp, Users, Database,
  MessageSquare, AlertTriangle,
} from "lucide-react";

// ── Design tokens ────────────────────────────────────────────────────────────
const BG       = "#030712";
const SURFACE  = "#0A0E17";
const BORDER   = "rgba(30,41,59,0.7)";
const PURPLE   = "#7c3aed";
const CYAN     = "#06b6d4";
const GREEN    = "#10b981";
const AMBER    = "#f59e0b";
const RED      = "#ef4444";
const VIOLET   = "#a78bfa";
const DISPLAY  = "'Bricolage Grotesque', sans-serif";
const MONO     = "'JetBrains Mono', monospace";

// ── Terminal animation data ───────────────────────────────────────────────────
type LineType = "cmd" | "blank" | "border" | "header" | "score" | "metric" | "label" | "catch" | "verdict";
const TERMINAL_LINES: { text: string; type: LineType; delay?: number }[] = [
  { text: "$ sentigent prove --days 90", type: "cmd",     delay: 600 },
  { text: "",                            type: "blank",   delay: 80  },
  { text: "═══════════════════════════════════════════════", type: "border",  delay: 60 },
  { text: " Sentigent  ⬡  Proof of Value — Last 90 Days",  type: "header",  delay: 100 },
  { text: "═══════════════════════════════════════════════", type: "border",  delay: 60 },
  { text: "",                            type: "blank",   delay: 60  },
  { text: " Judgment Score:      0.94  ↑ +38%",            type: "score",   delay: 130 },
  { text: " Brier Score:        0.087  (0.0 = perfect)",   type: "metric",  delay: 130 },
  { text: " Decisions evaluated:  847",                    type: "metric",  delay: 130 },
  { text: " Correct calls:        796  (94.0%)",           type: "metric",  delay: 130 },
  { text: "",                            type: "blank",   delay: 60  },
  { text: " Top catches confirmed by outcome:",            type: "label",   delay: 110 },
  { text: "  1. force_push_block    12×  100% acc  P=0.96", type: "catch",  delay: 140 },
  { text: "  2. deploy_escalation    8×   88% acc  P=0.88", type: "catch",  delay: 140 },
  { text: "  3. env_write_slow       5×  100% acc  P=0.98", type: "catch",  delay: 140 },
  { text: "",                            type: "blank",   delay: 60  },
  { text: " False negative rate:   3.2%",                  type: "metric",  delay: 130 },
  { text: " vs. random baseline:  +38% improvement",       type: "metric",  delay: 130 },
  { text: "",                            type: "blank",   delay: 60  },
  { text: "═══════════════════════════════════════════════", type: "border",  delay: 60 },
  { text: " Verdict: PROVEN  ✓",                           type: "verdict", delay: 300 },
  { text: "═══════════════════════════════════════════════", type: "border",  delay: 60 },
];

const LINE_COLORS: Record<LineType, string> = {
  cmd:     "#34d399",
  blank:   "transparent",
  border:  "#334155",
  header:  "#c4b5fd",
  score:   "#34d399",
  metric:  "#94a3b8",
  label:   "#64748b",
  catch:   "#22d3ee",
  verdict: "#34d399",
};

// ── Utility: IntersectionObserver hook ───────────────────────────────────────
function useVisible(threshold = 0.25) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setVisible(true); io.disconnect(); } }, { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return { ref, visible };
}

// ── Animated counter ─────────────────────────────────────────────────────────
function Counter({ from, to, decimals = 0, suffix = "" }: { from: number; to: number; decimals?: number; suffix?: string }) {
  const [val, setVal] = useState(from);
  const { ref, visible } = useVisible(0.5);
  useEffect(() => {
    if (!visible) return;
    const steps = 60, dur = 1800;
    let step = 0;
    const id = setInterval(() => {
      step++;
      setVal(from + ((to - from) * step) / steps);
      if (step >= steps) { setVal(to); clearInterval(id); }
    }, dur / steps);
    return () => clearInterval(id);
  }, [visible, from, to]);
  return <span ref={ref}>{val.toFixed(decimals)}{suffix}</span>;
}

// ── Terminal window ───────────────────────────────────────────────────────────
function TerminalWindow() {
  const [shown, setShown] = useState(0);
  const { ref, visible } = useVisible(0.2);
  useEffect(() => {
    if (!visible || shown >= TERMINAL_LINES.length) return;
    const t = setTimeout(() => setShown(n => n + 1), TERMINAL_LINES[shown].delay ?? 120);
    return () => clearTimeout(t);
  }, [visible, shown]);

  return (
    <div ref={ref} className="rounded-2xl overflow-hidden shadow-2xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      {/* Chrome */}
      <div className="flex items-center gap-1.5 px-4 py-3 border-b" style={{ background: "#0D1117", borderColor: BORDER }}>
        <div className="w-3 h-3 rounded-full" style={{ background: "#ff5f57" }} />
        <div className="w-3 h-3 rounded-full" style={{ background: "#febc2e" }} />
        <div className="w-3 h-3 rounded-full" style={{ background: "#28c840" }} />
        <span className="ml-3 text-xs text-slate-500" style={{ fontFamily: MONO }}>sentigent — bash</span>
      </div>
      {/* Body */}
      <div className="p-5 text-sm leading-6 min-h-[380px]" style={{ fontFamily: MONO }}>
        {TERMINAL_LINES.slice(0, shown).map((line, i) => (
          <div key={i} style={{ color: LINE_COLORS[line.type], fontWeight: line.type === "score" || line.type === "verdict" ? 700 : 400 }}>
            {line.text || "\u00a0"}
          </div>
        ))}
        {shown < TERMINAL_LINES.length && visible && (
          <span className="inline-block w-2 h-[1.1em] align-middle animate-pulse" style={{ background: "#34d399" }} />
        )}
      </div>
    </div>
  );
}

// ── Nav ───────────────────────────────────────────────────────────────────────
function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const h = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", h, { passive: true });
    return () => window.removeEventListener("scroll", h);
  }, []);

  return (
    <nav className="fixed top-0 inset-x-0 z-50 transition-all duration-300"
      style={{ background: scrolled ? "rgba(3,7,18,0.88)" : "transparent", backdropFilter: scrolled ? "blur(16px)" : "none", borderBottom: scrolled ? `1px solid ${BORDER}` : "1px solid transparent" }}>
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110"
            style={{ background: `linear-gradient(135deg, ${PURPLE}, ${CYAN})` }}>
            <span className="text-white text-[11px] font-black">S</span>
          </div>
          <span className="font-bold text-white text-[15px]" style={{ fontFamily: DISPLAY }}>Sentigent</span>
        </Link>

        {/* Links */}
        <div className="hidden md:flex items-center gap-7 text-sm text-slate-400">
          <a href="#how" className="hover:text-white transition-colors">How it works</a>
          <a href="#signals" className="hover:text-white transition-colors">Signals</a>
          <a href="#proof" className="hover:text-white transition-colors">Proof</a>
          <a href="#architecture" className="hover:text-white transition-colors">Architecture</a>
          <Link to="/pricing" className="hover:text-white transition-colors">Pricing</Link>
          <Link to="/help" className="hover:text-white transition-colors">Docs</Link>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <Link to="/auth/login" className="hidden sm:block text-sm text-slate-400 hover:text-white transition-colors px-3 py-1.5">Sign in</Link>
          <Link to="/auth/signup"
            className="px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all hover:opacity-90 hover:scale-105"
            style={{ background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`, boxShadow: `0 0 20px ${PURPLE}40` }}>
            Get started
          </Link>
        </div>
      </div>
    </nav>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────
function HeroSection() {
  return (
    <section className="relative min-h-screen flex items-center pt-16 overflow-hidden">
      {/* Atmospheric gradients */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute top-1/3 left-1/5 w-[500px] h-[500px] rounded-full blur-[100px] opacity-[0.18]"
          style={{ background: `radial-gradient(circle, ${PURPLE}, transparent)` }} />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] rounded-full blur-[120px] opacity-[0.12]"
          style={{ background: `radial-gradient(circle, ${CYAN}, transparent)` }} />
        {/* Grid */}
        <div className="absolute inset-0 opacity-[0.025]"
          style={{ backgroundImage: `linear-gradient(${BORDER} 1px, transparent 1px), linear-gradient(90deg, ${BORDER} 1px, transparent 1px)`, backgroundSize: "60px 60px" }} />
      </div>

      <div className="relative max-w-7xl mx-auto px-6 py-28 grid lg:grid-cols-[1fr_1.1fr] gap-16 items-center">
        {/* Left copy */}
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium mb-8"
            style={{ background: `${PURPLE}15`, border: `1px solid ${PURPLE}30`, color: VIOLET }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: GREEN }} />
            Now in early access · Layer 3 collective intelligence live
          </div>

          <h1 className="text-[3.6rem] lg:text-[4.2rem] font-extrabold text-white leading-[1.06] tracking-tight mb-6"
            style={{ fontFamily: DISPLAY }}>
            The judgment layer<br />
            <span style={{ background: `linear-gradient(120deg, ${PURPLE}, ${CYAN})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              that learns.
            </span>
          </h1>

          <p className="text-lg text-slate-400 leading-relaxed mb-8 max-w-[520px]">
            Sentigent gives AI agents the one thing they can't get from a larger model or a better prompt:{" "}
            <span className="text-slate-200 font-medium">judgment built from experience.</span>{" "}
            Install once. It starts learning immediately. After 90 days, you have the numbers to prove it worked.
          </p>

          {/* Proof pills */}
          <div className="flex flex-wrap gap-2.5 mb-10">
            {[
              { v: "0.94",  l: "judgment score",  c: GREEN  },
              { v: "0.087", l: "Brier score",      c: CYAN   },
              { v: "+38%",  l: "in 90 days",       c: VIOLET },
            ].map(p => (
              <div key={p.l} className="flex items-center gap-2 px-3 py-2 rounded-lg"
                style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <span className="text-sm font-bold" style={{ fontFamily: MONO, color: p.c }}>{p.v}</span>
                <span className="text-xs text-slate-500">{p.l}</span>
              </div>
            ))}
          </div>

          {/* CTAs */}
          <div className="flex flex-wrap gap-4">
            <Link to="/auth/signup"
              className="flex items-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-white transition-all hover:scale-105"
              style={{ background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`, boxShadow: `0 0 36px ${PURPLE}45` }}>
              Get started free <ArrowRight size={16} />
            </Link>
            <a href="#proof"
              className="flex items-center gap-2 px-7 py-3.5 rounded-xl font-medium text-slate-300 transition-all hover:border-slate-500 hover:text-white"
              style={{ border: `1px solid ${BORDER}` }}>
              See the proof <ChevronRight size={16} />
            </a>
          </div>
        </div>

        {/* Right: Terminal */}
        <div className="relative">
          <TerminalWindow />
          {/* Floating metric card */}
          <div className="absolute -left-10 top-6 hidden xl:block animate-fade-up"
            style={{ animationDelay: "1.2s", animationFillMode: "both" }}>
            <div className="px-4 py-3 rounded-xl shadow-xl" style={{ background: "rgba(10,14,23,0.96)", border: `1px solid ${BORDER}`, backdropFilter: "blur(16px)" }}>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Judgment Score</div>
              <div className="text-2xl font-bold" style={{ fontFamily: MONO, color: GREEN }}>
                <Counter from={0.68} to={0.94} decimals={2} />
              </div>
              <div className="text-[10px] mt-0.5" style={{ color: GREEN }}>↑ +38% in 90 days</div>
            </div>
          </div>
          {/* Floating agent bus card */}
          <div className="absolute -right-6 bottom-10 hidden xl:block animate-fade-up"
            style={{ animationDelay: "1.8s", animationFillMode: "both" }}>
            <div className="px-4 py-3 rounded-xl shadow-xl" style={{ background: "rgba(10,14,23,0.96)", border: `1px solid ${BORDER}`, backdropFilter: "blur(16px)" }}>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">AgentBus · Live</div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: GREEN }} />
                <span className="text-xs text-slate-300">3 agents connected</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function StatsBar() {
  const stats = [
    { from: 0, to: 24,  suffix: "",  label: "MCP tools",          decimals: 0 },
    { from: 0, to: 357, suffix: "+", label: "tests passing",       decimals: 0 },
    { from: 0, to: 5,   suffix: "",  label: "judgment signals",    decimals: 0 },
    { from: 0, to: 3,   suffix: "",  label: "intelligence layers", decimals: 0 },
  ];
  return (
    <section className="py-16 border-y" style={{ borderColor: BORDER }}>
      <div className="max-w-7xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-8">
        {stats.map(s => (
          <div key={s.label} className="text-center">
            <div className="text-4xl font-bold text-white mb-2" style={{ fontFamily: MONO }}>
              <Counter from={s.from} to={s.to} decimals={s.decimals} suffix={s.suffix} />
            </div>
            <div className="text-xs text-slate-500 uppercase tracking-wider">{s.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Problem section ───────────────────────────────────────────────────────────
const PROBLEMS = [
  { icon: <Zap size={20} />, title: "Catastrophic decisions happen fast", accent: RED,
    desc: "One force-push. One DROP TABLE. One accidental blast to 50,000 users. Static rules can't anticipate what they haven't seen. When agents run autonomously, there's no one watching." },
  { icon: <Brain size={20} />, title: "Every session starts from zero", accent: AMBER,
    desc: "Your agent makes the same mistake it made last Tuesday. No memory of outcomes. No accumulated wisdom. No reason to expect today to be different." },
  { icon: <TrendingUp size={20} />, title: "Governance has no proof of value", accent: "#3b82f6",
    desc: "You spend resources on AI safety tooling. At budget review, someone asks: did it work? Without quantitative proof, your honest answer is \"probably.\"" },
  { icon: <MessageSquare size={20} />, title: "Human-agent handoff is broken", accent: VIOLET,
    desc: "Escalations vanish into a void. Agents interrupt at the wrong moment. Humans don't know what the agent has already tried. There's no shared context at handoff." },
];

function ProblemSection() {
  return (
    <section className="py-32">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-20">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>The challenge</div>
          <h2 className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
            The trust crisis in production AI
          </h2>
          <p className="mt-4 text-slate-400 max-w-2xl mx-auto">
            You want autonomous agents. Your org won't give them real authority. Nobody can prove the judgment is reliable. This is the wall every AI deployment hits.
          </p>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
          {PROBLEMS.map(p => (
            <div key={p.title}
              className="p-6 rounded-2xl relative overflow-hidden group transition-all duration-300 hover:-translate-y-1"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500"
                style={{ background: `radial-gradient(ellipse at top left, ${p.accent}0C, transparent 60%)` }} />
              <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-5"
                style={{ background: `${p.accent}18`, color: p.accent }}>
                {p.icon}
              </div>
              <h3 className="font-semibold text-white mb-3 text-sm leading-snug">{p.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{p.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── How it works ─────────────────────────────────────────────────────────────
const HOW_STEPS = [
  {
    n: "01", title: "Install in 60 seconds", accent: PURPLE,
    desc: "pip install and init. Hooks wire into every Bash/Write/Edit call automatically. The MCP server starts. No config files to write.",
    code: "pip install sentigent\nsentigent init\n# hooks installed · MCP running",
  },
  {
    n: "02", title: "Declare your task", accent: CYAN,
    desc: "Before acting, agents declare what they're about to do — goal, scope, constraints. Every subsequent judgment is anchored to this context. Out-of-scope actions auto-escalate.",
    code: 'task_id = sentigent_start_task(\n  goal="Fix JWT expiry bug",\n  scope=["auth/middleware.py"],\n  constraints=["no schema changes"]\n)\n→ {"task_id":"3d884e1c..."}',
  },
  {
    n: "03", title: "Every action is evaluated", accent: GREEN,
    desc: "evaluate() computes 5 signals, checks org policies, enforces the declared task scope, and returns a calibrated decision. Task context makes every call smarter.",
    code: 'sentigent_evaluate(\n  tool="Edit",\n  input="auth/middleware.py",\n  task_id=task_id\n)\n→ {"action":"proceed","confidence":0.87}',
  },
  {
    n: "04", title: "Outcomes teach the system", accent: AMBER,
    desc: "Record what happened. The Brier score updates per task. Patterns crystallize into procedural rules. After 30 days, judgment is measurably sharper than day 1.",
    code: "sentigent_outcome(\n  trace_id=...,\n  outcome='correct'\n)\n→ brier_score updated: 0.112 → 0.099",
  },
  {
    n: "05", title: "Prove it to your team", accent: VIOLET,
    desc: "Run sentigent prove at any time. Get a CFO-ready report: top catches, Brier score trajectory, accuracy vs random baseline. Governance that proves its own value.",
    code: "sentigent prove --days 90\n→ Verdict: PROVEN ✓\n   Judgment: 0.94 · +38% accuracy",
  },
];

function HowItWorksSection() {
  return (
    <section id="how" className="py-32 relative">
      <div className="absolute inset-0 pointer-events-none opacity-20">
        <div className="absolute top-1/2 right-0 w-96 h-96 rounded-full blur-3xl"
          style={{ background: `radial-gradient(circle, ${CYAN}20, transparent)` }} />
      </div>
      <div className="max-w-7xl mx-auto px-6 relative">
        <div className="text-center mb-20">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>How it works</div>
          <h2 className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
            From install to proven in 90 days
          </h2>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-5">
          {HOW_STEPS.map((s, i) => (
            <div key={s.n} className="relative">
              {i < HOW_STEPS.length - 1 && (
                <div className="hidden lg:block absolute top-8 left-[calc(100%+12px)] w-6 h-px opacity-30" style={{ background: s.accent }} />
              )}
              <div className="text-5xl font-black mb-5 select-none" style={{ fontFamily: MONO, color: `${s.accent}25` }}>{s.n}</div>
              <div className="h-0.5 w-8 rounded mb-5" style={{ background: s.accent }} />
              <h3 className="font-bold text-white text-[15px] mb-3" style={{ fontFamily: DISPLAY }}>{s.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed mb-5">{s.desc}</p>
              <div className="p-3 rounded-xl text-[11px] leading-5 whitespace-pre"
                style={{ fontFamily: MONO, background: "#070B12", border: `1px solid ${BORDER}`, color: `${s.accent}CC` }}>
                {s.code}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Five signals ──────────────────────────────────────────────────────────────
const SIGNALS = [
  { name: "Caution",     desc: "Fires on anomalies vs. learned baselines. The more the current context deviates from history, the stronger this signal.",     color: AMBER,  pattern: "anomaly" },
  { name: "Doubt",       desc: "Activates when pattern match strength is low. Seeks enrichment context before committing. Gateway to the LLM Judge.",           color: "#3b82f6", pattern: "low confidence" },
  { name: "Urgency",     desc: "Reduces deliberation for time-sensitive operations. Learned from contexts where speed consistently mattered.",                  color: RED,    pattern: "time pressure" },
  { name: "Confidence",  desc: "Enables the fast path for operations seen hundreds of times with zero adverse outcomes. Routine work flies through.",            color: GREEN,  pattern: "routine ops" },
  { name: "Frustration", desc: "Triggers strategy change after repeated failures. Forces a different approach when the same iteration keeps failing.",           color: VIOLET, pattern: "failure loops" },
];

function SignalsSection() {
  return (
    <section id="signals" className="py-32">
      <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-[1fr_1.1fr] gap-20 items-start">
        {/* Left */}
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>Judgment engine</div>
          <h2 className="text-4xl font-extrabold text-white mb-6" style={{ fontFamily: DISPLAY }}>
            Five signals.<br />One calibrated decision.
          </h2>
          <p className="text-slate-400 leading-relaxed mb-8">
            Each evaluate() call computes five independent signals from the gap between what your agent has learned to expect and what it's currently seeing.
            They're not static thresholds. They shift as the agent operates.
            A $50K refund that triggers caution on day 1 might be routine on day 180.
          </p>
          {/* Live output sample */}
          <div className="rounded-xl p-4" style={{ background: "#070B12", border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] text-slate-600 mb-2 uppercase tracking-wider" style={{ fontFamily: MONO }}># evaluate() response</div>
            <div className="text-xs leading-5" style={{ fontFamily: MONO }}>
              <div className="text-slate-500">{"{"}</div>
              <div className="pl-4"><span style={{ color: CYAN }}>"action"</span>: <span style={{ color: GREEN }}>"slow_down"</span>,</div>
              <div className="pl-4"><span style={{ color: CYAN }}>"confidence"</span>: <span style={{ color: AMBER }}>0.41</span>,</div>
              <div className="pl-4"><span style={{ color: CYAN }}>"reason"</span>: <span style={{ color: GREEN }}>"caution=0.82, doubt=0.61"</span>,</div>
              <div className="pl-4"><span style={{ color: CYAN }}>"signals"</span>: {"{"}</div>
              <div className="pl-8 text-slate-400">"caution": 0.82, "doubt": 0.61,</div>
              <div className="pl-8 text-slate-400">"urgency": 0.12, "confidence": 0.23</div>
              <div className="pl-4 text-slate-500">{"}"}</div>
              <div className="text-slate-500">{"}"}</div>
            </div>
          </div>
        </div>

        {/* Right: signal cards */}
        <div className="space-y-3">
          {SIGNALS.map(s => (
            <div key={s.name}
              className="flex gap-4 p-4 rounded-xl group cursor-default transition-all duration-200 hover:-translate-x-1"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="mt-2 w-2 h-2 rounded-full flex-shrink-0" style={{ background: s.color, boxShadow: `0 0 10px ${s.color}60` }} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 mb-1">
                  <span className="font-semibold text-white text-sm">{s.name}</span>
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded" style={{ background: `${s.color}15`, color: s.color, fontFamily: MONO }}>{s.pattern}</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Architecture ──────────────────────────────────────────────────────────────
const LAYERS = [
  {
    n: "1", name: "Local Intelligence", sub: "Your machine · SQLite", color: PURPLE,
    desc: "Every evaluate() call recorded locally. Patterns emerge from your actual usage. No data leaves your machine unless you explicitly opt in.",
    items: ["Episode ledger", "Procedural rules", "Outcome tracking", "Brier score"],
  },
  {
    n: "2", name: "Org Intelligence", sub: "Your org · Supabase · RLS", color: CYAN,
    desc: "Org-wide policies, agent profiles, and shared patterns. Every agent in your org benefits from what any agent learns. Row-level security enforced.",
    items: ["Policy enforcement", "Agent profiles", "Shared org patterns", "Proof of value report"],
  },
  {
    n: "3", name: "Collective Intelligence", sub: "The network · Opt-in", color: GREEN,
    desc: "Anonymized patterns contributed by all participating orgs. No org identifiers stored. Opt in, contribute, and benefit from network-wide learning.",
    items: ["Cross-org patterns", "Anonymous contribution", "Cold-start boost", "Network flywheel"],
  },
];

function ArchitectureSection() {
  return (
    <section id="architecture" className="py-32 relative">
      <div className="pointer-events-none absolute inset-0 opacity-25">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] rounded-full blur-[120px]"
          style={{ background: `radial-gradient(circle, ${PURPLE}18, transparent)` }} />
      </div>
      <div className="max-w-7xl mx-auto px-6 relative">
        <div className="text-center mb-20">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>Architecture</div>
          <h2 className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
            Three layers. One learning system.
          </h2>
          <p className="mt-4 text-slate-400 max-w-xl mx-auto">
            Intelligence compounds at every level. From individual sessions, to your org, to the global network.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6 relative">
          {/* Connection arrows */}
          <div className="hidden md:flex absolute top-10 left-1/3 right-1/3 justify-between items-center px-4 z-10">
            <div className="flex-1 h-px opacity-30" style={{ background: `linear-gradient(90deg, ${PURPLE}, ${CYAN})` }} />
            <ArrowRight size={14} className="opacity-30" style={{ color: CYAN }} />
          </div>
          <div className="hidden md:flex absolute top-10 left-2/3 right-0 justify-between items-center px-4 z-10">
            <div className="flex-1 h-px opacity-30" style={{ background: `linear-gradient(90deg, ${CYAN}, ${GREEN})` }} />
            <ArrowRight size={14} className="opacity-30" style={{ color: GREEN }} />
          </div>

          {LAYERS.map((layer, i) => (
            <div key={layer.n}
              className="relative p-7 rounded-2xl transition-all duration-300 hover:-translate-y-1.5"
              style={{ background: i === 1 ? "rgba(13,17,23,0.9)" : SURFACE, border: `1px solid ${i === 1 ? layer.color + "35" : BORDER}` }}>
              <div className="absolute -top-3 left-7 px-2.5 py-0.5 rounded text-[10px] font-bold"
                style={{ background: layer.color, color: "white", fontFamily: MONO }}>Layer {layer.n}</div>
              <div className="mt-3 mb-5">
                <div className="font-bold text-white text-[17px] mb-1" style={{ fontFamily: DISPLAY }}>{layer.name}</div>
                <div className="text-[10px] text-slate-500" style={{ fontFamily: MONO }}>{layer.sub}</div>
              </div>
              <p className="text-xs text-slate-400 leading-relaxed mb-6">{layer.desc}</p>
              <ul className="space-y-2">
                {layer.items.map(item => (
                  <li key={item} className="flex items-center gap-2 text-xs text-slate-400">
                    <Check size={11} style={{ color: layer.color, flexShrink: 0 }} />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Proof section ─────────────────────────────────────────────────────────────
function ProofSection() {
  return (
    <section id="proof" className="py-32">
      <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-16 items-center">
        {/* Terminal mock */}
        <div className="rounded-2xl overflow-hidden shadow-2xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center gap-1.5 px-4 py-3 border-b" style={{ background: "#0D1117", borderColor: BORDER }}>
            <div className="w-3 h-3 rounded-full" style={{ background: "#ff5f57" }} />
            <div className="w-3 h-3 rounded-full" style={{ background: "#febc2e" }} />
            <div className="w-3 h-3 rounded-full" style={{ background: "#28c840" }} />
            <span className="ml-3 text-xs text-slate-500" style={{ fontFamily: MONO }}>sentigent prove --days 90</span>
          </div>
          <div className="p-5 text-xs leading-6" style={{ fontFamily: MONO }}>
            {[
              { t: "$ sentigent prove --days 90",                              c: "#34d399" },
              { t: " ",                                                        c: "transparent" },
              { t: "═══════════════════════════════════════════════",           c: "#334155" },
              { t: " Sentigent  ⬡  Proof of Value — Last 90 Days",             c: "#c4b5fd" },
              { t: "═══════════════════════════════════════════════",           c: "#334155" },
              { t: " ",                                                        c: "transparent" },
              { t: " Judgment Score:      0.94  ↑ +38%",                      c: "#34d399" },
              { t: " Brier Score:        0.087  (0.0 = perfect)",              c: "#94a3b8" },
              { t: " Decisions evaluated:  847",                               c: "#94a3b8" },
              { t: " Correct calls:        796  (94.0%)",                      c: "#94a3b8" },
              { t: " ",                                                        c: "transparent" },
              { t: " Top catches confirmed by outcome:",                       c: "#64748b" },
              { t: "  1. force_push_block    12×  100% acc  P=0.96",           c: "#22d3ee" },
              { t: "  2. deploy_escalation    8×   88% acc  P=0.88",           c: "#22d3ee" },
              { t: "  3. env_write_slow       5×  100% acc  P=0.98",           c: "#22d3ee" },
              { t: " ",                                                        c: "transparent" },
              { t: " False negative rate:   3.2%",                            c: "#94a3b8" },
              { t: " vs. random baseline:  +38% improvement",                 c: "#94a3b8" },
              { t: " ",                                                        c: "transparent" },
              { t: "═══════════════════════════════════════════════",           c: "#334155" },
              { t: " Verdict: PROVEN  ✓",                                     c: "#34d399" },
              { t: "═══════════════════════════════════════════════",           c: "#334155" },
            ].map((line, i) => (
              <div key={i} style={{ color: line.c }}>{line.t}</div>
            ))}
          </div>
        </div>

        {/* Copy */}
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>Proof of value</div>
          <h2 className="text-4xl font-extrabold text-white mb-6" style={{ fontFamily: DISPLAY }}>
            The first governance tool that answers "did it work?"
          </h2>
          <p className="text-slate-400 leading-relaxed mb-5">
            The hardest thing about AI governance is proving it works. Teams spend real money, write policies, tune models — then struggle to show ROI.
          </p>
          <p className="text-slate-400 leading-relaxed mb-8">
            <span className="text-slate-200 font-medium">Brier score</span> is a calibrated probability accuracy metric. 0.087 isn't just "good" — it's a specific, reproducible number. You can compare it to random (0.25) and to perfect (0.0). It's the data that answers "Is our AI governance working?" in a budget review.
          </p>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Day 1",        value: "0.68",  color: RED,    sub: "near-random" },
              { label: "Day 90",       value: "0.94",  color: GREEN,  sub: "proven"      },
              { label: "Improvement",  value: "+38%",  color: VIOLET, sub: "in 90 days"  },
            ].map(m => (
              <div key={m.label} className="p-4 rounded-xl text-center" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <div className="text-2xl font-bold mb-1" style={{ fontFamily: MONO, color: m.color }}>{m.value}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">{m.label}</div>
                <div className="text-[10px] mt-1" style={{ color: `${m.color}70`, fontFamily: MONO }}>{m.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Human-agent interaction ───────────────────────────────────────────────────
const HITL_FEATURES = [
  { icon: <AlertTriangle size={16} />, title: "Smart escalation routing", desc: "High-confidence escalations go to Slack. Critical ops go to PagerDuty. Routine anomalies go to the daily digest. No more alert fatigue.", color: AMBER },
  { icon: <MessageSquare size={16} />, title: "Full context at handoff", desc: "When an agent escalates, the human sees exactly what the agent tried, what it found, why it stopped, and what it recommends. No archaeology required.", color: CYAN },
  { icon: <Users size={16} />, title: "One-click approve / reject", desc: "The approval UI surfaces the decision, confidence score, and reasoning. Approve or reject in one click. The outcome feeds back to calibration.", color: GREEN },
  { icon: <Activity size={16} />, title: "Live decision feed", desc: "Real-time stream of every evaluate() call in the dashboard. Filter by action, agent, confidence, or policy hit. Full audit trail on demand.", color: VIOLET },
  { icon: <Brain size={16} />, title: "Human feedback is gold data", desc: "Every human approval or rejection is the highest-quality training signal. It updates the Brier score immediately and reinforces the right learned patterns.", color: PURPLE },
  { icon: <Database size={16} />, title: "Immutable audit ledger", desc: "Every decision, every escalation, every outcome — permanently recorded with timestamps, confidence, and reasoning. SOC 2 audit-ready on day 1.", color: RED },
];

function HumanAgentSection() {
  return (
    <section className="py-32 relative">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] blur-[100px] opacity-10"
          style={{ background: `radial-gradient(ellipse, ${VIOLET}, transparent)` }} />
      </div>
      <div className="max-w-7xl mx-auto px-6 relative">
        <div className="text-center mb-20">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>Human · Agent collaboration</div>
          <h2 className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
            The handoff that actually works
          </h2>
          <p className="mt-4 text-slate-400 max-w-2xl mx-auto">
            Most escalations are useless — a ping with no context, interrupting at the wrong moment. Sentigent redesigns the human-agent boundary:
            agents know when to stop, humans know exactly what they're approving, and every decision makes the system smarter.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {HITL_FEATURES.map(f => (
            <div key={f.title}
              className="p-6 rounded-2xl group transition-all duration-300 hover:-translate-y-1"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-5" style={{ background: `${f.color}15`, color: f.color }}>
                {f.icon}
              </div>
              <h3 className="font-semibold text-white mb-2 text-sm">{f.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Features grid ─────────────────────────────────────────────────────────────
const FEATURES = [
  { icon: <Shield size={18} />,   title: "Org Policy Enforcement",   color: PURPLE, desc: "Define policies at org level. Every agent, every session. Critical rules like no_force_push with zero config overhead." },
  { icon: <Brain size={18} />,    title: "LLM Judge",                color: CYAN,   desc: "Ambiguous decisions in the 0.30–0.70 zone go to a fast language model for reasoning. Haiku by default, configurable." },
  { icon: <Activity size={18} />, title: "AgentBus",                 color: GREEN,  desc: "Inter-agent messaging with capability routing. Delegate tasks. Uncertainty propagates across pipeline stages before cascading." },
  { icon: <GitFork size={18} />,  title: "Collective Learning",      color: AMBER,  desc: "Opt in to Layer 3. Contribute anonymized patterns. Pull from the global pool. First-mover advantage compounds daily." },
  { icon: <Lock size={18} />,     title: "Agent Profiles",           color: RED,    desc: "security_engineer, PM, devops — each shifts value weights and detection thresholds. One install, multiple behavioral modes." },
  { icon: <Terminal size={18} />, title: "24 MCP Tools",             color: VIOLET, desc: "Full Model Context Protocol integration. evaluate, score, prove, patterns, policy, profile, coach, bus — all in Claude Code." },
];

function FeaturesSection() {
  return (
    <section className="py-32">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-20">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-4" style={{ fontFamily: MONO }}>Capabilities</div>
          <h2 className="text-4xl font-extrabold text-white" style={{ fontFamily: DISPLAY }}>
            Built for the full agentic lifecycle
          </h2>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map(f => (
            <div key={f.title}
              className="p-6 rounded-2xl group transition-all duration-300 hover:-translate-y-1 hover:border-slate-700"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-5" style={{ background: `${f.color}15`, color: f.color }}>
                {f.icon}
              </div>
              <h3 className="font-semibold text-white mb-2 text-sm">{f.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── CTA ───────────────────────────────────────────────────────────────────────
function CTASection() {
  return (
    <section className="py-32">
      <div className="max-w-4xl mx-auto px-6 text-center relative">
        <div className="absolute inset-0 -m-16 rounded-full blur-[80px] opacity-15 pointer-events-none"
          style={{ background: `radial-gradient(circle, ${PURPLE}, transparent)` }} />
        <div className="relative">
          <h2 className="text-5xl font-extrabold text-white mb-6 leading-[1.1]" style={{ fontFamily: DISPLAY }}>
            Give your agent the judgment<br />
            <span style={{ background: `linear-gradient(120deg, ${PURPLE}, ${CYAN})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              it can't learn from a prompt.
            </span>
          </h2>
          <p className="text-lg text-slate-400 mb-10 max-w-2xl mx-auto">
            Start free. See judgment scores on day 1. In 90 days, run{" "}
            <code className="px-1.5 py-0.5 rounded text-sm" style={{ fontFamily: MONO, background: SURFACE, color: GREEN }}>sentigent prove</code>{" "}
            and bring the numbers to your team.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/auth/signup"
              className="flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-white text-[15px] transition-all hover:scale-105"
              style={{ background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`, boxShadow: `0 0 48px ${PURPLE}45` }}>
              Get started free <ArrowRight size={18} />
            </Link>
            <Link to="/pricing"
              className="flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-medium text-slate-300 transition-all hover:text-white hover:border-slate-500"
              style={{ border: `1px solid ${BORDER}` }}>
              See pricing <ChevronRight size={18} />
            </Link>
          </div>
          <p className="mt-6 text-xs text-slate-600">No credit card required · Starter plan free forever · Install in 60 seconds</p>
        </div>
      </div>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────
function Footer() {
  const cols = [
    { title: "Product",   links: [{ l: "Features", h: "#signals" }, { l: "Proof", h: "#proof" }, { l: "Architecture", h: "#architecture" }, { l: "Pricing", h: "/pricing" }] },
    { title: "Platform",  links: [{ l: "Dashboard", h: "/dashboard" }, { l: "Policies", h: "/policies" }, { l: "Intelligence", h: "/intelligence" }, { l: "Collective", h: "/collective" }] },
    { title: "Docs",      links: [{ l: "Quick start", h: "/help" }, { l: "MCP tools", h: "/help" }, { l: "REST API", h: "/help" }, { l: "Configuration", h: "/help" }] },
    { title: "Account",   links: [{ l: "Sign in", h: "/auth/login" }, { l: "Get started", h: "/auth/signup" }] },
  ];
  return (
    <footer className="py-16 border-t" style={{ borderColor: BORDER }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid md:grid-cols-[1.5fr_1fr_1fr_1fr_1fr] gap-12 mb-12">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${PURPLE}, ${CYAN})` }}>
                <span className="text-white text-[11px] font-black">S</span>
              </div>
              <span className="font-bold text-white" style={{ fontFamily: DISPLAY }}>Sentigent</span>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed max-w-[200px]">
              The judgment layer that learns. For AI agents that need to earn trust.
            </p>
            <div className="mt-5 text-[10px] font-mono text-slate-700">brier_score: 0.087 · proven ✓</div>
          </div>
          {/* Link columns */}
          {cols.map(col => (
            <div key={col.title}>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-[0.15em] mb-4">{col.title}</div>
              <ul className="space-y-2.5">
                {col.links.map(link => (
                  <li key={link.l}>
                    {link.h.startsWith("http") || link.h.startsWith("#")
                      ? <a href={link.h} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">{link.l}</a>
                      : <Link to={link.h} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">{link.l}</Link>
                    }
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="pt-8 border-t flex flex-col md:flex-row justify-between gap-4 text-[11px] text-slate-700" style={{ borderColor: BORDER }}>
          <span>© 2025 Sentigent. The judgment layer for AI agents.</span>
          <span style={{ fontFamily: MONO }}>v0.1 · early access</span>
        </div>
      </div>
    </footer>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function Landing() {
  return (
    <div className="min-h-screen text-white" style={{ background: BG, fontFamily: "'Inter', sans-serif" }}>
      <MarketingNav />
      <HeroSection />
      <StatsBar />
      <ProblemSection />
      <HowItWorksSection />
      <SignalsSection />
      <ArchitectureSection />
      <ProofSection />
      <HumanAgentSection />
      <FeaturesSection />
      <CTASection />
      <Footer />
    </div>
  );
}
