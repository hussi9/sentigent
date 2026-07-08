import { useState } from "react";

// ── Design tokens ──────────────────────────────────────────────────────────────
const BG = "#FAFAF8";
const DARK = "#0A0A0A";
const SURFACE = "#F3F3F0";
const BORDER = "rgba(0,0,0,0.08)";
const PURPLE = "#7c3aed";
const CYAN = "#0891b2";
const GREEN = "#059669";
const AMBER = "#d97706";
const DISPLAY = "'Bricolage Grotesque', sans-serif";
const MONO = "'JetBrains Mono', monospace";

// ── Stat callout ──────────────────────────────────────────────────────────────
function Stat({ value, label, sub, color = DARK }: { value: string; label: string; sub?: string; color?: string }) {
  return (
    <div style={{ borderTop: `2px solid ${color === DARK ? "rgba(0,0,0,0.12)" : color}`, paddingTop: "1.25rem" }}>
      <div style={{ fontFamily: MONO, fontSize: "2.25rem", fontWeight: 700, color, letterSpacing: "-0.02em", lineHeight: 1 }}>{value}</div>
      <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.4)", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: "0.4rem" }}>{label}</div>
      {sub && <div style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(0,0,0,0.4)", marginTop: "0.25rem" }}>{sub}</div>}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHead({ label, title }: { label: string; title: string }) {
  return (
    <div style={{ marginBottom: "3rem" }}>
      <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: PURPLE, letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: "0.75rem" }}>{label}</div>
      <h2 style={{ fontFamily: DISPLAY, fontSize: "clamp(1.75rem, 3.5vw, 2.75rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08, margin: 0, color: DARK }}>
        {title}
      </h2>
    </div>
  );
}

// ── Copy block ────────────────────────────────────────────────────────────────
function CopyBlock({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div style={{ border: `1px solid ${BORDER}`, borderRadius: "0.75rem", overflow: "hidden", marginBottom: "1rem" }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "0.625rem 1rem", background: SURFACE, borderBottom: `1px solid ${BORDER}`,
      }}>
        <span style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.4)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{label}</span>
        <button onClick={copy} style={{
          border: "none", cursor: "pointer",
          fontFamily: MONO, fontSize: "0.5625rem", color: copied ? GREEN : PURPLE,
          letterSpacing: "0.08em", textTransform: "uppercase", padding: "0.25rem 0.5rem",
          borderRadius: "0.25rem", background: copied ? `${GREEN}10` : `${PURPLE}10`,
        }}>
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
      <div style={{ padding: "1.25rem", background: "#fff" }}>
        <p style={{ fontFamily: DISPLAY, fontSize: "0.9375rem", color: DARK, lineHeight: 1.7, margin: 0 }}>{text}</p>
      </div>
    </div>
  );
}

// ── Color swatch ──────────────────────────────────────────────────────────────
function Swatch({ hex, name, role }: { hex: string; name: string; role: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      onClick={() => { navigator.clipboard.writeText(hex); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      style={{ cursor: "pointer" }}
    >
      <div style={{
        height: 80, borderRadius: "0.5rem", background: hex,
        marginBottom: "0.625rem", border: `1px solid rgba(0,0,0,0.06)`,
        transition: "transform 0.2s",
      }} />
      <div style={{ fontFamily: MONO, fontSize: "0.75rem", color: DARK, fontWeight: 600 }}>{copied ? "Copied!" : hex}</div>
      <div style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(0,0,0,0.6)" }}>{name}</div>
      <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: "0.15rem" }}>{role}</div>
    </div>
  );
}

