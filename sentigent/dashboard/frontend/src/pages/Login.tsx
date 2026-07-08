import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Activity, Zap, ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { signIn } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const from = (location.state as { from?: string })?.from ?? "/dashboard";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await signIn(email, password);
    setLoading(false);
    if (error) {
      setError(error);
    } else {
      navigate(from, { replace: true });
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-base px-4"
      style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(124,58,237,0.08) 0%, transparent 60%), #07090f" }}>

      {/* Ambient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-96 h-96 rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(124,58,237,0.06) 0%, transparent 70%)" }} />

      <div className="w-full max-w-sm relative z-10">

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

        {/* Card */}
        <div className="rounded-2xl border border-bg-border/80 overflow-hidden"
          style={{ background: "linear-gradient(135deg, #0d1321 0%, #0a0f1a 100%)" }}>

          <div className="px-6 pt-6 pb-2">
            <h1 className="text-xl font-bold text-white">Sign in</h1>
            <p className="text-sm text-muted/70 mt-1">
              Connect to your agent's judgment dashboard
            </p>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted/80 uppercase tracking-wider">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
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
                placeholder="••••••••"
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
                  Sign in
                  <ArrowRight size={14} />
                </>
              )}
            </button>
          </form>

          <div className="px-6 pb-5 text-center">
            <p className="text-xs text-muted/60">
              No account?{" "}
              <Link to="/auth/signup" className="text-accent-light hover:text-accent-bright transition-colors">
                Create your org
              </Link>
            </p>
          </div>
        </div>

        <p className="text-center text-[11px] text-muted/40 mt-5">
          Sentigent learns from every agent decision to make the next one better.
        </p>
      </div>
    </div>
  );
}
