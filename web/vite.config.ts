import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the UI with hot reload; API calls go to the Python server (python main.py, UI_PORT 8765).
// host: true = reachable from other PCs too; changeOrigin sends the Python server's own Host (it checks it).
const api = { target: "http://127.0.0.1:8765", changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  server: { host: true, proxy: { "/api": api, "/scans": api } },
});
