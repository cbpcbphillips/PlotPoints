import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the API runs on :8000 and the app on :5173. Proxying /api keeps the browser on
// one origin, so there is no CORS to configure locally. 127.0.0.1, not localhost: on Windows the
// latter tries IPv6 first and costs ~2 s per request before falling back.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        // PLOTPOINTS_API_PROXY lets a second API on another port be used when 8000 is taken
        target: process.env.PLOTPOINTS_API_PROXY ?? 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: { environment: 'jsdom', globals: true },
})
