import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const publicHost = env.PUBLIC_HOST || "localhost";
  const apiPort = env.PORT || "8000";
  const clientPort = env.CLIENT_PORT || "5173";
  const apiUrl =
    env.VITE_API_PROXY_URL ||
    env.API_URL ||
    `http://${publicHost}:${apiPort}`;

  return {
    envDir: "..",
    plugins: [react()],
    server: {
      port: Number(clientPort),
      proxy: {
        "/ws": {
          target: apiUrl,
          ws: true,
        },
      },
    },
  };
});
