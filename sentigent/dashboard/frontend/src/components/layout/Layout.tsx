import { useState, useCallback, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import type { NavPage, LiveDecision } from "@/types";
import { subscribeToDecisions } from "@/api/client";

// Map URL path → NavPage id
function pathToPage(pathname: string): NavPage {
  const clean = pathname.replace(/^\//, "");
  if (clean.startsWith("settings/")) {
    const sub = clean as NavPage;
    const validSettings: NavPage[] = ["settings/org", "settings/members"];
    return validSettings.includes(sub) ? sub : "dashboard";
  }
  if (clean.startsWith("admin/")) {
    const sub = clean as NavPage;
    const validAdmin: NavPage[] = ["admin/layer1"];
    return validAdmin.includes(sub) ? sub : "dashboard";
  }
  const segment = clean.split("/")[0] as NavPage;
  const valid: NavPage[] = [
    "dashboard", "agents", "policies", "practices", "escalations", "routing", "prompt-builder",
    "collective", "proof", "onboarding", "my-agent", "intelligence", "help",
    "org-knowledge",
  ];
  return valid.includes(segment) ? segment : "dashboard";
}

interface Props {
  children: React.ReactNode;
  orgId: string;
}

export function Layout({ children, orgId }: Props) {
  const location = useLocation();
  const qc = useQueryClient();
  const [isRefreshing, setRefreshing] = useState(false);
  const [liveDecisions, setLiveDecisions] = useState<LiveDecision[]>([]);

  const page = pathToPage(location.pathname);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await qc.invalidateQueries();
    setTimeout(() => setRefreshing(false), 800);
  }, [qc]);

  useEffect(() => {
    const unsub = subscribeToDecisions(
      (d) => {
        setLiveDecisions((prev) => [d, ...prev].slice(0, 50));
        qc.invalidateQueries({ queryKey: ["episodes"] });
      },
      () => {},
    );
    return unsub;
  }, [qc]);

  return (
    <div className="flex h-screen bg-bg-base text-white overflow-hidden">
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: "#141b26",
            border: "1px solid #1e293b",
            color: "white",
            fontSize: "13px",
            borderRadius: "10px",
          },
        }}
      />

      <Sidebar current={page} liveCount={liveDecisions.length} />

      <div className="flex-1 flex flex-col min-w-0">
        <Header
          page={page}
          orgId={orgId}
          onRefresh={refresh}
          isRefreshing={isRefreshing}
          liveCount={liveDecisions.length}
        />
        <main className="flex-1 overflow-y-auto bg-gradient-mesh">
          <div key={location.pathname} className="animate-fade-up min-h-full">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
