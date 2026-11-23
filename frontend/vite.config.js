import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// During "npm run dev" the browser talks to Vite, and Vite forwards /api and /ws to the backend.
// 127.0.0.1 (not "localhost") avoids IPv6 problems on Windows.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
});