// ── Logo mark ─────────────────────────────────────────────────────────────────
function LogoMark({ size = 48, dark: _dark = false }: { size?: number; dark?: boolean }) {
  const gradStart = "#7c3aed";
  const gradEnd = "#a855f7";
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.2,
      background: `linear-gradient(135deg, ${gradStart}, ${gradEnd})`,
      display: "flex", alignItems: "center", justifyContent: "center",
      flexShrink: 0,
    }}>
      <span style={{
        fontFamily: DISPLAY, fontWeight: 800,
        fontSize: size * 0.42,
        color: "white",
        letterSpacing: "-0.04em",
      }}>S</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function PressKit() {
  return (
    <div style={{ background: BG, color: DARK, minHeight: "100vh", fontFamily: DISPLAY }}>

      {/* ─── Navigation ──────────────────────────────────────────────────────── */}
      <nav style={{
        padding: "1.25rem clamp(1.5rem, 6vw, 5rem)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        borderBottom: `1px solid ${BORDER}`,
        background: "rgba(250,250,248,0.95)", backdropFilter: "blur(8px)",
        position: "sticky", top: 0, zIndex: 50,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <LogoMark size={32} />
          <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem", color: DARK }}>Sentigent</span>
        </div>
        <div style={{ display: "flex", gap: "1.5rem", alignItems: "center" }}>
          {["Overview", "Assets", "Contact"].map(l => (
            <a key={l} href={`#${l.toLowerCase()}`} style={{ fontFamily: MONO, fontSize: "0.75rem", color: "rgba(0,0,0,0.45)", textDecoration: "none", letterSpacing: "0.04em" }}>{l}</a>
          ))}
          <a href="/pitch" style={{
            fontFamily: MONO, fontSize: "0.75rem", color: PURPLE,
            textDecoration: "none", letterSpacing: "0.04em",
            background: `${PURPLE}12`, padding: "0.375rem 0.875rem",
            borderRadius: "0.375rem", border: `1px solid ${PURPLE}30`,
          }}>Investor Deck →</a>
        </div>
      </nav>

      {/* ─── Hero ─────────────────────────────────────────────────────────────── */}
      <div style={{
        padding: "6rem clamp(1.5rem, 6vw, 5rem) 4rem",
        maxWidth: "1200px", margin: "0 auto",
        borderBottom: `1px solid ${BORDER}`,
      }}>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: "0.5rem",
          background: `${PURPLE}0f`, border: `1px solid ${PURPLE}25`,
          borderRadius: "9999px", padding: "0.3rem 0.875rem",
          marginBottom: "2rem",
        }}>
          <span style={{ fontFamily: MONO, fontSize: "0.5625rem", color: PURPLE, letterSpacing: "0.12em", textTransform: "uppercase" }}>Press & Media Kit</span>
        </div>

        <h1 style={{
          fontFamily: DISPLAY, fontSize: "clamp(3rem, 6vw, 5.5rem)",
          fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.02,
          margin: "0 0 1.5rem", maxWidth: "900px", color: DARK,
        }}>
          The judgment layer for AI agents.
        </h1>
        <p style={{
          fontFamily: DISPLAY, fontSize: "clamp(1.0625rem, 1.75vw, 1.3125rem)",
          color: "rgba(0,0,0,0.5)", lineHeight: 1.65,
          maxWidth: "620px", margin: "0 0 3rem",
        }}>
          Sentigent makes AI agents safe enough to trust with real work —
          by giving them judgment built from experience, and proving it quantitatively.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "2rem", maxWidth: "720px" }}>
          <Stat value="0.087" label="Brier Score" sub="vs 0.25 random baseline" color={GREEN} />
          <Stat value="94%" label="Judgment Accuracy" sub="90-day rolling window" color={PURPLE} />
          <Stat value="65%" label="Token Reduction" sub="avg clarification cycles" color={CYAN} />
          <Stat value="$105K" label="Annual Savings" sub="per enterprise team" color={AMBER} />
        </div>
      </div>

      <div id="overview" style={{ maxWidth: "1200px", margin: "0 auto", padding: "0 clamp(1.5rem, 6vw, 5rem)" }}>

        {/* ─── Company overview ─────────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: "5rem", alignItems: "start" }}>
            <div>
              <SectionHead label="About" title="Company Overview" />
              <p style={{ fontSize: "1rem", color: "rgba(0,0,0,0.55)", lineHeight: 1.75, marginBottom: "1.5rem" }}>
                Sentigent is an AI agent governance platform that makes autonomous AI agents safe
                enough to deploy with real authority. Unlike static guardrail systems, Sentigent
                learns from every decision and outcome, proving its accuracy with a mathematically
                rigorous Brier score — the same calibration metric used in weather forecasting.
              </p>
              <p style={{ fontSize: "1rem", color: "rgba(0,0,0,0.55)", lineHeight: 1.75 }}>
                Founded in 2025, Sentigent is building the judgment layer that will become as
                standard in AI infrastructure as a rate limiter or circuit breaker.
              </p>
            </div>
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                {[
                  { label: "Founded", val: "2025" },
                  { label: "Stage", val: "Pre-Seed" },
                  { label: "HQ", val: "San Francisco, CA" },
                  { label: "Employees", val: "3" },
                  { label: "Market", val: "$5–8B by 2030" },
                  { label: "Beachhead", val: "Fintech / Enterprise" },
                ].map(item => (
                  <div key={item.label} style={{ padding: "1rem", background: SURFACE, borderRadius: "0.5rem" }}>
                    <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.25rem" }}>{item.label}</div>
                    <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem" }}>{item.val}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ─── Founding story ───────────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: "5rem", alignItems: "start" }}>
            <SectionHead label="Origin" title="The Founding Story" />
            <div>
              <p style={{ fontSize: "1.0625rem", color: "rgba(0,0,0,0.65)", lineHeight: 1.8, marginBottom: "1.25rem" }}>
                The idea for Sentigent emerged from a simple observation: every enterprise team using AI agents wanted to give them more authority, but nobody could prove the judgment was reliable enough to trust.
              </p>
              <p style={{ fontSize: "1.0625rem", color: "rgba(0,0,0,0.65)", lineHeight: 1.8, marginBottom: "1.25rem" }}>
                The tools that existed — static guardrails, blocklists, compliance theater — all shared the same fatal flaw: they didn't learn. They went stale. And they couldn't prove they were working.
              </p>
              <p style={{ fontSize: "1.0625rem", color: "rgba(0,0,0,0.65)", lineHeight: 1.8 }}>
                Sentigent was built on one insight: if you can measure judgment calibration with a Brier score, you can prove value in the same way a weather forecasting system proves accuracy. Numbers, not dashboards. Proof, not promises.
              </p>
            </div>
          </div>
        </div>

        {/* ─── Product description ──────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <SectionHead label="Product" title="What Sentigent Does" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem", marginBottom: "3rem" }}>
            {[
              {
                icon: "⬡", title: "Layer 1: Action Judgment",
                desc: "Watches every AI agent tool call. Evaluates risk using five dynamic signals. Learns from outcomes. Proves accuracy with Brier score.",
                tag: "Built", color: GREEN,
              },
              {
                icon: "⬡⬡", title: "Layer 2: Org Intelligence",
                desc: "Shares learned patterns across all agents in an organization. Org-wide baselines, policies, and proof of value reporting.",
                tag: "Built", color: CYAN,
              },
              {
                icon: "⬡⬡⬡", title: "Layer 3: Collective Memory",
                desc: "Cross-org pattern sharing with differential privacy. Network-effect moat: every new org starts smarter than the last.",
                tag: "Early Stage", color: PURPLE,
              },
            ].map(l => (
              <div key={l.title} style={{ border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.75rem" }}>
                <div style={{ fontFamily: MONO, fontSize: "1.25rem", color: l.color, marginBottom: "0.75rem" }}>{l.icon}</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                  <h3 style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "1rem", margin: 0, color: DARK }}>{l.title}</h3>
                  <span style={{ fontFamily: MONO, fontSize: "0.5625rem", color: l.color, background: `${l.color}12`, padding: "0.15rem 0.5rem", borderRadius: "9999px", marginLeft: "0.5rem", flexShrink: 0 }}>{l.tag}</span>
                </div>
                <p style={{ fontSize: "0.875rem", color: "rgba(0,0,0,0.5)", lineHeight: 1.65, margin: 0 }}>{l.desc}</p>
              </div>
            ))}
          </div>

          {/* Five signals */}
          <div style={{ background: SURFACE, borderRadius: "1rem", padding: "2.5rem" }}>
            <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.5rem" }}>The Five Judgment Signals</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "1rem" }}>
              {[
                { name: "Caution", desc: "Context deviates from baselines", color: AMBER },
                { name: "Doubt", desc: "Pattern match strength is low", color: PURPLE },
                { name: "Urgency", desc: "Time-sensitive context", color: CYAN },
                { name: "Confidence", desc: "Routine — fast-path proceed", color: GREEN },
                { name: "Frustration", desc: "Repeated failure loop", color: "#dc2626" },
              ].map(s => (
                <div key={s.name} style={{ borderTop: `2px solid ${s.color}`, paddingTop: "0.75rem" }}>
                  <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.875rem", color: DARK, marginBottom: "0.25rem" }}>{s.name}</div>
                  <div style={{ fontFamily: DISPLAY, fontSize: "0.75rem", color: "rgba(0,0,0,0.45)", lineHeight: 1.4 }}>{s.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Quotes ───────────────────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <SectionHead label="Key Quotes" title="What They're Saying" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
            {[
              {
                quote: "The only tool with calibrated proof. Brier score is a specific, reproducible number — not a dashboard metric.",
                author: "Sentigent Proof Engine", role: "sentigent prove --days 90",
                color: GREEN,
              },
              {
                quote: "Enterprise conversation intelligence products generate $1B+ in value by making human-to-human conversations more productive. Sentigent does the same for human-AI sessions.",
                author: "Market Research 2026", role: "Human-Agent Intelligence Report",
                color: PURPLE,
              },
              {
                quote: "The bottleneck in AI coding productivity is not model intelligence — it is conversation quality. The next frontier is not model quality but human-agent interaction quality.",
                author: "A16Z Future of Developer Tools", role: "2024",
                color: CYAN,
              },
              {
                quote: "First-mover compounds. An org with 90 days of Sentigent data has a judgment advantage that cannot be bought.",
                author: "Sentigent Vision", role: "docs/PRODUCT_VISION.md",
                color: AMBER,
              },
            ].map(q => (
              <div key={q.quote} style={{
                border: `1px solid ${BORDER}`, borderRadius: "0.75rem",
                padding: "1.75rem", position: "relative",
              }}>
                <div style={{ fontFamily: DISPLAY, fontSize: "2rem", color: q.color, lineHeight: 1, marginBottom: "0.5rem", opacity: 0.4 }}>"</div>
                <p style={{ fontFamily: DISPLAY, fontSize: "0.9375rem", color: DARK, lineHeight: 1.65, margin: "0 0 1.25rem", fontStyle: "italic" }}>
                  {q.quote}
                </p>
                <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: "0.875rem" }}>
                  <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.875rem", color: DARK }}>{q.author}</div>
                  <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.08em", marginTop: "0.15rem" }}>{q.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ─── Boilerplate ──────────────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <SectionHead label="Press Copy" title="Boilerplate Descriptions" />
          <CopyBlock
            label="One sentence (for headlines)"
            text="Sentigent is the judgment layer that lets enterprises give AI agents real authority — because it proves they've earned it, and pays for itself in saved tokens."
          />
          <CopyBlock
            label="Short (75 words — for press releases)"
            text="Sentigent is an AI agent governance platform that makes autonomous agents safe enough to deploy with real authority. Unlike static guardrail systems, Sentigent learns from every decision and outcome, continuously improving its calibration. Its Brier score metric — the same tool used in weather forecasting — provides reproducible, CFO-ready proof of value. Founded in 2025, Sentigent targets the $5–8B Guardian Agent market with a three-tier platform starting free for individual developers."
          />
          <CopyBlock
            label="Long (150 words — for feature articles)"
            text="Sentigent is building the judgment layer that makes AI agents safe enough to trust with real work. Every AI deployment hits the same wall: engineering leaders want autonomous agents, but nobody can prove the judgment is reliable. Sentigent solves this with a self-learning three-layer architecture — a local per-agent memory layer, an org-wide intelligence layer, and a cross-org collective intelligence network with differential privacy — that watches every agent action, records outcomes, and learns continuously from experience. The platform evaluates five dynamic signals (caution, doubt, urgency, confidence, frustration) in under 10ms, routes ambiguous decisions to an LLM judge, and enforces org-level policies before any action executes. Its proof-of-value command generates a CFO-ready report with a Brier score: 0.087 (compared to 0.25 for random and 0.0 for perfect). Beyond action judgment, Sentigent also reduces token costs by coaching humans to interact with agents more effectively, reducing clarification cycles from 3.2 to 1.1 per task — approximately $105,000 in annual savings per enterprise team."
          />
        </div>

        {/* ─── Brand assets ─────────────────────────────────────────────────── */}
        <div id="assets" style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <SectionHead label="Brand" title="Brand Assets" />

          {/* Logos */}
          <div style={{ marginBottom: "4rem" }}>
            <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.5rem" }}>Logo Mark</div>
            <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
              {[
                { bg: "#fff", border: true, label: "On White" },
                { bg: "#F3F3F0", border: true, label: "On Light" },
                { bg: "#030712", border: false, label: "On Dark" },
                { bg: "#7c3aed", border: false, label: "On Purple" },
              ].map(variant => (
                <div key={variant.label} style={{ textAlign: "center" }}>
                  <div style={{
                    width: 120, height: 120, borderRadius: "1rem",
                    background: variant.bg,
                    border: variant.border ? `1px solid ${BORDER}` : "none",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    marginBottom: "0.5rem",
                  }}>
                    <LogoMark size={56} dark={variant.bg === "#030712" || variant.bg === "#7c3aed"} />
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.08em" }}>{variant.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Typography */}
          <div style={{ marginBottom: "4rem" }}>
            <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.5rem" }}>Typography</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem" }}>
              {[
                { family: "Bricolage Grotesque", role: "Display", sample: "Judgment that compounds.", weight: "300–800", note: "All headlines, hero text, marketing copy" },
                { family: "Inter", role: "UI / Body", sample: "Safe. Proven. Autonomous.", weight: "300–700", note: "Dashboard, body text, navigation" },
                { family: "JetBrains Mono", role: "Code / Data", sample: "Brier: 0.087", weight: "400–500", note: "Terminal output, metrics, code" },
              ].map(t => (
                <div key={t.family} style={{ border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.5rem" }}>
                  <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: PURPLE, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.5rem" }}>{t.role}</div>
                  <div style={{ fontFamily: t.family, fontSize: "1.375rem", fontWeight: 700, color: DARK, marginBottom: "0.375rem", letterSpacing: "-0.02em" }}>{t.sample}</div>
                  <div style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(0,0,0,0.4)", marginBottom: "0.5rem" }}>{t.family} · {t.weight}</div>
                  <div style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(0,0,0,0.4)" }}>{t.note}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Color palette */}
          <div>
            <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.5rem" }}>Color Palette</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: "1.25rem", marginBottom: "2rem" }}>
              <Swatch hex="#7c3aed" name="Sentigent Purple" role="Primary" />
              <Swatch hex="#a78bfa" name="Purple Light" role="Accent" />
              <Swatch hex="#06b6d4" name="Cyber Cyan" role="Action" />
              <Swatch hex="#10b981" name="Proof Green" role="Success" />
              <Swatch hex="#f59e0b" name="Signal Amber" role="Warning" />
              <Swatch hex="#ef4444" name="Danger Red" role="Alert" />
              <Swatch hex="#030712" name="Deep Black" role="Background" />
              <Swatch hex="#0d1117" name="Surface Dark" role="Card" />
            </div>
            <p style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(0,0,0,0.4)" }}>
              Click any swatch to copy the hex code. All colors are accessible at WCAG AA contrast on dark backgrounds.
            </p>
          </div>
        </div>

        {/* ─── Key facts ────────────────────────────────────────────────────── */}
        <div style={{ padding: "5rem 0", borderBottom: `1px solid ${BORDER}` }}>
          <SectionHead label="Quick Reference" title="Key Facts & Figures" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3rem" }}>
            <div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.25rem" }}>Product</div>
              {[
                ["Architecture", "Three-layer: Local SQLite → Supabase → Collective"],
                ["Signals", "5 dynamic signals computed in <10ms, no model training"],
                ["Proof metric", "Brier score (0.087 vs 0.25 random)"],
                ["MCP tools", "25 tools exposed to Claude Code"],
                ["Decision actions", "proceed / slow_down / enrich / escalate"],
                ["Learning method", "Pure statistics — fully auditable"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "0.75rem 0", borderBottom: `1px solid ${BORDER}`, gap: "1rem" }}>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(0,0,0,0.5)", flexShrink: 0 }}>{k}</span>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: DARK, textAlign: "right" }}>{v}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "1.25rem" }}>Market & Competition</div>
              {[
                ["Market size", "$5–8B Guardian Agent market by 2030"],
                ["Total market", "$52B AI agent market by 2030"],
                ["Key competitor", "Galileo ($68M raised, no learning)"],
                ["Differentiator", "Only tool with calibrated proof + learning"],
                ["Beachhead", "Fintech (30–50% agent adoption)"],
                ["Timeline risk", "6–12 months before competition catches up"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "0.75rem 0", borderBottom: `1px solid ${BORDER}`, gap: "1rem" }}>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: "rgba(0,0,0,0.5)", flexShrink: 0 }}>{k}</span>
                  <span style={{ fontFamily: DISPLAY, fontSize: "0.875rem", color: DARK, textAlign: "right" }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Contact ──────────────────────────────────────────────────────── */}
        <div id="contact" style={{ padding: "5rem 0" }}>
          <SectionHead label="Contact" title="Get in Touch" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem", maxWidth: "700px" }}>
            {[
              { type: "Press Inquiries", email: "press@sentigent.ai", desc: "Interview requests, media coverage, product briefings", color: PURPLE },
              { type: "Investor Relations", email: "invest@sentigent.ai", desc: "Pitch deck, financials, partnership discussions", color: CYAN },
              { type: "General", email: "hello@sentigent.ai", desc: "Product questions, partnership, everything else", color: GREEN },
            ].map(c => (
              <div key={c.type} style={{ border: `1px solid ${BORDER}`, borderRadius: "0.75rem", padding: "1.5rem" }}>
                <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: c.color, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "0.75rem" }}>{c.type}</div>
                <a href={`mailto:${c.email}`} style={{
                  display: "block", fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.9375rem",
                  color: DARK, textDecoration: "none", marginBottom: "0.5rem",
                  borderBottom: `1px solid ${c.color}`, paddingBottom: "0.5rem",
                }}>{c.email}</a>
                <p style={{ fontFamily: DISPLAY, fontSize: "0.8125rem", color: "rgba(0,0,0,0.45)", margin: 0, lineHeight: 1.5 }}>{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Footer ────────────────────────────────────────────────────────── */}
      <div style={{
        borderTop: `1px solid ${BORDER}`,
        padding: "2rem clamp(1.5rem, 6vw, 5rem)",
        display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.625rem" }}>
          <LogoMark size={24} />
          <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: "0.9375rem", color: DARK }}>Sentigent</span>
        </div>
        <div style={{ fontFamily: MONO, fontSize: "0.5625rem", color: "rgba(0,0,0,0.3)", letterSpacing: "0.08em" }}>
          © 2026 Sentigent — Press kit updated February 2026
        </div>
        <div style={{ display: "flex", gap: "1.5rem" }}>
          {[["Pitch Deck", "/pitch"], ["Pricing", "/pricing"], ["Docs", "/docs"]].map(([l, h]) => (
            <a key={l} href={h} style={{ fontFamily: MONO, fontSize: "0.6875rem", color: "rgba(0,0,0,0.35)", textDecoration: "none" }}>{l}</a>
          ))}
        </div>
      </div>
    </div>
  );
}
