import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

// Single source of truth: no Supabase project configured → the dashboard runs
// in local-first mode (default `pip install sentigent`, server on 127.0.0.1).
// AuthContext reads this to bypass the auth gate entirely instead of just
// warning about it.
export const isLocalMode = !supabaseUrl || !supabaseAnonKey;

if (isLocalMode) {
  console.warn(
    "[Sentigent] VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY not set — auth disabled, running in local mode"
  );
}

export const supabase = createClient(
  supabaseUrl || "https://placeholder.supabase.co",
  supabaseAnonKey || "placeholder"
);
