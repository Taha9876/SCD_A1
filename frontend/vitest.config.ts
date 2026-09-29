import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts on purpose: vitest ships its own copy of Vite,
// and a single file that imports defineConfig from 'vitest/config' while
// importing plugins resolved against the top-level 'vite' makes tsc compare two
// structurally identical but nominally different Plugin types and fail.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    coverage: { reporter: ['text'] },
  },
})
