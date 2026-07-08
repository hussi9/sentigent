import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Layout } from "@/components/layout/Layout";
import { Dashboard } from "@/pages/Dashboard";
import { AgentExplorer } from "@/pages/AgentExplorer";
import { PolicyManager } from "@/pages/PolicyManager";
import { Practices } from "@/pages/Practices";
import { Escalations } from "@/pages/Escalations";
import { Routing } from "@/pages/Routing";
import { PromptBuilder } from "@/pages/PromptBuilder";
import { CollectiveIntelligence } from "@/pages/CollectiveIntelligence";
import { ProofOfValue } from "@/pages/ProofOfValue";
import { Onboarding } from "@/pages/Onboarding";
import { OrgSettings } from "@/pages/OrgSettings";
import { MembersSettings } from "@/pages/MembersSettings";
import { MyAgent } from "@/pages/MyAgent";
import { AdminLayer1 } from "@/pages/AdminLayer1";
import { Intelligence } from "@/pages/Intelligence";
import { Help } from "@/pages/Help";
import { Login } from "@/pages/Login";
import { Signup } from "@/pages/Signup";
import { AcceptInvite } from "@/pages/AcceptInvite";
import { Landing } from "@/pages/Landing";
import { Pricing } from "@/pages/Pricing";
import { InvestorPitch } from "@/pages/InvestorPitch";
import { PressKit } from "@/pages/PressKit";
import { OrgKnowledge } from "@/pages/OrgKnowledge";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// ── Auth gate ─────────────────────────────────────────────────────────────
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-base">
        <div className="w-8 h-8 rounded-full border-2 border-accent/30 border-t-accent animate-spin" />
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/auth/login" state={{ from: location.pathname }} replace />;
  }

  return <>{children}</>;
}

// ── Protected app shell (reads org from auth) ─────────────────────────────
function AppShell() {
  const { membership } = useAuth();
  const orgId = membership?.org_slug || (import.meta.env.VITE_ORG_ID as string) || "hussi";

  return (
    <RequireAuth>
      <Layout orgId={orgId}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/agents" element={<AgentExplorer />} />
          <Route path="/policies" element={<PolicyManager />} />
          <Route path="/practices" element={<Practices />} />
          <Route path="/escalations" element={<Escalations />} />
          <Route path="/routing" element={<Routing />} />
          <Route path="/prompt-builder" element={<PromptBuilder />} />
          <Route path="/collective" element={<CollectiveIntelligence />} />
          <Route path="/proof" element={<ProofOfValue />} />
          <Route path="/my-agent" element={<MyAgent />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/help" element={<Help />} />
          <Route path="/admin/layer1" element={<AdminLayer1 />} />
          <Route path="/settings/org" element={<OrgSettings />} />
          <Route path="/settings/members" element={<MembersSettings />} />
          <Route path="/org-knowledge" element={<OrgKnowledge />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Layout>
    </RequireAuth>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/auth/login" element={<Login />} />
            <Route path="/auth/signup" element={<Signup />} />
            <Route path="/auth/invite/:token" element={<AcceptInvite />} />
            <Route path="/" element={<Landing />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/pitch" element={<InvestorPitch />} />
            <Route path="/press" element={<PressKit />} />
            <Route path="/*" element={<AppShell />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
