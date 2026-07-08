import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase, isLocalMode } from "@/lib/supabase";

// ── Types ──────────────────────────────────────────────────────────────────

export interface OrgMembership {
  org_id: string;
  org_name: string;
  org_slug: string;
  role: "owner" | "admin" | "member" | "viewer";
  plan: "free" | "team" | "enterprise";
}

interface AuthState {
  session: Session | null;
  user: User | null;
  membership: OrgMembership | null;
  loading: boolean;
}

interface AuthContextValue extends AuthState {
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signUp: (email: string, password: string, orgName: string, orgSlug: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
  acceptInvite: (token: string) => Promise<{ error: string | null }>;
  refreshMembership: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Local mode ─────────────────────────────────────────────────────────────
// No Supabase project configured (the default `pip install sentigent` case,
// server bound to 127.0.0.1). There's no multi-tenant auth to gate — the
// dashboard is a single-user local console, so we synthesize a permanent
// "local" session/user/membership instead of ever hitting Supabase.

const LOCAL_USER = {
  id: "local",
  email: "local@localhost",
} as unknown as User;

const LOCAL_SESSION = {
  access_token: "local",
  token_type: "bearer",
  user: LOCAL_USER,
} as unknown as Session;

const LOCAL_MEMBERSHIP: OrgMembership = {
  org_id: "local",
  org_name: "Local",
  org_slug: "local",
  role: "owner",
  plan: "enterprise",
};

// ── Provider ───────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(
    isLocalMode
      ? { session: LOCAL_SESSION, user: LOCAL_USER, membership: LOCAL_MEMBERSHIP, loading: false }
      : { session: null, user: null, membership: null, loading: true }
  );

  const fetchMembership = useCallback(async (userId: string) => {
    try {
      const { data, error } = await supabase
        .from("org_members")
        .select(`
          role,
          org_id,
          organizations (name, slug, plan)
        `)
        .eq("user_id", userId)
        .single();

      if (error || !data) return null;

      const org = Array.isArray(data.organizations)
        ? data.organizations[0]
        : data.organizations;

      return {
        org_id: data.org_id,
        org_name: org?.name ?? "",
        org_slug: org?.slug ?? "",
        role: data.role as OrgMembership["role"],
        plan: (org?.plan ?? "free") as OrgMembership["plan"],
      };
    } catch {
      return null;
    }
  }, []);

  const refreshMembership = useCallback(async () => {
    if (isLocalMode) return; // membership is fixed in local mode
    const userId = state.user?.id;
    if (!userId) return;
    const membership = await fetchMembership(userId);
    setState((prev) => ({ ...prev, membership }));
  }, [state.user?.id, fetchMembership]);

  useEffect(() => {
    if (isLocalMode) return; // state is already seeded with the local session

    // Load initial session
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      const membership = session?.user
        ? await fetchMembership(session.user.id)
        : null;
      setState({ session, user: session?.user ?? null, membership, loading: false });
    });

    // Subscribe to auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        const membership = session?.user
          ? await fetchMembership(session.user.id)
          : null;
        setState({ session, user: session?.user ?? null, membership, loading: false });
      }
    );

    return () => subscription.unsubscribe();
  }, [fetchMembership]);

  const signIn = useCallback(async (email: string, password: string) => {
    if (isLocalMode) return { error: null }; // already signed in locally
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return { error: error?.message ?? null };
  }, []);

  const signUp = useCallback(
    async (email: string, password: string, orgName: string, orgSlug: string) => {
      if (isLocalMode) return { error: null }; // no signup flow in local mode
      // 1. Create the auth user
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) return { error: error.message };
      if (!data.user) return { error: "Signup failed — no user returned" };

      // 2. Create org + make user owner
      const { error: rpcError } = await supabase.rpc("create_org_with_owner", {
        p_name: orgName,
        p_slug: orgSlug,
      });
      if (rpcError) return { error: rpcError.message };

      return { error: null };
    },
    []
  );

  const signOut = useCallback(async () => {
    if (isLocalMode) return; // no-op — there's no one else to sign in as locally
    await supabase.auth.signOut();
    setState({ session: null, user: null, membership: null, loading: false });
  }, []);

  const acceptInvite = useCallback(async (token: string) => {
    if (isLocalMode) return { error: null }; // no org invites in local mode
    const { error } = await supabase.rpc("accept_invite", { p_token: token });
    if (error) return { error: error.message };
    await refreshMembership();
    return { error: null };
  }, [refreshMembership]);

  return (
    <AuthContext.Provider
      value={{ ...state, signIn, signUp, signOut, acceptInvite, refreshMembership }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ───────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
