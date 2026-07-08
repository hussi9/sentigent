import { useEffect, useRef, useState } from "react";

// ── Design tokens ──────────────────────────────────────────────────────────────
const BG = "#030712";
const SURFACE = "#0A0E17";
const BORDER = "rgba(30,41,59,0.6)";
const PURPLE = "#7c3aed";
const PURPLE_LIGHT = "#a78bfa";
const CYAN = "#06b6d4";
const GREEN = "#10b981";
const AMBER = "#f59e0b";
const RED = "#ef4444";
const DISPLAY = "'Bricolage Grotesque', sans-serif";
const MONO = "'JetBrains Mono', monospace";

// ── Intersection observer hook ────────────────────────────────────────────────
function useVisible(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, visible };
}


// ── Section number watermark ──────────────────────────────────────────────────
function SlideNum({ n }: { n: string }) {
  return (
    <div style={{
      position: "absolute", top: "50%", right: "-0.05em",
      transform: "translateY(-50%)",
      fontFamily: DISPLAY, fontSize: "clamp(12rem, 20vw, 22rem)",
      fontWeight: 800, color: "rgba(124,58,237,0.04)",
      lineHeight: 1, pointerEvents: "none", userSelect: "none",
      letterSpacing: "-0.04em",
    }}>{n}</div>
  );
}

// ── Thin rule ─────────────────────────────────────────────────────────────────
function Rule() {
  return <div style={{ height: 1, background: BORDER, margin: "3rem 0" }} />;
}

// ── Slide label ───────────────────────────────────────────────────────────────
function Label({ n, text }: { n: string; text: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "2.5rem" }}>
      <span style={{ fontFamily: MONO, fontSize: "0.6875rem", color: PURPLE, letterSpacing: "0.12em", textTransform: "uppercase" }}>
        {n}
      </span>
      <div style={{ height: 1, flex: 1, background: `linear-gradient(90deg, ${PURPLE}40, transparent)` }} />
      <span style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.25)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
        {text}
      </span>
    </div>
  );
}

// ── Slide wrapper ─────────────────────────────────────────────────────────────
function Slide({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  const { ref, visible } = useVisible(0.05);
  return (
    <div ref={ref} style={{
      position: "relative", overflow: "hidden",
      minHeight: "100vh", display: "flex", flexDirection: "column",
      justifyContent: "center",
      padding: "6rem clamp(1.5rem, 8vw, 9rem)",
      transition: "opacity 0.7s ease, transform 0.7s ease",
      opacity: visible ? 1 : 0,
      transform: visible ? "translateY(0)" : "translateY(32px)",
      ...style,
    }}>
      {children}
    </div>
  );
}

// ── Competitor table row ──────────────────────────────────────────────────────
function CompRow({ name, raised, learning, proof, network, highlight }: {
  name: string; raised: string; learning: boolean; proof: boolean; network: boolean; highlight?: boolean;
}) {
  const bg = highlight ? `linear-gradient(90deg, ${PURPLE}18, transparent)` : undefined;
  const border = highlight ? `1px solid ${PURPLE}40` : `1px solid ${BORDER}`;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
      padding: "1rem 1.25rem", background: bg, border,
      borderRadius: "0.5rem", marginBottom: "0.5rem",
      alignItems: "center",
    }}>
      <span style={{ fontFamily: MONO, fontSize: "0.8125rem", color: highlight ? PURPLE_LIGHT : "rgba(255,255,255,0.8)", fontWeight: highlight ? 600 : 400 }}>{name}</span>
      <span style={{ fontFamily: MONO, fontSize: "0.8125rem", color: "rgba(255,255,255,0.4)" }}>{raised}</span>
      <span style={{ fontFamily: MONO, fontSize: "0.8125rem", color: learning ? GREEN : RED }}>{learning ? "✓ Yes" : "✗ No"}</span>
      <span style={{ fontFamily: MONO, fontSize: "0.8125rem", color: proof ? GREEN : RED }}>{proof ? "✓ Yes" : "✗ No"}</span>
      <span style={{ fontFamily: MONO, fontSize: "0.8125rem", color: network ? GREEN : RED }}>{network ? "✓ Yes" : "✗ No"}</span>
    </div>
  );
}

// ── Signal pill ───────────────────────────────────────────────────────────────
function SignalPill({ name, color, desc, value }: { name: string; color: string; desc: string; value: string }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        border: `1px solid ${hovered ? color : BORDER}`,
        borderRadius: "0.75rem",
        padding: "1.5rem",
        background: hovered ? `${color}0d` : SURFACE,
        transition: "all 0.25s ease",
        cursor: "default",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
        <span style={{ fontFamily: MONO, fontSize: "0.625rem", color, letterSpacing: "0.12em", textTransform: "uppercase" }}>{name}</span>
        <span style={{ fontFamily: MONO, fontSize: "1rem", color, fontWeight: 700 }}>{value}</span>
      </div>
      <p style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.55)", lineHeight: 1.5, margin: 0 }}>{desc}</p>
    </div>
  );
}

