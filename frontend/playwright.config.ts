import { defineConfig, devices } from '@playwright/test'
import { resolve } from 'node:path'

const wav = resolve('tests/fixtures/send_5000.wav')

export default defineConfig({
  testDir: 'tests',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'https://localhost:5180',
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    ...devices['Pixel 7'],
    permissions: ['microphone'],
    launchOptions: {
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        `--use-file-for-fake-audio-capture=${wav}`,
        '--autoplay-policy=no-user-gesture-required',
      ],
    },
  },
  webServer: {
    command: 'npx vite --port 5180 --strictPort',
    port: 5180,
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
