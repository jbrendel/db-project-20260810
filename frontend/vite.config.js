import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Ports are discovered by start_all.sh and passed via env (§4). Vite proxies
// /api/* to Django same-origin, so CORS is unnecessary in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: process.env.VITE_PORT ? Number(process.env.VITE_PORT) : 5173,
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.DJANGO_PORT || 8000}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.js",
  },
});
