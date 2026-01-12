import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Gill Sans", "Trebuchet MS", "Calibri", "sans-serif"],
        body: ["Georgia", "Times New Roman", "serif"]
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
