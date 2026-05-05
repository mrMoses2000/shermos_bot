import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173
  },
  build: {
    rollupOptions: {
      input: {
        mini: resolve(__dirname, "index.html"),
        cms: resolve(__dirname, "cms.html"),
      }
    }
  }
});
