import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Standalone SPA (unlike sibling demochat, which is a library build).
export default defineConfig({
  plugins: [react()],
  server: {
    open: true,
  },
})
