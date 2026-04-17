import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(() => {
  // GitHub Pages serves from `/<repo>/`, not `/`.
  // - In Actions, `GITHUB_REPOSITORY` is like "owner/repo".
  // - Override with `BASE_PATH` if you need a custom path.
  const repo = process.env.GITHUB_REPOSITORY?.split('/')[1]
  const base =
    process.env.BASE_PATH ??
    (process.env.GITHUB_PAGES === 'true' && repo ? `/${repo}/` : '/')

  return {
    base,
    build: {
      chunkSizeWarningLimit: 700,
    },
    plugins: [tailwindcss(), svelte()],
    server: {
      proxy: {
        '/api': 'http://127.0.0.1:8000',
      },
    },
  }
})
