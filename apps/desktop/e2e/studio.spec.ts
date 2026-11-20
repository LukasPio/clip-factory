import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

test('importa, edita, gera prévia, reabre e exporta um corte real', async ({ page }, info) => {
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1'
    ? route.continue()
    : route.abort())
  const dir = mkdtempSync(join(tmpdir(), 'clip-fixture-'))
  const video = join(dir, 'original.mp4')
  try {
    execFileSync('ffmpeg', [
      '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=30',
      '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video,
    ])
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Seus projetos' })).toBeVisible()
    await page.getByRole('main').getByRole('button', { name: 'Novo projeto' }).click()
    await page.getByLabel('Nome do projeto').fill(`Fluxo ${info.project.name}`)
    await page.getByLabel('Arquivo de vídeo').fill(video)
    await page.getByRole('button', { name: 'Importar vídeo' }).click()
    await expect(page.getByRole('heading', { name: 'Vídeo original' })).toBeVisible()
    await page.getByRole('button', { name: 'Criar corte manual' }).click()
    await page.getByLabel('Título', { exact: true }).fill('Corte validado')
    const selected = page.getByRole('checkbox', { name: 'Selecionar Corte manual' })
    await selected.click()
    await expect(selected).not.toBeChecked()
    await expect(page.getByLabel('Título', { exact: true })).toHaveValue('Corte validado')
    await page.getByLabel('Início no vídeo').fill('0.5')
    await page.getByRole('button', { name: 'Adicionar legenda' }).click()
    await page.getByLabel('Início da legenda 1').fill('0.5')
    await page.getByLabel('Texto da legenda 1').fill('Legenda de teste')
    await page.getByRole('button', { name: 'Atualizar prévia' }).click()
    await expect(page.locator('video[aria-label="Prévia vertical do corte"]')).toHaveAttribute('src', /\/media\//)
    await page.reload()
    await page.getByRole('button', { name: new RegExp(`Fluxo ${info.project.name}`) }).click()
    await page.getByRole('button', { name: 'Editar e reproduzir' }).click()
    await expect(page.getByRole('checkbox', { name: 'Selecionar Corte validado' })).not.toBeChecked()
    await expect(page.getByLabel('Texto da legenda 1')).toHaveValue('Legenda de teste')
    await expect(page.getByLabel('Início no vídeo')).toHaveValue('0.5')
    await page.getByRole('button', { name: 'Exportar MP4' }).click()
    await page.getByLabel('Pasta de saída').fill(dir)
    await page.getByRole('button', { name: 'Exportar 1 corte' }).click()
    await expect(page.getByText('Exportação concluída.')).toBeVisible()
    const metadata = JSON.parse(execFileSync('ffprobe', [
      '-v', 'error', '-show_streams', '-of', 'json', join(dir, 'clip-Corte validado.mp4'),
    ], { encoding: 'utf8' })).streams
    expect(metadata[0]).toMatchObject({ codec_name: 'h264', width: 1080, height: 1920, avg_frame_rate: '30/1' })
    expect(metadata[1].codec_name).toBe('aac')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
