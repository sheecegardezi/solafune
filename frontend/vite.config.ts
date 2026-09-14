import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/tiles": "http://localhost:8000" } },
  build: {
    rollupOptions: {
      output: {
        // split heavy vendor code (deck.gl + react) out of the app chunk so it
        // downloads in parallel and stays cached across app releases
        manualChunks: {
          deck: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/geo-layers", "@deck.gl/react"],
          react: ["react", "react-dom"],
        },
      },
    },
  },
});
