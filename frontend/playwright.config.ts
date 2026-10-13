import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const localPython = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../.venv/Scripts/python.exe');
const python = process.env.SOLOVIBE_PYTHON || (existsSync(localPython) ? `"${localPython}"` : 'python');
const backendCommand = process.platform === 'win32'
  ? `${python} ../backend/run_server.py`
  : `${python} -m uvicorn main:app --app-dir ../backend --host 127.0.0.1 --port 8000 --no-access-log`;

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.SOLOVIBE_E2E_BASE_URL || 'http://127.0.0.1:5173',
    channel: process.env.CI ? undefined : 'msedge',
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
  },
  webServer: [
    { command: backendCommand,
      url: 'http://127.0.0.1:8000/api/v1/health', reuseExistingServer: !process.env.CI, timeout: 45_000 },
    { command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.CI, timeout: 45_000 },
  ],
});
