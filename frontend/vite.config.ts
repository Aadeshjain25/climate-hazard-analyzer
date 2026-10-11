import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the FastAPI server so the browser sees one origin.
// In production set VITE_API_URL to the deployed backend (e.g. https://cha-api.onrender.com).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { charts: ["chart.js", "react-chartjs-2"], map: ["leaflet", "react-leaflet"] } },
    },
  },
});
