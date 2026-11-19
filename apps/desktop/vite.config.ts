import { defineConfig } from 'vitest/config'

export default defineConfig({
  server: {
    // Cargo can lock build executables while Vite starts on Windows.
    watch: { ignored: ['**/src-tauri/**'] },
  },
  test: { exclude: ['**/node_modules/**', '**/e2e/**', '**/dist/**'] },
})
