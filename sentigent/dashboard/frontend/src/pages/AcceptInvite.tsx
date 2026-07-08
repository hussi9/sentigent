import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Activity, CheckCircle, XCircle, Loader2, Zap } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export function AcceptInvite() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { user, acceptInvite } = useAuth();

  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Invalid invite link");
      return;
    }
    if (!user) {
      // Not logged in — send to signup, come back after
      navigate(`/auth/signup?invite=${token}`, { replace: true });
      return;
    }

    acceptInvite(token).then(({ error }) => {
      if (error) {
        setStatus("error");
        setMessage(error);
      } else {
        setStatus("success");
        setTimeout(() => navigate("/dashboard", { replace: true }), 2000);
      }
    });
  }, [token, user, acceptInvite, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-base px-4"
      style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(124,58,237,0.08) 0%, transparent 60%), #07090f" }}>

      <div className="w-full max-w-sm text-center">
        <div className="flex justify-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-gradient-accent flex items-center justify-center shadow-glow">
            <Activity size={20} className="text-white" />
          </div>
        </div>

        <div className="rounded-2xl border border-bg-border/80 p-8"
          style={{ background: "linear-gradient(135deg, #0d1321 0%, #0a0f1a 100%)" }}>

          {status === "pending" && (
            <>
              <Loader2 size={32} className="animate-spin text-accent-light mx-auto mb-4" />
              <p className="text-white font-semibold">Joining your org…</p>
            </>
          )}
          {status === "success" && (
            <>
              <CheckCircle size={32} className="text-success mx-auto mb-4" />
              <p className="text-white font-semibold mb-1">Welcome to the team!</p>
              <p className="text-sm text-muted/60">Redirecting to your dashboard…</p>
            </>
          )}
          {status === "error" && (
            <>
              <XCircle size={32} className="text-danger mx-auto mb-4" />
              <p className="text-white font-semibold mb-1">Invite failed</p>
              <p className="text-sm text-danger/80">{message}</p>
              <button
                onClick={() => navigate("/auth/login")}
                className="btn btn-primary mt-4 w-full"
              >
                Go to login
              </button>
            </>
          )}
        </div>

        <p className="text-[11px] text-muted/40 mt-5 flex items-center justify-center gap-1">
          <Zap size={8} className="text-accent-light" />
          Sentigent AI Judgment Layer
        </p>
      </div>
    </div>
  );
}
