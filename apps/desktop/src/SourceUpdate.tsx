import { invoke, isTauri } from '@tauri-apps/api/core'
import { useEffect, useRef, useState } from 'react'
import type { Engine, Job } from './api'

export default function SourceUpdate({ api, busy, visible }: { api: Engine; busy: boolean; visible: boolean }) {
  const [enabled, setEnabled] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (!isTauri()) return
    void invoke<boolean>('source_updates_enabled').then(setEnabled).catch(() => {})
  }, [])

  async function update() {
    const progress = dialog.current
    if (!progress || progress.open || busy) return
    setStatus('')
    setError('')
    progress.showModal()
    try {
      const jobs = await api.request<Job[]>('/jobs')
      if (jobs.length) {
        setError('Aguarde o fim do processamento para atualizar.')
        return
      }
      const updated = await invoke<boolean>('update_from_github')
      if (!updated) setStatus('O Clip Factory já está atualizado.')
    } catch (problem) {
      setError(typeof problem === 'string' ? problem : 'Não foi possível atualizar pelo GitHub. Tente novamente.')
    } finally {
      progress.close()
    }
  }

  if (!enabled) return null
  return <section className="panel" aria-label="Atualização pelo GitHub" hidden={!visible}>
    <button disabled={busy} onClick={() => void update()}>Atualizar pelo GitHub</button>
    {status && <p role="status">{status}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <dialog ref={dialog} className="panel update-dialog" aria-labelledby="source-update-progress" onCancel={event => event.preventDefault()}>
      <p id="source-update-progress" role="status">Verificando e preparando a versão do GitHub…</p>
      <progress aria-label="Atualização pelo GitHub" />
    </dialog>
  </section>
}
