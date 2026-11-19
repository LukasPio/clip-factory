import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:1420',
    launchOptions: {
      executablePath: process.env.CLIP_FACTORY_CHROMIUM,
      args: ['--no-proxy-server', '--disable-background-networking', '--disable-component-update',
        '--disable-domain-reliability', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost'],
    },
  },
  projects: [
    { name: 'notebook', use: { viewport: { width: 1366, height: 768 } } },
    { name: 'desktop', use: { viewport: { width: 1920, height: 1080 } } },
  ],
  webServer: {
    command: 'node e2e/server.mjs',
    url: 'http://127.0.0.1:1420',
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
  },
})
