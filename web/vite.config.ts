/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

// HollerBox web app — Phase 0 shell.
// PWA + push wiring lands in Phase 8; the plugin is included now so dev parity
// stays close to prod from day one.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["logo.png"],
      manifest: {
        name: "HollerBox",
        short_name: "HollerBox",
        description: "Local-first, chat-driven AI workflow engine.",
        theme_color: "#c97a48",
        background_color: "#faf6ee",
        display: "standalone",
        icons: [
          { src: "/logo.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    host: "127.0.0.1",
  },
});
