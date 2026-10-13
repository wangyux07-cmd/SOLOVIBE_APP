import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.SOLOVIBE_E2E_BASE_URL || 'http://127.0.0.1:5173',
    channel: 'msedge',
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
  },
});
