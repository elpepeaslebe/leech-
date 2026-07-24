/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "var(--color-rule)",
        input: "var(--color-rule-strong)",
        ring: "var(--color-accent)",
        background: "var(--color-paper)",
        foreground: "var(--color-ink)",
        primary: {
          DEFAULT: "var(--color-accent)",
          foreground: "var(--color-on-accent)"
        },
        secondary: {
          DEFAULT: "var(--color-panel-strong)",
          foreground: "var(--color-ink)"
        },
        destructive: {
          DEFAULT: "var(--color-critical)",
          foreground: "var(--color-ink)"
        },
        muted: {
          DEFAULT: "var(--color-panel)",
          foreground: "var(--color-muted)"
        },
        accent: {
          DEFAULT: "var(--color-accent-soft)",
          foreground: "var(--color-ink)"
        },
        popover: {
          DEFAULT: "var(--color-paper-2)",
          foreground: "var(--color-ink)"
        },
        card: {
          DEFAULT: "var(--color-panel)",
          foreground: "var(--color-ink)"
        }
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)"
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        mono: ["var(--font-mono)"]
      }
    }
  },
  plugins: []
};
