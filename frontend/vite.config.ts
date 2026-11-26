import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiOrigin = process.env.VITE_API_ORIGIN || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/query': {
        target: apiOrigin,
        changeOrigin: true,
      },
      '/health': {
        target: apiOrigin,
        changeOrigin: true,
      },
      '/threads': {
        target: apiOrigin,
        changeOrigin: true,
      },
    },
  },
});
