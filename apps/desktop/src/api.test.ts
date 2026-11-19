import { describe, expect, it } from 'vitest'
import { active, Engine, time, type Job } from './api'

describe('estado do motor', () => {
  it('distingue tarefas ativas de resultados finais', () => {
    expect(active({ status: 'queued' } as Job)).toBe(true)
    expect(active({ status: 'failed' } as Job)).toBe(false)
    expect(active(null)).toBe(false)
  })

  it('exibe duração superior a uma hora sem reiniciar os minutos', () => {
    expect(time(3_684_000)).toBe('61:24')
  })

  it('preserva a mensagem acionável retornada pela API', async () => {
    const original = globalThis.fetch
    try {
      globalThis.fetch = async () => new Response(JSON.stringify({ error: { message: 'Modelo ausente' } }), { status: 400 })
      const engine = new Engine({ url: 'http://127.0.0.1:5000', token: 'test' })
      await expect(engine.request('/projects')).rejects.toThrow('Modelo ausente')
    } finally {
      globalThis.fetch = original
    }
  })
})
