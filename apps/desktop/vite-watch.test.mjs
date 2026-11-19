import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, normalize, resolve } from 'node:path'
import { createServer } from 'vite'
import { expect, it } from 'vitest'

it('watches frontend files without opening Cargo build files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'clip-factory-watch-'))
  const source = join(root, 'src')
  const cargoBuild = join(root, 'src-tauri', 'target', 'debug', 'build')

  try {
    await mkdir(source)
    await mkdir(cargoBuild, { recursive: true })
    await writeFile(join(source, 'main.ts'), 'export {}')
    await writeFile(join(cargoBuild, 'build_script_build.exe'), '')

    const server = await createServer({
      root,
      configFile: resolve('vite.config.ts'),
      server: { middlewareMode: true, hmr: false },
    })
    try {
      const watchedFiles = dir => Object.entries(server.watcher.getWatched())
        .find(([watchedDir]) => normalize(watchedDir) === dir)?.[1] ?? []
      await expect.poll(() => watchedFiles(source)).toContain('main.ts')
      expect(watchedFiles(root)).not.toContain('src-tauri')
    } finally {
      await server.close()
    }
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
