import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds into the Python package so the dashboard runs without Node on Anagha's PC.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../jobbot/dashboard/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
