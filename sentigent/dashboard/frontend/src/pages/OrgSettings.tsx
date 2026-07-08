import { useState } from "react";
import { Building2, Key, Copy, Check, RefreshCw, Loader2, Shield, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { supabase } from "@/lib/supabase";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export function OrgSettings() {
  const { membership } = useAuth();
  const [copying, setCopying] = useState(false);
  const [rotatingKey, setRotatingKey] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);

  const isOwner = membership?.role === "owner";
  const isAdmin = isOwner || membership?.role === "admin";

  async function copyOrgId() {
    if (!membership?.org_id) return;
    setCopying(true);
    await navigator.clipboard.writeText(membership.org_id);
    setTimeout(() => setCopying(false), 1500);
    toast.success("Org ID copied");
  }

  async function rotateApiKey() {
    if (!membership?.org_id || !isAdmin) return;
    setRotatingKey(true);

    // Generate a new API key
    const rawKey = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
    const keyName = `agent-key-${Date.now()}`;

    // In production: hash with bcrypt server-side. For now, store raw for display.
    // The server should accept a rotation RPC — here we insert directly.
    try {
      const { error } = await supabase.from("api_keys").insert({
        org_id: membership.org_id,
        key_hash: rawKey, // TODO: hash server-side before storing
        name: keyName,
        permissions: ["read", "write"],
        is_active: true,
      });
      if (error) throw error;
      setNewKey(`sntg_${rawKey.slice(0, 32)}`);
      toast.success("New API key generated — copy it now, it won't be shown again");
    } catch (e: unknown) {
      toast.error(`Failed to generate key: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setRotatingKey(false);
    }
  }

  const planColors = {
    free: "default" as const,
    team: "success" as const,
    enterprise: "accent" as const,
  };

  return (
    <div className="p-6 space-y-5 max-w-2xl">
      <div>
        <h2 className="text-lg font-bold text-white">Org Settings</h2>
        <p className="text-sm text-muted/60 mt-0.5">Manage your organization and agent connections</p>
      </div>

      {/* Org identity */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Building2 size={14} />}>Organization</CardTitle>
        </CardHeader>
        <CardBody>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted/60 uppercase tracking-wider mb-0.5">Name</p>
                <p className="text-sm font-semibold text-white">{membership?.org_name || "—"}</p>
              </div>
              <Badge variant={planColors[membership?.plan ?? "free"]}>
                {membership?.plan ?? "free"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted/60 uppercase tracking-wider mb-0.5">Slug</p>
                <p className="text-sm font-mono text-muted">{membership?.org_slug || "—"}</p>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted/60 uppercase tracking-wider mb-1">Org ID</p>
              <div className="flex items-center gap-2 bg-bg-card rounded-lg px-3 py-2 border border-bg-border/60">
                <code className="text-xs font-mono text-muted/80 flex-1 truncate">
                  {membership?.org_id || "—"}
                </code>
                <button
                  onClick={copyOrgId}
                  className="btn btn-ghost p-1 rounded text-muted/60 hover:text-white"
                >
                  {copying ? <Check size={13} className="text-success" /> : <Copy size={13} />}
                </button>
              </div>
              <p className="text-[11px] text-muted/40 mt-1.5 pl-1">
                Used in <code className="text-accent-light/70">SENTIGENT_ORG_ID</code> env var for your agents
              </p>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* API Key management */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Key size={14} />}>Agent API Keys</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-muted/60 mb-4">
            Agents use these keys to sync decisions to your org's Layer 2.
            Set <code className="text-accent-light/70 text-xs">SUPABASE_SERVICE_ROLE_KEY</code> for your local agents.
          </p>

          {newKey && (
            <div className="mb-4 rounded-xl border border-success/30 bg-success/10 p-4">
              <p className="text-xs font-semibold text-success mb-2 flex items-center gap-1.5">
                <Check size={12} /> New key generated — copy now
              </p>
              <div className="flex items-center gap-2 bg-bg-base rounded-lg px-3 py-2">
                <code className="text-xs font-mono text-success/90 flex-1 break-all">{newKey}</code>
                <button
                  onClick={() => { navigator.clipboard.writeText(newKey); toast.success("Copied"); }}
                  className="btn btn-ghost p-1 rounded flex-shrink-0"
                >
                  <Copy size={12} />
                </button>
              </div>
              <p className="text-[11px] text-muted/40 mt-2">
                This key will not be shown again. Store it in your .env file.
              </p>
            </div>
          )}

          {isAdmin ? (
            <button
              onClick={rotateApiKey}
              disabled={rotatingKey}
              className="btn btn-primary flex items-center gap-2"
            >
              {rotatingKey ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              Generate new API key
            </button>
          ) : (
            <p className="text-sm text-muted/50 italic">
              Only admins and owners can generate API keys.
            </p>
          )}
        </CardBody>
      </Card>

      {/* Plan */}
      {isOwner && (
        <Card>
          <CardHeader>
            <CardTitle icon={<Shield size={14} />}>Plan</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white capitalize">{membership?.plan ?? "free"} plan</p>
                {membership?.plan === "free" && (
                  <p className="text-xs text-muted/60 mt-0.5">1 user · up to 10k episodes/month</p>
                )}
                {membership?.plan === "team" && (
                  <p className="text-xs text-muted/60 mt-0.5">Unlimited users · 500k episodes/month</p>
                )}
              </div>
              {membership?.plan !== "enterprise" && (
                <button className="btn btn-primary flex items-center gap-1.5 text-xs">
                  Upgrade <ChevronRight size={12} />
                </button>
              )}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