// ── Navigation ────────────────────────────────────────────────────────────────
function PitchNav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const sections = ["Problem", "Solution", "Signals", "Proof", "Market", "Competition", "Model", "GTM", "Moat", "Ask"];

  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
      padding: "1rem 2rem",
      background: scrolled ? "rgba(3,7,18,0.92)" : "transparent",
      backdropFilter: scrolled ? "blur(12px)" : "none",
      borderBottom: scrolled ? `1px solid ${BORDER}` : "none",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      transition: "all 0.4s ease",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <div style={{
          width: 28, height: 28, borderRadius: "0.375rem",
          background: `linear-gradient(135deg, ${PURPLE}, #a855f7)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "0.75rem", fontWeight: 700, color: "white",
        }}>S</div>
        <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem", color: "white" }}>Sentigent</span>
        <span style={{ fontFamily: MONO, fontSize: "0.625rem", color: PURPLE, letterSpacing: "0.1em", textTransform: "uppercase", marginLeft: "0.25rem" }}>// Investor Deck</span>
      </div>
      <div style={{ display: "flex", gap: "1.5rem" }}>
        {sections.slice(0, 5).map(s => (
          <span key={s} style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.35)", letterSpacing: "0.06em", cursor: "pointer" }}>{s}</span>
        ))}
      </div>
    </nav>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function InvestorPitch() {
  return (
    <div style={{ background: BG, color: "white", minHeight: "100vh" }}>
      <PitchNav />

      {/* ─── 00 HOOK ─────────────────────────────────────────────────────────── */}
      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        justifyContent: "center", alignItems: "center", textAlign: "center",
        padding: "6rem 2rem", position: "relative", overflow: "hidden",
      }}>
        {/* Atmospheric background */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          background: `radial-gradient(ellipse 60% 50% at 50% 30%, ${PURPLE}22 0%, transparent 70%),
                       radial-gradient(ellipse 40% 30% at 80% 70%, ${CYAN}0f 0%, transparent 60%)`,
        }} />
        {/* Grid texture */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none", opacity: 0.04,
          backgroundImage: `linear-gradient(${BORDER} 1px, transparent 1px), linear-gradient(90deg, ${BORDER} 1px, transparent 1px)`,
          backgroundSize: "60px 60px",
        }} />

        <div style={{ position: "relative", maxWidth: "900px" }}>
          <div style={{ marginBottom: "1.5rem" }}>
            <span style={{
              display: "inline-block",
              fontFamily: MONO, fontSize: "0.6875rem",
              color: PURPLE, letterSpacing: "0.15em", textTransform: "uppercase",
              background: `${PURPLE}14`, padding: "0.35rem 0.875rem",
              borderRadius: "9999px", border: `1px solid ${PURPLE}30`,
            }}>
              Confidential — February 2026
            </span>
          </div>

          <h1 style={{
            fontFamily: DISPLAY, fontSize: "clamp(3rem, 7vw, 6.5rem)",
            fontWeight: 800, lineHeight: 1.03, letterSpacing: "-0.03em",
            margin: "0 0 2rem",
          }}>
            AI agents that do{" "}
            <span style={{
              background: `linear-gradient(135deg, ${PURPLE_LIGHT}, ${CYAN})`,
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            }}>real work.</span>
            {" "}Proved.
          </h1>

          <p style={{
            fontFamily: DISPLAY, fontSize: "clamp(1.125rem, 2vw, 1.5rem)",
            color: "rgba(255,255,255,0.55)", lineHeight: 1.6,
            maxWidth: "640px", margin: "0 auto 3rem",
          }}>
            Right now your AI agents are doing low-risk, low-value tasks because nobody can prove they're
            safe for anything else. Sentigent gives you the proof — and your engineers get 2 hours a day back.
          </p>

          <div style={{ display: "flex", gap: "2rem", justifyContent: "center", flexWrap: "wrap" }}>
            {[
              { label: "Tasks completed autonomously", value: "94%", sub: "no human review needed", color: GREEN },
              { label: "Cost saved per team / year", value: "$105K", sub: "in rework + wasted tokens", color: CYAN },
              { label: "Catastrophic incidents prevented", value: "0", sub: "in 90 days of production", color: PURPLE_LIGHT },
            ].map(m => (
              <div key={m.label} style={{ textAlign: "center" }}>
                <div style={{ fontFamily: MONO, fontSize: "2.25rem", fontWeight: 700, color: m.color, letterSpacing: "-0.02em" }}>
                  {m.value}
                </div>
                <div style={{ fontFamily: MONO, fontSize: "0.625rem", color: "rgba(255,255,255,0.3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{m.label}</div>
                <div style={{ fontFamily: MONO, fontSize: "0.625rem", color: m.color, opacity: 0.7 }}>{m.sub}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          position: "absolute", bottom: "2.5rem", left: "50%", transform: "translateX(-50%)",
          display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem",
        }}>
          <span style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.2)", letterSpacing: "0.1em", textTransform: "uppercase" }}>scroll</span>
          <div style={{
            width: 1, height: 40,
            background: `linear-gradient(to bottom, ${PURPLE}60, transparent)`,
            animation: "fadeUp 2s ease infinite",
          }} />
        </div>
      </div>

      {/* ─── 01 PROBLEM ──────────────────────────────────────────────────────── */}
      <Slide style={{ background: SURFACE }}>
        <SlideNum n="01" />
        <Label n="01 —" text="The Problem" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2.5rem, 5vw, 4.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.05, margin: "0 0 1.5rem", maxWidth: "780px" }}>
          You spent $500K on AI agents.{" "}
          <span style={{ color: RED }}>They're writing summaries and drafting emails.</span>
        </h2>
        <p style={{ fontFamily: DISPLAY, fontSize: "1.125rem", color: "rgba(255,255,255,0.5)", maxWidth: "600px", lineHeight: 1.7, marginBottom: "4rem" }}>
          Not because the models aren't capable. Because the moment someone asks "what happens when it deletes
          the wrong database?" — the answer is silence. So agents get restricted to zero-stakes tasks.
          Your $500K investment has a $0 ROI. And every month that continues, a competitor doesn't.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem", marginBottom: "4rem" }}>
          {[
            { title: "$200K+ per incident", icon: "💥", desc: "One wrong database operation, one bulk email blast, one force push to production. These happen. Static blocklists don't prevent them — they just ban a list of commands.", color: RED },
            { title: "2–3 hours/day per engineer", icon: "👁️", desc: "Engineers review every agent action because they don't trust it. That's not autonomy — that's an expensive copilot with extra steps.", color: AMBER },
            { title: "The dark factory problem", icon: "🏭", desc: "Multi-agent swarms lose the bigger picture. Each agent acts locally correct but globally wrong. Nobody declared the task. Nobody knows what scope is in play.", color: CYAN },
            { title: "CFO kills the budget", icon: "📊", desc: "\"Show me the ROI.\" You have a demo. They want a number. Without proof, AI governance is the first budget line cut.", color: PURPLE_LIGHT },
          ].map(p => (
            <div key={p.title} style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.5rem" }}>
              <div style={{ fontSize: "1.5rem", marginBottom: "0.75rem" }}>{p.icon}</div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem", color: p.color, marginBottom: "0.5rem" }}>{p.title}</div>
              <p style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.45)", margin: 0, lineHeight: 1.6 }}>{p.desc}</p>
            </div>
          ))}
        </div>

        {/* The cost math */}
        <div style={{
          background: `linear-gradient(135deg, ${PURPLE}14, ${CYAN}0a)`,
          border: `1px solid ${PURPLE}30`, borderRadius: "1rem", padding: "2rem",
          maxWidth: "700px",
        }}>
          <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: PURPLE, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1rem" }}>The Cost Math Nobody Is Tracking</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1.5rem" }}>
            {[
              { label: "Avg clarification cycles / task", before: "3.2×", after: "1.1×", color: RED },
              { label: "Token reduction", before: "—", after: "65%", color: GREEN },
              { label: "Annual savings / team", before: "—", after: "$105K", color: CYAN },
            ].map(m => (
              <div key={m.label}>
                <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.5rem" }}>{m.label}</div>
                <div style={{ fontFamily: MONO, fontSize: "1.25rem", color: m.color, fontWeight: 700 }}>{m.after}</div>
                {m.before !== "—" && <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: "rgba(255,255,255,0.25)", textDecoration: "line-through" }}>{m.before}</div>}
              </div>
            ))}
          </div>
        </div>
      </Slide>

      {/* ─── 02 SOLUTION ─────────────────────────────────────────────────────── */}
      <Slide>
        <SlideNum n="02" />
        <Label n="02 —" text="The Solution" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2.25rem, 4.5vw, 4rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.07, margin: "0 0 1.5rem", maxWidth: "700px" }}>
          Agents that know what they're supposed to be doing — and prove it.
        </h2>
        <p style={{ fontFamily: DISPLAY, fontSize: "1rem", color: "rgba(255,255,255,0.5)", maxWidth: "520px", lineHeight: 1.7, marginBottom: "3.5rem" }}>
          The dark factory problem: autonomous agents lose context between actions. They do the right
          thing locally and the wrong thing globally. Sentigent's three-layer architecture gives
          every agent a declared task, enforced scope, and a track record that gets better over time.
        </p>

        {/* Architecture diagram — 4-layer */}
        <div style={{ maxWidth: "680px", fontFamily: MONO, fontSize: "0.8125rem" }}>
          {[
            { label: "HUMAN", sub: "\"fix the auth stuff\"", color: CYAN, note: "← natural language goal" },
            { label: "│", sub: "intent extraction · scope declaration · constraints", color: PURPLE, arrow: true },
            { label: "TASK CONTEXT", sub: "goal · scope[] · constraints · task_id", color: AMBER, note: "← Layer 2  ·  NEW" },
            { label: "│", sub: "scope enforcement · episode tracking · auto-escalate if out-of-scope", color: AMBER, arrow: true },
            { label: "AGENT", sub: "thinking, planning, deciding", color: PURPLE_LIGHT, note: "← Judgment Layer" },
            { label: "│", sub: "5 signals · LLM judge · task-anchored policy · Brier score", color: PURPLE, arrow: true },
            { label: "ENVIRONMENT", sub: "file system · APIs · databases · git", color: GREEN, note: "← Executor" },
          ].map((row, i) => (
            <div key={i} style={{ marginBottom: row.arrow ? "0" : "0" }}>
              {row.arrow ? (
                <div style={{ padding: "0.5rem 1.5rem", color: "rgba(255,255,255,0.25)", borderLeft: `1px solid ${BORDER}`, marginLeft: "1.5rem" }}>
                  <div style={{ color: row.color, fontSize: "0.6875rem", letterSpacing: "0.08em" }}>↓ {row.sub}</div>
                </div>
              ) : (
                <div style={{
                  padding: "1.25rem 1.5rem",
                  background: `${row.color}0d`,
                  border: `1px solid ${row.color}30`,
                  borderRadius: "0.5rem",
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  marginBottom: "0",
                }}>
                  <div>
                    <div style={{ color: row.color, fontWeight: 700, marginBottom: "0.2rem" }}>{row.label}</div>
                    <div style={{ color: "rgba(255,255,255,0.35)", fontSize: "0.75rem" }}>{row.sub}</div>
                  </div>
                  {row.note && <div style={{ color: row.color, fontSize: "0.6875rem", opacity: 0.7 }}>{row.note}</div>}
                </div>
              )}
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", maxWidth: "680px", marginTop: "3rem" }}>
          {[
            { n: "Layer 1 — Per Agent", title: "Task-anchored judgment", desc: "Agents declare goal + scope before acting. Every evaluate() call is anchored to that context. Out-of-scope actions auto-escalate. Zero false negatives.", status: "Built", color: GREEN },
            { n: "Layer 2 — Org Brain", title: "Policies that actually work", desc: "Org-wide task history, scope violation tracking, shared policies. Every agent in your org benefits from what every other agent learned on real tasks.", status: "Built", color: CYAN },
            { n: "Layer 3 — Collective", title: "Network effect moat", desc: "When 100 teams use Sentigent, every team gets smarter signal on day 1 than any competitor can offer on day 365. No data shared. Pure pattern value.", status: "Shipping", color: PURPLE_LIGHT },
          ].map(l => (
            <div key={l.n} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.25rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                <span style={{ fontFamily: MONO, fontSize: "0.5625rem", color: l.color, letterSpacing: "0.1em", textTransform: "uppercase" }}>{l.n}</span>
                <span style={{ fontFamily: MONO, fontSize: "0.5625rem", background: `${l.color}20`, color: l.color, padding: "0.1rem 0.4rem", borderRadius: "9999px" }}>{l.status}</span>
              </div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.9375rem", marginBottom: "0.5rem" }}>{l.title}</div>
              <p style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.4)", margin: 0, lineHeight: 1.5 }}>{l.desc}</p>
            </div>
          ))}
        </div>
      </Slide>

      {/* ─── 03 FIVE SIGNALS ─────────────────────────────────────────────────── */}
      <Slide style={{ background: SURFACE }}>
        <SlideNum n="03" />
        <Label n="03 —" text="How Trust Is Earned" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 1rem", maxWidth: "660px" }}>
          The agent earns more autonomy the more it gets right. Your oversight shrinks as its track record grows.
        </h2>
        <p style={{ fontFamily: DISPLAY, fontSize: "1rem", color: "rgba(255,255,255,0.45)", maxWidth: "520px", lineHeight: 1.7, marginBottom: "3rem" }}>
          On day 1 the agent checks in. By day 90 it handles routine operations without interruption —
          because it has the receipts. Every decision has a reason. Every reason has a number.
          The CISO can audit the full history at any time.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.875rem" }}>
          <SignalPill name="Stops the $200K mistake" color={AMBER} value="⚡" desc="Something looks wrong — pattern doesn't match what it's seen before. Agent slows down, validates. A $200K database wipe doesn't happen because the agent paused." />
          <SignalPill name="Asks instead of guessing" color={PURPLE_LIGHT} value="?" desc="Agent is in genuinely new territory. It asks a targeted question rather than proceeding on a bad assumption. One question beats three correction cycles." />
          <SignalPill name="Moves fast when it should" color={CYAN} value="→" desc="Time-sensitive task. Agent knows from history that deliberating here costs more than speed. It acts — and it's right." />
          <SignalPill name="Handles routine silently" color={GREEN} value="✓" desc="Done this 100+ times. Zero issues. Agent proceeds without asking. Engineer never gets pinged. This is what autonomy actually looks like." />
          <SignalPill name="Stops the retry spiral" color={RED} value="✗" desc="Same approach has failed three times. Instead of burning another $40 in API costs retrying, agent changes strategy and tells you why." />
        </div>

        <div style={{
          marginTop: "3rem", padding: "1.25rem 1.5rem",
          background: BG, border: `1px solid ${BORDER}`, borderRadius: "0.75rem",
          display: "flex", alignItems: "center", gap: "1.5rem", flexWrap: "wrap",
        }}>
          <span style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.3)", letterSpacing: "0.08em" }}>
            Signals are dynamic. A $50K refund that triggers CAUTION on day 1 is routine on day 180
            — because the agent learned enterprise accounts process them regularly.
          </span>
        </div>
      </Slide>

      {/* ─── 04 PROOF ────────────────────────────────────────────────────────── */}
      <Slide>
        <SlideNum n="04" />
        <Label n="04 —" text="Proof of Value" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 1.5rem", maxWidth: "660px" }}>
          The CFO asks "is this worth it?"
          <span style={{ color: PURPLE }}> You show them a number, not a demo.</span>
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2rem", maxWidth: "800px" }}>
          {/* Brier score callout */}
          <div style={{
            background: `linear-gradient(135deg, ${GREEN}14, ${CYAN}0a)`,
            border: `1px solid ${GREEN}30`, borderRadius: "1rem", padding: "2rem",
          }}>
            <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: GREEN, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "0.75rem" }}>Agent Reliability Score</div>
            <div style={{ fontFamily: MONO, fontSize: "4rem", fontWeight: 700, color: GREEN, letterSpacing: "-0.02em", lineHeight: 1 }}>
              94%
            </div>
            <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: "rgba(255,255,255,0.35)", marginTop: "0.75rem" }}>
              796 correct decisions out of 847 &nbsp;·&nbsp; last 90 days
            </div>
            <div style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.45)", marginTop: "1rem", lineHeight: 1.5 }}>
              Independently auditable. The underlying calibration score (0.087 vs 0.25 baseline) uses the same math your insurance company uses to evaluate risk models. Your CISO can verify it, compare it, and bet budget on it.
            </div>
          </div>

          {/* Stats grid */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {[
              { label: "Catastrophic actions blocked", val: "25×", sub: "zero false negatives", color: GREEN },
              { label: "Engineer review sessions eliminated", val: "65%", sub: "agents handle it alone", color: CYAN },
              { label: "Token cost reduction", val: "65%", sub: "$105K saved / team / year", color: AMBER },
              { label: "Time to first autonomous task", val: "< 1 day", sub: "zero infrastructure", color: PURPLE_LIGHT },
            ].map(s => (
              <div key={s.label} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: "0.625rem", padding: "1rem 1.25rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{s.label}</div>
                  <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: s.color, opacity: 0.7, marginTop: "0.125rem" }}>{s.sub}</div>
                </div>
                <div style={{ fontFamily: MONO, fontSize: "1.375rem", fontWeight: 700, color: s.color }}>{s.val}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: "2.5rem", fontFamily: MONO, fontSize: "0.75rem", background: BG, border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.5rem", maxWidth: "800px" }}>
          <div style={{ color: GREEN, marginBottom: "0.5rem" }}>$ sentigent prove --days 90</div>
          <div style={{ color: "rgba(255,255,255,0.25)", lineHeight: 1.8 }}>
            <div>Top catches confirmed by outcome:</div>
            <div style={{ color: "rgba(255,255,255,0.5)" }}>  1. force_push_block &nbsp;&nbsp; 12× &nbsp; 100% acc &nbsp; P=0.96</div>
            <div style={{ color: "rgba(255,255,255,0.5)" }}>  2. deploy_escalation &nbsp;&nbsp; 8× &nbsp;&nbsp; 88% acc &nbsp; P=0.88</div>
            <div style={{ color: "rgba(255,255,255,0.5)" }}>  3. env_write_slow &nbsp;&nbsp;&nbsp;&nbsp; 5× &nbsp; 100% acc &nbsp; P=0.98</div>
            <div style={{ marginTop: "0.5rem" }}>Verdict: <span style={{ color: GREEN }}>PROVEN ✓</span></div>
          </div>
        </div>
      </Slide>

      {/* ─── 05 MARKET ───────────────────────────────────────────────────────── */}
      <Slide style={{ background: SURFACE }}>
        <SlideNum n="05" />
        <Label n="05 —" text="Market Opportunity" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 3rem", maxWidth: "700px" }}>
          Every AI agent in production will need a judgment layer.
          We're building the standard.
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem", maxWidth: "800px", marginBottom: "3rem" }}>
          {[
            { label: "Total AI Agent Market", val: "$52B", sub: "by 2030", color: PURPLE_LIGHT },
            { label: "Guardian Agent Segment", val: "$5–8B", sub: "by 2030 (Gartner)", color: CYAN },
            { label: "Current Market Stage", val: "NASCENT", sub: "10 companies, 3 funded", color: AMBER },
          ].map(m => (
            <div key={m.label} style={{ borderTop: `2px solid ${m.color}`, paddingTop: "1.25rem" }}>
              <div style={{ fontFamily: MONO, fontSize: "2.5rem", fontWeight: 700, color: m.color, letterSpacing: "-0.02em", lineHeight: 1 }}>{m.val}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.3)", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: "0.5rem" }}>{m.label}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: m.color, opacity: 0.7, marginTop: "0.25rem" }}>{m.sub}</div>
            </div>
          ))}
        </div>

        <Rule />

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", maxWidth: "800px" }}>
          {[
            { vertical: "Fintech", adoption: "30–50%", cycle: "30–60 days", priority: "BEACHHEAD", color: GREEN },
            { vertical: "E-Commerce", adoption: "20–30%", cycle: "45–90 days", priority: "Phase 2", color: CYAN },
            { vertical: "Enterprise Tech", adoption: "15–20%", cycle: "60–120 days", priority: "Phase 2", color: PURPLE_LIGHT },
            { vertical: "Healthcare", adoption: "10–15%", cycle: "120–180 days", priority: "Phase 3", color: AMBER },
          ].map(v => (
            <div key={v.vertical} style={{ background: BG, border: `1px solid ${v.vertical === "Fintech" ? v.color + "50" : BORDER}`, borderRadius: "0.625rem", padding: "1rem" }}>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: v.color, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.5rem" }}>{v.priority}</div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.9375rem", marginBottom: "0.75rem" }}>{v.vertical}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: "rgba(255,255,255,0.4)" }}>Agent adoption: {v.adoption}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: "rgba(255,255,255,0.4)" }}>Procurement: {v.cycle}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: "2rem", fontFamily: DISPLAY, fontSize: "0.9375rem", color: "rgba(255,255,255,0.4)", maxWidth: "600px", lineHeight: 1.6 }}>
          Driver: <strong style={{ color: "white" }}>40% of enterprise applications will have autonomous agents by end of 2026</strong> (Gartner). Every one of them needs a judgment layer.
        </div>
      </Slide>

      {/* ─── 06 COMPETITION ──────────────────────────────────────────────────── */}
      <Slide>
        <SlideNum n="06" />
        <Label n="06 —" text="Competitive Landscape" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 1.5rem", maxWidth: "660px" }}>
          No competitor has learning capability.
          <span style={{ color: GREEN }}> This is our undefended position.</span>
        </h2>
        <p style={{ fontFamily: DISPLAY, fontSize: "1rem", color: "rgba(255,255,255,0.45)", maxWidth: "520px", lineHeight: 1.6, marginBottom: "2.5rem" }}>
          Galileo's customers will be writing the same static rules in year 2 that they wrote in year 1.
          Sentigent customers won't — the agent learned. That's the switching cost.
          Galileo copies learning in 6–12 months. Layer 3 ships before that. Then the data moat is permanent.
        </p>

        <div style={{ maxWidth: "760px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr", padding: "0.75rem 1.25rem", marginBottom: "0.5rem" }}>
            {["Company", "Raised", "Learns?", "Proof?", "Network?"].map(h => (
              <span key={h} style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.25)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{h}</span>
            ))}
          </div>
          <CompRow name="Galileo" raised="$68M" learning={false} proof={false} network={false} />
          <CompRow name="Wayfound" raised="$12M" learning={false} proof={false} network={false} />
          <CompRow name="Guardrails AI" raised="$7.5M" learning={false} proof={false} network={false} />
          <CompRow name="PromptLayer" raised="—" learning={false} proof={false} network={false} />
          <CompRow name="LangSmith" raised="$35M" learning={false} proof={false} network={false} />
          <CompRow name="⬡ Sentigent" raised="Raising" learning={true} proof={true} network={true} highlight />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", maxWidth: "760px", marginTop: "2.5rem" }}>
          {[
            { title: "Gets smarter over time", desc: "Every other tool is identical on day 365 as day 1. Sentigent customers have an agent that's learned 10,000 decisions. You can't buy that.", color: GREEN },
            { title: "A number, not a demo", desc: "Competitors show dashboards. We show a reliability score your CFO can sign budget against. That's the sale.", color: PURPLE_LIGHT },
            { title: "The longer you stay, the bigger the gap", desc: "90 days of Sentigent data = a trust advantage that no competitor can replicate. Switching means starting from zero.", color: CYAN },
          ].map(a => (
            <div key={a.title} style={{ borderLeft: `2px solid ${a.color}`, paddingLeft: "1rem" }}>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.9375rem", color: a.color, marginBottom: "0.35rem" }}>{a.title}</div>
              <p style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.4)", margin: 0, lineHeight: 1.5 }}>{a.desc}</p>
            </div>
          ))}
        </div>
      </Slide>

      {/* ─── 07 BUSINESS MODEL ───────────────────────────────────────────────── */}
      <Slide style={{ background: SURFACE }}>
        <SlideNum n="07" />
        <Label n="07 —" text="Business Model" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 3rem", maxWidth: "600px" }}>
          Value is proved, not promised.
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.25rem", maxWidth: "800px", marginBottom: "3rem" }}>
          {[
            {
              name: "Starter", price: "Free", focus: "Individual dev", agents: "1 agent",
              features: ["Layer 1 local", "5 MCP tools", "30-day history", "Basic signals"],
              color: "rgba(255,255,255,0.3)", highlight: false,
            },
            {
              name: "Team", price: "$49", focus: "Engineering teams", agents: "Up to 10 agents",
              features: ["Layer 1 + 2", "27 MCP tools", "Task context layer", "Org policies", "AgentBus", "LLM Judge"],
              color: PURPLE, highlight: true,
            },
            {
              name: "Enterprise", price: "$199", focus: "Large orgs", agents: "Unlimited agents",
              features: ["All layers", "SOC 2 audit", "RBAC + SSO/SAML", "GitOps", "99.9% SLA", "Dedicated support"],
              color: CYAN, highlight: false,
            },
          ].map(tier => (
            <div key={tier.name} style={{
              background: tier.highlight ? `linear-gradient(135deg, ${PURPLE}22, ${PURPLE}0a)` : BG,
              border: `1px solid ${tier.highlight ? PURPLE + "60" : BORDER}`,
              borderRadius: "1rem", padding: "1.75rem",
              boxShadow: tier.highlight ? `0 0 32px ${PURPLE}25` : "none",
            }}>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: tier.color, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "0.75rem" }}>{tier.name}</div>
              <div style={{ fontFamily: DISPLAY, fontSize: "2.5rem", fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1, marginBottom: "0.25rem" }}>
                {tier.price}<span style={{ fontSize: "1rem", fontWeight: 400, color: "rgba(255,255,255,0.4)" }}>{tier.price !== "Free" ? "/mo" : ""}</span>
              </div>
              <div style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.4)", marginBottom: "0.25rem" }}>{tier.focus}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: tier.color, marginBottom: "1.25rem" }}>{tier.agents}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                {tier.features.map(f => (
                  <div key={f} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ color: tier.color, fontSize: "0.75rem" }}>✓</span>
                    <span style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.6)" }}>{f}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", maxWidth: "800px" }}>
          {[
            { label: "Month 3", mrr: "$1.5K", color: "rgba(255,255,255,0.4)" },
            { label: "Month 6", mrr: "$16K", color: AMBER },
            { label: "Month 12", mrr: "$74K", color: CYAN },
            { label: "2030 ARR", mrr: "$100M", color: GREEN },
          ].map(r => (
            <div key={r.label} style={{ textAlign: "center", borderTop: `1px solid ${BORDER}`, paddingTop: "1rem" }}>
              <div style={{ fontFamily: MONO, fontSize: "1.5rem", fontWeight: 700, color: r.color }}>{r.mrr}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(255,255,255,0.25)", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: "0.25rem" }}>{r.label}</div>
            </div>
          ))}
        </div>
        <p style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.3)", marginTop: "0.75rem" }}>
          Path: 1,000 enterprise customers × $100K average contract = $100M ARR
        </p>
      </Slide>

      {/* ─── 08 GTM ──────────────────────────────────────────────────────────── */}
      <Slide>
        <SlideNum n="08" />
        <Label n="08 —" text="Go-to-Market" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 3rem", maxWidth: "660px" }}>
          Developer-led growth into enterprise. Fintech as the beachhead.
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0", maxWidth: "800px", marginBottom: "3rem" }}>
          {[
            { phase: "Phase 1", period: "Mo 1–3", title: "Developer Love", actions: ["Open-source core on GitHub", "HackerNews launch", "pip install sentigent", "1,000 GitHub stars"], color: PURPLE_LIGHT },
            { phase: "Phase 2", period: "Mo 3–6", title: "First Revenue", actions: ["2–3 fintech pilots", "Layer 2 dashboard live", "Proof reports for sales", "$16K MRR target"], color: CYAN },
            { phase: "Phase 3", period: "Mo 6–12", title: "Enterprise", actions: ["Layer 3 beta", "SOC 2 Type II", "First enterprise AE", "$74K MRR target"], color: GREEN },
            { phase: "Phase 4", period: "Mo 12–24", title: "Scale", actions: ["Layer 3 GA", "Expand verticals", "\"Judgment Score\" standard", "$100M ARR path"], color: AMBER },
          ].map((p, i) => (
            <div key={p.phase} style={{
              padding: "1.5rem",
              borderLeft: i > 0 ? `1px solid ${BORDER}` : "none",
              borderTop: `2px solid ${p.color}`,
            }}>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: p.color, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.25rem" }}>{p.phase}</div>
              <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.25)", marginBottom: "0.75rem" }}>{p.period}</div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem", marginBottom: "1rem" }}>{p.title}</div>
              {p.actions.map(a => (
                <div key={a} style={{ display: "flex", alignItems: "flex-start", gap: "0.375rem", marginBottom: "0.375rem" }}>
                  <span style={{ color: p.color, fontSize: "0.625rem", marginTop: "0.125rem" }}>→</span>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(255,255,255,0.5)", lineHeight: 1.4 }}>{a}</span>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div style={{
          background: `${GREEN}0d`, border: `1px solid ${GREEN}30`,
          borderRadius: "0.75rem", padding: "1.25rem 1.5rem", maxWidth: "800px",
          display: "flex", alignItems: "center", gap: "1.5rem",
        }}>
          <span style={{ fontSize: "1.5rem" }}>💰</span>
          <div>
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: "0.9375rem", marginBottom: "0.25rem" }}>Why fintech first</div>
            <div style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.5)" }}>
              30–50% agent adoption · 30–60 day procurement · $200K+ value per prevented error · Highest compliance pressure = highest willingness to pay
            </div>
          </div>
        </div>
      </Slide>

      {/* ─── 09 MOAT ─────────────────────────────────────────────────────────── */}
      <Slide style={{ background: SURFACE }}>
        <SlideNum n="09" />
        <Label n="09 —" text="The Moat" />
        <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2rem, 4vw, 3.5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: "0 0 1.5rem", maxWidth: "660px" }}>
          First-mover compounds.{" "}
          <span style={{ color: PURPLE_LIGHT }}>An org with 90 days of data has a judgment advantage that cannot be bought.</span>
        </h2>

        <div style={{ maxWidth: "700px", marginBottom: "3rem" }}>
          {[
            { step: "1", text: "Agents declare tasks with goal + scope + constraints. Every action is judged in that context. The judgment data is yours — task-anchored, auditable, irreproducible.", color: PURPLE_LIGHT },
            { step: "2", text: "More tasks completed → better calibration per task type. So what? The signal gets sharper with every decision, automatically. Competitors start from day 0.", color: CYAN },
            { step: "3", text: "Better calibration → higher autonomy → fewer interruptions → more tasks → more data. Flywheel. No competitor can buy their way into your 10,000 completed tasks.", color: GREEN },
            { step: "4", text: "Layer 3: your patterns improve the collective intelligence. Every new customer gets smarter signal on day 1 than any competitor can offer on day 365.", color: AMBER },
          ].map((s, i) => (
            <div key={s.step} style={{ display: "flex", gap: "1.5rem", alignItems: "flex-start", marginBottom: i < 3 ? "1.5rem" : 0 }}>
              <div style={{
                width: 36, height: 36, borderRadius: "50%",
                background: `${s.color}20`, border: `1px solid ${s.color}40`,
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                fontFamily: MONO, fontSize: "0.75rem", color: s.color, fontWeight: 700,
              }}>{s.step}</div>
              <div style={{ fontFamily: DISPLAY, fontSize: "1.0625rem", color: "rgba(255,255,255,0.75)", lineHeight: 1.55, paddingTop: "0.4rem" }}>{s.text}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", maxWidth: "700px" }}>
          {[
            { label: "Day 1", desc: "Statistical baselines + org patterns from Layer 3", color: PURPLE_LIGHT },
            { label: "Day 90", desc: "0.087 Brier score. High-confidence rules. Proven ROI.", color: CYAN },
            { label: "Day 365", desc: "Network effect: your patterns inform the collective. Competitors start from zero.", color: GREEN },
          ].map(m => (
            <div key={m.label} style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.25rem" }}>
              <div style={{ fontFamily: MONO, fontSize: "1.5rem", fontWeight: 700, color: m.color, marginBottom: "0.5rem" }}>{m.label}</div>
              <p style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.45)", margin: 0, lineHeight: 1.5 }}>{m.desc}</p>
            </div>
          ))}
        </div>
      </Slide>

      {/* ─── 10 ASK ──────────────────────────────────────────────────────────── */}
      <Slide>
        <SlideNum n="10" />
        <Label n="10 —" text="The Ask" />

        <div style={{ maxWidth: "780px" }}>
          <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(2.5rem, 5vw, 5rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.04, margin: "0 0 2.5rem" }}>
            Raising{" "}
            <span style={{
              background: `linear-gradient(135deg, ${PURPLE_LIGHT}, ${CYAN})`,
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            }}>$3M seed</span>
            {" "}to ship Layer 3 and close the window before Galileo wakes up.
          </h2>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2rem", marginBottom: "3rem" }}>
            <div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: PURPLE, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.25rem" }}>Use of Funds</div>
              {[
                { item: "Engineering (4 engineers)", pct: "55%", color: PURPLE_LIGHT },
                { item: "GTM (1 enterprise AE + marketing)", pct: "25%", color: CYAN },
                { item: "Infrastructure + compliance (SOC 2)", pct: "15%", color: GREEN },
                { item: "Legal + operations", pct: "5%", color: AMBER },
              ].map(f => (
                <div key={f.item} style={{ display: "flex", justifyContent: "space-between", padding: "0.625rem 0", borderBottom: `1px solid ${BORDER}` }}>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.6)" }}>{f.item}</span>
                  <span style={{ fontFamily: MONO, fontSize: "0.875rem", color: f.color }}>{f.pct}</span>
                </div>
              ))}
            </div>

            <div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: PURPLE, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.25rem" }}>18-Month Milestones</div>
              {[
                { milestone: "Layer 3 GA + network effects live", date: "Mo 6", color: GREEN },
                { milestone: "SOC 2 Type II certified", date: "Mo 9", color: CYAN },
                { milestone: "10 enterprise customers signed", date: "Mo 12", color: PURPLE_LIGHT },
                { milestone: "$210K MRR / seed extension", date: "Mo 18", color: AMBER },
              ].map(m => (
                <div key={m.milestone} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.625rem 0", borderBottom: `1px solid ${BORDER}` }}>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(255,255,255,0.6)" }}>{m.milestone}</span>
                  <span style={{ fontFamily: MONO, fontSize: "0.75rem", color: m.color }}>{m.date}</span>
                </div>
              ))}
            </div>
          </div>

          {/* CTA */}
          <div style={{
            background: `linear-gradient(135deg, ${PURPLE}22, ${CYAN}0f)`,
            border: `1px solid ${PURPLE}40`, borderRadius: "1.25rem",
            padding: "2.5rem", textAlign: "center",
          }}>
            <div style={{ fontFamily: DISPLAY, fontSize: "1.75rem", fontWeight: 800, letterSpacing: "-0.02em", marginBottom: "0.75rem" }}>
              Layer 3 ships in 6 months. After that, the data is the moat.
            </div>
            <p style={{ fontFamily: DISPLAY, fontSize: "1rem", color: "rgba(255,255,255,0.5)", marginBottom: "2rem" }}>
              Once collective intelligence is live, every new customer makes every existing customer smarter.
              No amount of funding buys Galileo that. This is the window. Let's talk.
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: "1rem", flexWrap: "wrap" }}>
              <a href="mailto:invest@sentigent.ai" style={{
                display: "inline-flex", alignItems: "center", gap: "0.5rem",
                background: PURPLE, color: "white",
                fontFamily: MONO, fontSize: "0.8125rem",
                padding: "0.75rem 1.75rem", borderRadius: "0.5rem",
                textDecoration: "none", letterSpacing: "0.04em",
              }}>invest@sentigent.ai →</a>
              <a href="/pricing" style={{
                display: "inline-flex", alignItems: "center", gap: "0.5rem",
                background: "transparent", color: "rgba(255,255,255,0.7)",
                fontFamily: MONO, fontSize: "0.8125rem",
                padding: "0.75rem 1.75rem", borderRadius: "0.5rem",
                textDecoration: "none", border: `1px solid ${BORDER}`,
                letterSpacing: "0.04em",
              }}>View Pricing</a>
            </div>
          </div>
        </div>
      </Slide>

      {/* ─── Footer ──────────────────────────────────────────────────────────── */}
      <div style={{
        padding: "3rem clamp(1.5rem, 8vw, 9rem)",
        borderTop: `1px solid ${BORDER}`,
        display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <div style={{
            width: 24, height: 24, borderRadius: "0.3rem",
            background: `linear-gradient(135deg, ${PURPLE}, #a855f7)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "0.625rem", fontWeight: 700, color: "white",
          }}>S</div>
          <span style={{ fontFamily: DISPLAY, fontWeight: 700, color: "rgba(255,255,255,0.6)" }}>Sentigent</span>
        </div>
        <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.2)" }}>
          Confidential — For authorized recipients only — February 2026
        </div>
        <div style={{ display: "flex", gap: "1.5rem" }}>
          {["Pricing", "Docs", "Press"].map(l => (
            <a key={l} href={`/${l.toLowerCase()}`} style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(255,255,255,0.3)", textDecoration: "none" }}>{l}</a>
          ))}
        </div>
      </div>
    </div>
  );
}
