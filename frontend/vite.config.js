import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev:  `npm run dev`   → Vite serves on 5173 and proxies /api (REST) and /ws
//                         (the live-collaboration WebSocket) to the backend.
// Prod: `npm run build` → static files land in dist/, which FastAPI serves
//                         itself on one port, so no proxy is involved.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // `ws: true` is essential — without it the collaboration socket can't
      // reach the backend in dev and live co-editing silently doesn't work.
      "/ws": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
