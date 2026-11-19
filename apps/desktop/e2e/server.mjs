import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

const root = resolve('../..')
const data = mkdtempSync(join(tmpdir(), 'clip-factory-e2e-'))
const python = process.env.CLIP_FACTORY_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
const engine = spawn(python, ['-m', 'app.main'], {
  cwd: join(root, 'services', 'engine'),
  env: { ...process.env, CLIP_FACTORY_DATA: data, CLIP_FACTORY_MANAGED: '1' },
  stdio: ['pipe', 'pipe', 'inherit'],
})
let vite
let closing = false
const lines = createInterface({ input: engine.stdout })
lines.once('line', line => {
  const { url, token } = JSON.parse(line)
  vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '1420', '--strictPort'], {
    env: { ...process.env, VITE_ENGINE_URL: url, VITE_ENGINE_TOKEN: token },
    stdio: 'inherit',
  })
  vite.on('exit', code => stop(code ?? 1))
})
engine.on('error', error => { console.error(error.message); stop(1) })
engine.on('exit', code => { if (!closing) stop(code ?? 1) })
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => stop(0))

function stop(code) {
  if (closing) return
  closing = true
  vite?.kill()
  if (engine.pid && engine.exitCode === null) {
    engine.once('close', cleanup)
    engine.stdin.end()
    setTimeout(() => engine.kill(), 4000).unref()
  } else cleanup()
  function cleanup() {
    rmSync(data, { recursive: true, force: true })
    process.exitCode = code
  }
}
