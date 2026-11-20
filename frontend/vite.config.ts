/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In dev, /api goes to FastAPI; in production FastAPI serves the build, so no CORS.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true, // lets Testing Library auto-clean up between tests
    setupFiles: ["./src/setupTests.ts"],
  },
});
