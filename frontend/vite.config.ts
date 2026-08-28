import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // Local dev only (design principle 1) -- proxy /api to the FastAPI
    // backend (scripts/run_api.py, port 8000) so the frontend can call
    // relative /api/... paths in both dev and the eventual production
    // build (where FastAPI serves the built static files itself).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
