import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const api = process.env.QUE_DEV_API || 'http://127.0.0.1:8790';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
      '/assets': api,
      '/static': api,
      '/health': api
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'app-assets'
  }
});
