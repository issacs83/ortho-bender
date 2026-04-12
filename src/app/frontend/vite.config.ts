import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API calls to the FastAPI backend during development.
// Change the target to the i.MX8MP IP when testing against real hardware.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_URL || "http://192.168.77.2:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: (process.env.VITE_BACKEND_URL || "http://192.168.77.2:8000").replace(/^http/, "ws"),
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
