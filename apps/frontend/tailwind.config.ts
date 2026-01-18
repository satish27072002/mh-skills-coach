import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-jakarta)", "system-ui", "sans-serif"]
      },
      colors: {
        ink: "#1f2937",
        fog: "#f8f6f2",
        glow: "#f7c59f",
        tide: "#9ad0ec",
        coral: "#f28482"
      }
    }
  },
  plugins: []
};

export default config;
