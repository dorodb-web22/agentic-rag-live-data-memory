import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/query': {
        target: process.env.VITE_API_ORIGIN || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
