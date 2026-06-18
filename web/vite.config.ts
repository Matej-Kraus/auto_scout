import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: /api -> lokalni FastAPI (uvicorn app.main:app --reload na :8000)
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
