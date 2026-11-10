import { useEffect, useRef } from 'preact/hooks'
import type { ReadonlySignal } from '@preact/signals'
import styles from './ListeningOrb.module.css'

export type OrbMode = 'listening' | 'hearing' | 'checking'

interface Props {
  mode: OrbMode
  /** smoothed mic level 0..1 */
  level: ReadonlySignal<number>
  /** true while Avenza is speaking: orb is still and dimmed */
  speaking: ReadonlySignal<boolean>
  size?: number
}

const prefersReducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** Canvas orb: radius follows the mic level, breathes when idle, still while Avenza speaks, ring spinner while checking. */
export function ListeningOrb({ mode, level, speaking, size = 200 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = Math.min(window.devicePixelRatio || 1, 3)
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const reduced = prefersReducedMotion()
    let raf = 0
    let smooth = 0
    let accent = '#3dd9b3'
    let frame = 0
    const cx = size / 2
    const base = size * 0.3

    const draw = (time: number) => {
      if (frame++ % 30 === 0) accent = getComputedStyle(canvas).getPropertyValue('--accent').trim() || accent
      const m = modeRef.current
      const dim = speaking.value
      ctx.clearRect(0, 0, size, size)
      ctx.globalAlpha = dim ? 0.45 : 1

      if (reduced) {
        // static ring
        ctx.strokeStyle = accent
        ctx.lineWidth = 4
        ctx.beginPath()
        ctx.arc(cx, cx, base + 10, 0, Math.PI * 2)
        ctx.stroke()
        ctx.globalAlpha = 0.14
        ctx.fillStyle = accent
        ctx.beginPath()
        ctx.arc(cx, cx, base, 0, Math.PI * 2)
        ctx.fill()
        return
      }

      if (m === 'checking') {
        const a = (time / 900) * Math.PI * 2
        ctx.strokeStyle = accent
        ctx.globalAlpha = 0.18
        ctx.lineWidth = 6
        ctx.beginPath()
        ctx.arc(cx, cx, base + 12, 0, Math.PI * 2)
        ctx.stroke()
        ctx.globalAlpha = 1
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.arc(cx, cx, base + 12, a, a + Math.PI * 0.55)
        ctx.stroke()
        ctx.globalAlpha = 0.12
        ctx.fillStyle = accent
        ctx.beginPath()
        ctx.arc(cx, cx, base, 0, Math.PI * 2)
        ctx.fill()
      } else {
        const target = dim ? 0 : level.value
        smooth += (target - smooth) * 0.18
        const breath = dim ? 0 : (Math.sin(time / 1300) + 1) / 2 // slow breathing when idle
        const idleAmp = m === 'listening' ? breath * 0.07 : 0
        const r = base * (1 + idleAmp) + smooth * size * 0.2
        // halo, body, ring: flat fills only
        ctx.fillStyle = accent
        ctx.globalAlpha = (dim ? 0.45 : 1) * 0.1
        ctx.beginPath()
        ctx.arc(cx, cx, r + 22 + smooth * 18, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalAlpha = (dim ? 0.45 : 1) * 0.2
        ctx.beginPath()
        ctx.arc(cx, cx, r + 10, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalAlpha = dim ? 0.45 : 1
        ctx.strokeStyle = accent
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.arc(cx, cx, r, 0, Math.PI * 2)
        ctx.stroke()
        ctx.globalAlpha = (dim ? 0.45 : 1) * 0.85
        ctx.beginPath()
        ctx.arc(cx, cx, r * 0.55, 0, Math.PI * 2)
        ctx.fillStyle = accent
        ctx.fill()
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    if (reduced) draw(0)
    return () => cancelAnimationFrame(raf)
  }, [size, level, speaking])

  return <canvas ref={ref} class={styles.orb} style={{ width: `${size}px`, height: `${size}px` }} aria-hidden="true" data-mode={mode} />
}
