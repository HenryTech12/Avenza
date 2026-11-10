import { chromium } from '@playwright/test'
import { writeFileSync, mkdirSync } from 'node:fs'
const svg = (size, pad) => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 512 512"><rect width="512" height="512" fill="#0B1220"/><g transform="translate(256 256) scale(${pad}) translate(-256 -256)"><path d="M150 380 256 130l106 250M190 300h132" fill="none" stroke="#3DD9B3" stroke-width="40" stroke-linecap="round" stroke-linejoin="round"/><circle cx="372" cy="376" r="22" fill="#3DD9B3"/></g></svg>`
mkdirSync('public/icons', { recursive: true })
const b = await chromium.launch()
const p = await b.newPage()
for (const [name, size, pad] of [['icon-192', 192, 1], ['icon-512', 512, 1], ['maskable-512', 512, 0.72]]) {
  await p.setViewportSize({ width: size, height: size })
  await p.setContent(`<body style="margin:0">${svg(size, pad)}</body>`)
  writeFileSync(`public/icons/${name}.png`, await p.screenshot({ type: 'png' }))
}
await b.close()
