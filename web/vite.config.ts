import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  build: {
    chunkSizeWarningLimit: 700,
  },
  plugins: [tailwindcss(), svelte()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
