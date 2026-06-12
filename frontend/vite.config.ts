import { defineConfig } from "vite";

// Overridden by the Playwright E2E suite so the dev server proxies to the
// isolated mock-provider backend instead of a real dev backend.
const backendPort = process.env.STUDIOUS_BACKEND_PORT ?? "8000";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
