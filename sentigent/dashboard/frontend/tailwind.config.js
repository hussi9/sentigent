/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#07090f",
          surface: "#0d1117",
          elevated: "#141b26",
          card: "#111827",
          border: "#1e293b",
          hover: "#192231",
        },
        accent: {
          DEFAULT: "#7c3aed",
          light: "#a78bfa",
          bright: "#c4b5fd",
          dim: "#3b1a85",
          glow: "rgba(124, 58, 237, 0.2)",
          subtle: "rgba(124, 58, 237, 0.08)",
        },
        success: {
          DEFAULT: "#10b981",
          light: "#34d399",
          dim: "rgba(16, 185, 129, 0.12)",
        },
        warning: {
          DEFAULT: "#f59e0b",
          light: "#fbbf24",
          dim: "rgba(245, 158, 11, 0.12)",
        },
        danger: {
          DEFAULT: "#ef4444",
          light: "#f87171",
          dim: "rgba(239, 68, 68, 0.12)",
        },
        info: {
          DEFAULT: "#3b82f6",
          light: "#60a5fa",
          dim: "rgba(59, 130, 246, 0.12)",
        },
        muted: "#475569",
        subtle: "#334155",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Cascadia Code", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.25s ease-out",
        "fade-up": "fadeUp 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-in-left": "slideInLeft 0.25s ease-out",
        shimmer: "shimmer 2s linear infinite",
        float: "float 6s ease-in-out infinite",
        "glow-pulse": "glowPulse 2s ease-in-out infinite",
        ticker: "ticker 0.35s ease-out",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        fadeUp: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { opacity: "0", transform: "translateX(16px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        slideInLeft: {
          from: { opacity: "0", transform: "translateX(-16px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        glowPulse: {
          "0%, 100%": { boxShadow: "0 0 12px rgba(124, 58, 237, 0.3)" },
          "50%": { boxShadow: "0 0 24px rgba(124, 58, 237, 0.6), 0 0 48px rgba(124, 58, 237, 0.2)" },
        },
        ticker: {
          from: { opacity: "0", transform: "translateY(-6px) scale(0.98)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
      boxShadow: {
        glow: "0 0 24px rgba(124, 58, 237, 0.35)",
        "glow-sm": "0 0 12px rgba(124, 58, 237, 0.2)",
        "glow-lg": "0 0 48px rgba(124, 58, 237, 0.4)",
        card: "0 1px 3px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4)",
        "card-hover": "0 4px 16px rgba(0,0,0,0.4), 0 2px 6px rgba(0,0,0,0.3)",
        success: "0 0 16px rgba(16, 185, 129, 0.25)",
        danger: "0 0 16px rgba(239, 68, 68, 0.25)",
      },
      backgroundImage: {
        "gradient-accent": "linear-gradient(135deg, #7c3aed, #a855f7)",
        "gradient-mesh":
          "radial-gradient(at 40% 20%, rgba(124, 58, 237, 0.07) 0px, transparent 50%), radial-gradient(at 80% 0%, rgba(59, 130, 246, 0.05) 0px, transparent 50%)",
      },
    },
  },
  plugins: [],
};
