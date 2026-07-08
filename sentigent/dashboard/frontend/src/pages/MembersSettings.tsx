import { useState, useEffect } from "react";
import {
  Users, UserPlus, Shield, Mail, Loader2,
  Crown, Eye, Check, X
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { supabase } from "@/lib/supabase";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface Member {
  id: string;
  user_id: string;
  role: "owner" | "admin" | "member" | "viewer";
  joined_at: string;
  email?: string;
}

const ROLE_ICONS = {
  owner: <Crown size={11} className="text-amber-400" />,
  admin: <Shield size={11} className="text-accent-light" />,
  member: <Users size={11} className="text-muted/60" />,
  viewer: <Eye size={11} className="text-muted/60" />,
};

const ROLE_BADGE_VARIANTS = {
  owner: "warning" as const,
  admin: "accent" as const,
  member: "default" as const,
  viewer: "default" as const,
};

export function MembersSettings() {
  const { membership, user } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(true);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member" | "viewer">("member");
  const [inviting, setInviting] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);

  const isAdmin = membership?.role === "owner" || membership?.role === "admin";

  useEffect(() => {
    if (!membership?.org_id) return;
    loadMembers();
  }, [membership?.org_id]);

  async function loadMembers() {
    setLoadingMembers(true);
    try {
      const { data, error } = await supabase
        .from("org_members")
        .select("id, user_id, role, joined_at")
        .eq("org_id", membership!.org_id)
        .order("joined_at");

      if (error) throw error;
      setMembers(data ?? []);
    } catch (e: unknown) {
      toast.error(`Failed to load members: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setLoadingMembers(false);
    }
  }

  async function sendInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail.trim() || !membership?.org_id) return;
    setInviting(true);

    try {
      const { data, error } = await supabase
        .from("org_invites")
        .insert({
          org_id: membership.org_id,
          email: inviteEmail.trim(),
          role: inviteRole,
          invited_by: user?.id,
        })
        .select("token")
        .single();

      if (error) throw error;
      const link = `${window.location.origin}/auth/invite/${data.token}`;
      setInviteLink(link);
      setInviteEmail("");
      toast.success("Invite created — share the link with your teammate");
    } catch (e: unknown) {
      toast.error(`Failed to create invite: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setInviting(false);
    }
  }

  async function updateRole(memberId: string, newRole: "admin" | "member" | "viewer") {
    try {
      const { error } = await supabase
        .from("org_members")
        .update({ role: newRole })
        .eq("id", memberId);
      if (error) throw error;
      setMembers(prev => prev.map(m => m.id === memberId ? { ...m, role: newRole } : m));
      toast.success("Role updated");
    } catch (e: unknown) {
      toast.error(`Failed: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }

  async function removeMember(memberId: string) {
    if (!window.confirm("Remove this member from your org?")) return;
    try {
      const { error } = await supabase.from("org_members").delete().eq("id", memberId);
      if (error) throw error;
      setMembers(prev => prev.filter(m => m.id !== memberId));
      toast.success("Member removed");
    } catch (e: unknown) {
      toast.error(`Failed: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }

  return (
    <div className="p-6 space-y-5 max-w-2xl">
      <div>
        <h2 className="text-lg font-bold text-white">Members</h2>
        <p className="text-sm text-muted/60 mt-0.5">
          Invite teammates to view and manage your org's agent intelligence
        </p>
      </div>

      {/* Invite form */}
      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle icon={<UserPlus size={14} />}>Invite teammate</CardTitle>
          </CardHeader>
          <CardBody>
            <form onSubmit={sendInvite} className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={e => setInviteEmail(e.target.value)}
                  required
                  placeholder="colleague@company.com"
                  className="input flex-1"
                />
                <select
                  value={inviteRole}
                  onChange={e => setInviteRole(e.target.value as typeof inviteRole)}
                  className="input w-28"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button
                  type="submit"
                  disabled={inviting}
                  className="btn btn-primary flex items-center gap-1.5 shrink-0"
                >
                  {inviting ? <Loader2 size={13} className="animate-spin" /> : <Mail size={13} />}
                  Invite
                </button>
              </div>

              {inviteLink && (
                <div className="rounded-lg border border-success/30 bg-success/10 p-3">
                  <p className="text-xs text-success font-semibold mb-1.5 flex items-center gap-1.5">
                    <Check size={11} /> Invite link ready
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="text-[11px] font-mono text-muted/80 flex-1 break-all">
                      {inviteLink}
                    </code>
                    <button
                      type="button"
                      onClick={() => { navigator.clipboard.writeText(inviteLink!); toast.success("Copied"); }}
                      className="btn btn-ghost p-1 rounded flex-shrink-0 text-xs"
                    >
                      Copy
                    </button>
                  </div>
                </div>
              )}
            </form>

            <div className="mt-3 grid grid-cols-3 gap-2">
              {(["viewer", "member", "admin"] as const).map(r => (
                <div key={r} className="rounded-lg bg-bg-card border border-bg-border/60 p-2.5 text-center">
                  <div className="flex justify-center mb-1">{ROLE_ICONS[r]}</div>
                  <p className="text-[11px] font-semibold text-white capitalize">{r}</p>
                  <p className="text-[10px] text-muted/50 mt-0.5">
                    {r === "viewer" && "Read-only access"}
                    {r === "member" && "View + own Layer 1"}
                    {r === "admin" && "Full management"}
                  </p>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Members list */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Users size={14} />}>
            Team ({members.length})
          </CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {loadingMembers ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-accent-light/60" />
            </div>
          ) : members.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted/50">
              No members yet — invite your first teammate above
            </div>
          ) : (
            <div className="divide-y divide-bg-border/40">
              {members.map(m => (
                <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                  <div
                    className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
                    style={{ background: "linear-gradient(135deg, #7c3aed, #a855f7)" }}
                  >
                    {m.user_id.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white/90 font-mono truncate">{m.user_id}</p>
                    <p className="text-[10px] text-muted/50">
                      Joined {new Date(m.joined_at).toLocaleDateString()}
                    </p>
                  </div>
                  <Badge variant={ROLE_BADGE_VARIANTS[m.role]} dot>
                    {ROLE_ICONS[m.role]}
                    {m.role}
                  </Badge>
                  {isAdmin && m.role !== "owner" && m.user_id !== user?.id && (
                    <div className="flex items-center gap-1">
                      <select
                        value={m.role}
                        onChange={e => updateRole(m.id, e.target.value as "admin" | "member" | "viewer")}
                        className="input text-xs py-1 px-2 h-7 w-24"
                      >
                        <option value="admin">Admin</option>
                        <option value="member">Member</option>
                        <option value="viewer">Viewer</option>
                      </select>
                      <button
                        onClick={() => removeMember(m.id)}
                        className="btn btn-ghost p-1 rounded text-danger/60 hover:text-danger"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
