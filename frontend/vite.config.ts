import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    // 5173 collided with another local project's dev server bound to
    // [::1]:5173, and 5174 (the first fallback) has since been claimed
    // the same way by yet another project's [::1] listener -- since
    // `localhost` resolves to ::1 first on this machine, that made
    // requests to this app nondeterministically land on the OTHER app
    // instead (confirmed real both times: got the other app's HTML back
    // from a plain curl). 5175 was confirmed fully free (neither IPv4 nor
    // IPv6) via `lsof -nP -iTCP:5175 -sTCP:LISTEN` before picking it.
    port: 5175,
  },
})
