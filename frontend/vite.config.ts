import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The backend address is never hard-coded. For local development set
// VITE_DEV_PROXY_TARGET in an untracked .env.local file (see .env.example);
// the dev server then forwards API calls to it, so no CORS setup is needed.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_DEV_PROXY_TARGET;
  // Triggers read every document with an LLM, so the proxy must wait minutes.
  const timeout = 600_000;
  return {
    plugins: [react()],
    server: proxyTarget
      ? {
          proxy: {
            "/v1": { target: proxyTarget, changeOrigin: true, timeout, proxyTimeout: timeout },
            "/health": { target: proxyTarget, changeOrigin: true },
          },
        }
      : {},
  };
});
