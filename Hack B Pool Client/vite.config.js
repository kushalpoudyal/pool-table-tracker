import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // API_PROXY_TARGET lets docker compose point this at the api service.
      '/api': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
    },
  },
});
