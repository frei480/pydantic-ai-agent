import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // Документация API (как nginx в проде); ^…$ — Vite трактует как regex,
      // чтобы /docs не ловил посторонние пути вроде /docsomething
      "^/docs$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/docs/": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/redoc$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/openapi\\.json$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
