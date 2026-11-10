import { readFileSync, writeFileSync, rmSync } from 'node:fs'
// Pads a 16 kHz mono 16-bit WAV with leading and trailing silence so Chrome's looping fake mic has quiet gaps.
const src = readFileSync('tests/fixtures/raw.wav')
let off = 12, dataStart = 0, dataLen = 0
while (off < src.length) {
  const id = src.toString('ascii', off, off + 4), len = src.readUInt32LE(off + 4)
  if (id === 'data') { dataStart = off + 8; dataLen = len; break }
  off += 8 + len
}
const pcm = src.subarray(dataStart, dataStart + dataLen)
const lead = Buffer.alloc(16000 * 2 * 2), tail = Buffer.alloc(16000 * 2 * 5)
const body = Buffer.concat([lead, pcm, tail])
const h = Buffer.alloc(44)
h.write('RIFF', 0); h.writeUInt32LE(36 + body.length, 4); h.write('WAVE', 8); h.write('fmt ', 12)
h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(16000, 24)
h.writeUInt32LE(32000, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(body.length, 40)
writeFileSync('tests/fixtures/send_5000.wav', Buffer.concat([h, body]))
rmSync('tests/fixtures/raw.wav')
