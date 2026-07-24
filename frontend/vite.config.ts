import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": "/src"
    }
  },
  server: {
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/models": "http://127.0.0.1:8000",
      "/bank": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000"
    }
  }
});
