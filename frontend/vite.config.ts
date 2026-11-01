import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 6482,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:9247",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/auth": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:9247",
        changeOrigin: true,
      },
      "/v1": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:9247",
        changeOrigin: true,
      },
      "/.well-known/clef-node": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:9247",
        changeOrigin: true,
      },
    },
  },
  build: {
    commonjsOptions: {
      transformMixedEsModules: true,
    },
  },
});
