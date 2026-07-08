import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, Zap, ArrowRight, Loader2, Bot, Brain, Globe } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

// Slugify org name → slug
function toSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 32);
}

export function Signup() {
  const navigate = useNavigate();
  const { signUp } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleOrgNameChange(val: string) {
    setOrgName(val);
    setOrgSlug(toSlug(val));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (!orgSlug) {
      setError("Org name is required");
      return;
    }
    setLoading(true);
    const { error } = await signUp(email, password, orgName.trim(), orgSlug);
    setLoading(false);
    if (error) {
      setError(error);
    } else {
      navigate("/onboarding", { replace: true });
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-bg-base px-4 py-8"
      style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(124,58,237,0.08) 0%, transparent 60%), #07090f" }}
    >
      {/* Ambient glow */}
      <div
        className="absolute top-1/4 left-1/2 -translate-x-1/2 w-96 h-96 rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(124,58,237,0.06) 0%, transparent 70%)" }}
      />

      <div className="w-full max-w-md relative z-10">

        {/* Brand */}
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="w-10 h-10 rounded-xl bg-gradient-accent flex items-center justify-center shadow-glow">
            <Activity size={18} className="text-white" />
          </div>
          <div>
            <div className="text-lg font-bold text-white tracking-tight">Sentigent</div>
            <div className="text-[10px] text-muted/70 flex items-center gap-1">
              <Zap size={8} className="text-accent-light" /> AI Judgment Layer
            </div>
          </div>
        </div>

        {/* Value props */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          {[
            { icon: <Bot size={14} />, label: "Agent Learning", sub: "Layer 1" },
            { icon: <Brain size={14} />, label: "Org Intelligence", sub: "Layer 2" },
            { icon: <Globe size={14} />, label: "Collective", sub: "Layer 3" },
          ].map(({ icon, label, sub }) => (
            <div key={label}
              className="rounded-xl border border-bg-border/60 p-3 text-center"
              style={{ background: "rgba(124,58,237,0.05)" }}>
              <div className="flex justify-center mb-1 text-accent-light">{icon}</div>
              <div className="text-[11px] font-semibold text-white/90">{label}</div>
              <div className="text-[10px] text-muted/50">{sub}</div>
            </div>
          ))}
        </div>

        {/* Card */}
        <div
          className="rounded-2xl border border-bg-border/80 overflow-hidden"
          style={{ background: "linear-gradient(135deg, #0d1321 0%, #0a0f1a 100%)" }}
        >
          <div className="px-6 pt-6 pb-2">
            <h1 className="text-xl font-bold text-white">Create your org</h1>
            <p className="text-sm text-muted/70 mt-1">
              Your agents will start learning from day one
            </p>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted/80 uppercase tracking-wider">
                Organization name
              </label>
              <input
                type="text"
                value={orgName}
                onChange={e => handleOrgNameChange(e.target.value)}
                required
                autoFocus
                placeholder="Acme Corp"
                className="input w-full"
              />
              {orgSlug && (
                <p className="text-[11px] text-muted/50 pl-1">
                  slug: <span className="text-accent-light font-mono">{orgSlug}</span>
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted/80 uppercase tracking-wider">
                Work email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                placeholder="you@company.com"
                className="input w-full"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted/80 uppercase tracking-wider">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                placeholder="Min 8 characters"
                className="input w-full"
              />
            </div>

            {error && (
              <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2">
                <p className="text-xs text-danger">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary w-full flex items-center justify-center gap-2"
            >
              {loading ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <>
                  Create org & continue
                  <ArrowRight size={14} />
                </>
              )}
            </button>
          </form>

          <div className="px-6 pb-5 text-center">
            <p className="text-xs text-muted/60">
              Already have an account?{" "}
              <Link to="/auth/login" className="text-accent-light hover:text-accent-bright transition-colors">
                Sign in
              </Link>
            </p>
          </div>
        </div>

        <p className="text-center text-[11px] text-muted/40 mt-5">
          Free plan · No credit card required · Connect your agent in 2 minutes
        </p>
      </div>
    </div>
  );
}
