import { useEffect, useState } from 'react'
import { type Clip, type Cue, type Engine, type Project, time } from './api'

type Props = {
  clip: Clip; project: Project; api: Engine; disabled: boolean;
  save: (clip: Clip, subtitleEdit: boolean, offset: number) => Promise<Clip>;
  preview: (clip: Clip) => Promise<void>; exportClip: (clip: Clip) => void;
}

function Seconds({ label, value, max, update }: {
  label: string; value: number; max?: number; update: (ms: number) => void
}) {
  return <label>{label}<input type="number" min="0" max={max === undefined ? undefined : max / 1000}
    step="0.1" value={value / 1000} onChange={event => update(Math.round(Number(event.target.value) * 1000))} /></label>
}

export default function Editor({ clip, project, api, disabled, save, preview, exportClip }: Props) {
  const [draft, setDraft] = useState(clip)
  const [changed, setChanged] = useState(false)
  const [cueChanged, setCueChanged] = useState(false)
  const [offset, setOffset] = useState(0)
  const [previewUrl, setPreviewUrl] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setDraft(clip)
    setChanged(false)
    setCueChanged(false)
    setOffset(0)
  }, [clip.id, clip.updated_at])

  useEffect(() => {
    let valid = true
    setPreviewUrl('')
    if (!clip.preview_path) return
    const update = () => api.media(project.id, 'preview', clip.id).then(url => {
      if (valid) setPreviewUrl(url)
    }).catch(() => { if (valid) setPreviewUrl('') })
    void update()
    const interval = window.setInterval(update, 25 * 60 * 1000)
    return () => { valid = false; window.clearInterval(interval) }
  }, [api, project.id, clip.id, clip.preview_path])

  const duration = project.metadata?.duration_ms ?? 0
  const length = draft.end_ms - draft.start_ms
  const edit = (fields: Partial<Clip>) => {
    setChanged(true)
    setSaved(false)
    setDraft(current => ({ ...current, ...fields }))
  }
  const updateCue = (index: number, fields: Partial<Cue>) => {
    setCueChanged(true)
    edit({ cues: draft.cues.map((cue, i) => i === index ? { ...cue, ...fields } : cue) })
  }
  const submit = async () => {
    const updated = await save(draft, cueChanged || offset !== 0, offset)
    setDraft(updated)
    setChanged(false)
    setCueChanged(false)
    setOffset(0)
    setSaved(true)
    return updated
  }
  const saveAnd = async (then: (item: Clip) => unknown) => {
    try {
      await then(changed ? await submit() : clip)
    } catch {
      // The parent's live region displays API errors.
    }
  }

  return <section className="panel editor">
    <div className="section-head"><div><h2>Editor de corte</h2><p>{time(draft.start_ms)} – {time(draft.end_ms)} · {Math.max(0, length) / 1000} s</p></div>
      <button className="primary" disabled={disabled || !changed} onClick={() => void saveAnd(() => undefined)}>Salvar</button></div>
    <div className="editor-grid">
      <div>
        <div className="portrait">
          {previewUrl ? <video controls preload="metadata" src={previewUrl} aria-label="Prévia vertical do corte" />
            : <span>Gere uma prévia<br />para reproduzir o corte</span>}
        </div>
        <button className="wide" disabled={disabled} onClick={() => void saveAnd(preview)}>Atualizar prévia</button>
        {changed && <p className="muted">As alterações serão aplicadas à próxima prévia.</p>}
        {saved && <p role="status">Alterações salvas.</p>}
      </div>
      <fieldset disabled={disabled} className="form">
        <label>Título<input value={draft.title} maxLength={180} onChange={event => edit({ title: event.target.value })} /></label>
        <div className="inline-fields">
          <Seconds label="Início no vídeo (s)" value={draft.start_ms} max={duration} update={start_ms => edit({ start_ms })} />
          <Seconds label="Fim no vídeo (s)" value={draft.end_ms} max={duration} update={end_ms => edit({ end_ms })} />
        </div>
        <div className="timeline" aria-label="Intervalo do corte">
          <div style={{ left: `${100 * draft.start_ms / duration}%`, right: `${100 - 100 * draft.end_ms / duration}%` }} />
          <input type="range" aria-label="Arrastar início" min="0" max={duration} step="100" value={draft.start_ms}
            onChange={event => edit({ start_ms: Math.min(draft.end_ms - 1, +event.target.value) })} />
          <input type="range" aria-label="Arrastar fim" min="0" max={duration} step="100" value={draft.end_ms}
            onChange={event => edit({ end_ms: Math.max(draft.start_ms + 1, +event.target.value) })} />
        </div>
        <label>Enquadramento horizontal · {Math.round(draft.center_x * 100)}%
          <input aria-label="Enquadramento horizontal" type="range" min="0" max="1" step="0.01" value={draft.center_x}
            onChange={event => edit({ center_x: +event.target.value })} />
        </label>
        <div className="inline-fields">
          <label>Estilo das legendas<select value={draft.caption_style} onChange={event => edit({ caption_style: event.target.value as Clip['caption_style'] })}>
            <option value="white">Branco com contorno</option><option value="yellow">Amarelo com contorno</option>
          </select></label>
          <label>Deslocamento global (ms)<input type="number" min="-60000" max="60000" step="10" value={offset} onChange={event => {
            setOffset(Math.round(Number(event.target.value))); setChanged(true); setSaved(false)
          }} /></label>
        </div>
        <div className="section-head"><h3>Legendas</h3><button onClick={() => {
          setCueChanged(true)
          edit({ cues: [...draft.cues, { start_ms: 0, end_ms: Math.min(length, 1500), text: '' }] })
        }}>Adicionar legenda</button></div>
        {draft.cues.length === 0 && <p className="muted">Este corte ainda não tem legendas.</p>}
        <div className="cues">
          {draft.cues.map((cue, i) => <div className="cue" key={cue.id ?? i}>
            <div className="inline-fields">
              <Seconds label={`Início da legenda ${i + 1} (s)`} value={cue.start_ms} max={length} update={start_ms => updateCue(i, { start_ms })} />
              <Seconds label={`Fim da legenda ${i + 1} (s)`} value={cue.end_ms} max={length} update={end_ms => updateCue(i, { end_ms })} />
            </div>
            <label>Texto da legenda {i + 1}<textarea maxLength={240} value={cue.text} onChange={event => updateCue(i, { text: event.target.value })} /></label>
            {cue.alignment_needs_review && <p className="notice">Confira a sincronização deste trecho.</p>}
            <button onClick={() => { setCueChanged(true); edit({ cues: draft.cues.filter((_, n) => n !== i) }) }}>Remover legenda</button>
          </div>)}
        </div>
        <button className="primary" onClick={() => void saveAnd(exportClip)}>Exportar MP4</button>
      </fieldset>
    </div>
  </section>
}
