import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме /api проксируется на backend (порт 8000 открыт только на 127.0.0.1)
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1200 },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
