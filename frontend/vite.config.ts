import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
  server: {
    host: '127.0.0.1',
    port: Number(process.env.SOLOVIBE_DEV_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.SOLOVIBE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true },
  };
});
