/** Тёмная палитра в духе LM Studio */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#161618",
        rail: "#111113",
        panel: "#1e1e21",
        panel2: "#26262a",
        hover: "#2e2e33",
        line: "#323238",
        fg: "#e7e7ea",
        muted: "#9a9aa3",
        dim: "#6b6b74",
        accent: { DEFAULT: "#8b5cf6", soft: "#8b5cf622", fg: "#c4b5fd" },
        ok: "#34d399",
        warn: "#fbbf24",
        bad: "#f87171",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
