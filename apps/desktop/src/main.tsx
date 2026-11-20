import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { open } from '@tauri-apps/plugin-dialog'
import { revealItemInDir } from '@tauri-apps/plugin-opener'
import Editor from './Editor'
import { active, connect, Engine, size, time, type Clip, type Diagnostics, type Job, type Project, type Settings } from './api'
import './style.css'

type JobResponse = { job_id: string }
const videoFilters = [{ name: 'Vídeos', extensions: ['mp4', 'mov', 'mkv', 'webm'] }]

function useMedia(api: Engine, project: Project | null, kind: 'source' | 'thumbnail' | 'preview', clipId?: string) {
  const [url, setUrl] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => {
    let current = true
    setUrl('')
    setUnavailable(false)
    if (!project?.metadata) return
    const update = () => api.media(project.id, kind, clipId).then(value => {
      if (current) { setUrl(value); setUnavailable(false) }
    }).catch(() => { if (current) setUnavailable(true) })
    void update()
    const interval = window.setInterval(update, 25 * 60 * 1000)
    return () => { current = false; window.clearInterval(interval) }
  }, [api, project?.id, project?.updated_at, kind, clipId])
  return { url, unavailable }
}

function ClipPlayback({ api, project, clip }: { api: Engine; project: Project; clip: Clip }) {
  const { url, unavailable } = useMedia(api, project, 'preview', clip.id)
  const [playError, setPlayError] = useState(false)
  if (unavailable || playError) return <p role="alert">Não foi possível reproduzir a prévia.</p>
  return url ? <video className="original" src={url} controls autoPlay playsInline onError={() => setPlayError(true)}
    aria-label={`Reprodução de ${clip.title}`} />
    : <p role="status">Carregando prévia…</p>
}

function Thumbnail({ api, item }: { api: Engine; item: Project }) {
  const { url } = useMedia(api, item, 'thumbnail')
  return url ? <img src={url} alt="" /> : <div className="thumb-placeholder" aria-hidden="true">▷</div>
}

function ClipThumbnail({ api, project, clip }: { api: Engine; project: Project; clip: Clip }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!clip.thumbnail_path) return
    let current = true
    void api.media(project.id, 'clip-thumbnail', clip.id).then(value => {
      if (current) setUrl(value)
    }).catch(() => {})
    return () => { current = false }
  }, [api, project.id, clip.id, clip.thumbnail_path])
  return url ? <img className="clip-thumb" src={url} alt="" /> : null
}

function Import({ api, busy, done, run }: {
  api: Engine; busy: boolean; done: (p: Project & JobResponse) => Promise<void>; run: (task: () => Promise<unknown>) => void
}) {
  const [kind, setKind] = useState<'local' | 'url'>('local')
  const [source, setSource] = useState('')
  const [title, setTitle] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const browserDev = import.meta.env.DEV && !('__TAURI_INTERNALS__' in window)
  function submit(event: FormEvent) {
    event.preventDefault()
    run(async () => done(await api.request('/projects', 'POST', {
      title: title.trim() || undefined, source_kind: kind, source_uri: source.trim(), authorized,
    })))
  }
  return <section className="panel import">
    <h2>Importar vídeo</h2>
    <div className="segments" aria-label="Origem do vídeo">
      <button aria-pressed={kind === 'local'} onClick={() => { setKind('local'); setSource('') }}>Arquivo local</button>
      <button aria-pressed={kind === 'url'} onClick={() => { setKind('url'); setSource('') }}>Link de vídeo</button>
    </div>
    <form className="form" onSubmit={submit}>
      <label>Nome do projeto<input value={title} onChange={e => setTitle(e.target.value)} maxLength={180} placeholder="Usar o nome do vídeo" /></label>
      {kind === 'local' ? <>
        <label>Arquivo de vídeo<input value={source} onChange={e => setSource(e.target.value)}
          readOnly={!browserDev} placeholder="MP4, MOV, MKV ou WEBM" /></label>
        {!browserDev && <button type="button" disabled={busy} onClick={() => run(async () => {
          const result = await open({ filters: videoFilters }); if (typeof result === 'string') setSource(result)
        })}>Escolher arquivo…</button>}
      </> : <>
        <label>Link HTTPS<input type="url" required value={source} placeholder="https://" onChange={e => setSource(e.target.value)} /></label>
        <label className="checkbox"><input type="checkbox" checked={authorized} onChange={e => setAuthorized(e.target.checked)} />
          Tenho permissão para editar o vídeo gravado.</label>
      </>}
      <button className="primary" disabled={busy || !source.trim() || (kind === 'url' && !authorized)}>Importar vídeo</button>
    </form>
  </section>
}

function Configuration({ api, settings, setSettings, disabled, run }: {
  api: Engine; settings: Settings; setSettings: (value: Settings) => void; disabled: boolean;
  run: (task: () => Promise<unknown>) => void
}) {
  const [draft, setDraft] = useState(settings)
  const [report, setReport] = useState<Diagnostics | null>(null)
  const [loading, setLoading] = useState(false)
  const update = (value: Partial<Settings>) => setDraft(current => ({ ...current, ...value }))
  useEffect(() => setDraft(settings), [settings])
  const scan = () => run(async () => {
    setLoading(true)
    try { setReport(await api.request('/diagnostics')) } finally { setLoading(false) }
  })
  return <div className="columns">
    <section className="panel">
      <h2>Configurações</h2>
      <fieldset disabled={disabled} className="form">
        <label>Perfil de processamento<select value={draft.use_gpu ? 'gpu' : 'cpu'} onChange={e => {
          const gpu = e.target.value === 'gpu'; update({ use_gpu: gpu, whisper_model: gpu ? 'small' : 'base' })
        }}><option value="cpu">Teste leve · CPU / int8</option><option value="gpu">Produção GPU · CUDA / NVENC</option></select></label>
        <label>Modelo de voz<select value={draft.whisper_model} onChange={e => update({ whisper_model: e.target.value as Settings['whisper_model'] })}>
          {['tiny', 'base', 'small', 'medium'].map(model => <option key={model}>{model}</option>)}
        </select></label>
        <label>Idioma de análise<select value={draft.language} onChange={e => update({ language: e.target.value as Settings['language'] })}>
          <option value="auto">Automático</option><option value="pt">Português</option></select></label>
        <label className="checkbox"><input type="checkbox" checked={draft.use_llm} onChange={e => update({ use_llm: e.target.checked })} /> Usar Ollama com Qwen 2.5 3B quando disponível</label>
        <label>Estilo padrão<select value={draft.default_caption_style} onChange={e => update({ default_caption_style: e.target.value as Settings['default_caption_style'] })}>
          <option value="white">Branco · destaque amarelo</option><option value="yellow">Amarelo · destaque ciano</option></select></label>
        <button onClick={() => run(async () => {
          const path = await open({ directory: true }); if (typeof path === 'string') update({ default_export_dir: path })
        })}>Pasta de exportação…</button>
        {draft.default_export_dir && <p className="path">{draft.default_export_dir}</p>}
        <button className="primary" onClick={() => run(async () => setSettings(await api.request('/settings', 'PATCH', draft)))}>Salvar configurações</button>
      </fieldset>
    </section>
    <section className="panel">
      <div className="section-head"><h2>Diagnóstico</h2><button disabled={disabled || loading} onClick={scan}>{loading ? 'Verificando…' : 'Executar diagnóstico'}</button></div>
      {report && <>
        <p className="notice">{report.recommendation}</p>
        <dl className="diagnostics">
          <dt>FFmpeg</dt><dd>{report.ffmpeg.version ?? 'Ausente'}</dd>
          <dt>FFprobe</dt><dd>{report.ffprobe.version ?? 'Ausente'}</dd>
          <dt>Legendas libass</dt><dd>{report.libass ? 'Disponível' : 'Ausente'}</dd>
          <dt>H.264 em CPU</dt><dd>{report.libx264 ? 'Disponível' : 'Ausente'}</dd>
          <dt>NVENC / Quick Sync</dt><dd>{report.nvenc ? 'NVENC funcional' : 'NVENC indisponível'} · {report.qsv ? 'QSV funcional' : 'QSV indisponível'}</dd>
          <dt>CUDA</dt><dd>{report.cuda_devices} dispositivo(s) detectado(s)</dd>
          <dt>Whisper</dt><dd>{!report.whisper ? 'Dependência ausente' : report.models.join(', ') || 'Sem modelos baixados'}</dd>
          <dt>Ollama</dt><dd>{report.ollama.model ? 'Qwen disponível' : report.ollama.available ? 'Modelo ausente' : 'Indisponível'}</dd>
          <dt>RAM livre</dt><dd>{report.memory ? size(report.memory.available) : 'Indisponível'}</dd>
          <dt>Disco livre</dt><dd>{size(report.disk_free)}</dd>
        </dl>
      </>}
    </section>
  </div>
}

function Studio({ api }: { api: Engine }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [project, setProject] = useState<Project | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [view, setView] = useState<'home' | 'import' | 'settings' | 'project'>('home')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [exporting, setExporting] = useState<Clip[] | null>(null)
  const [directory, setDirectory] = useState('')
  const [filename, setFilename] = useState('')
  const [preset, setPreset] = useState<'1080p' | '720p'>('1080p')
  const [analysis, setAnalysis] = useState({ clip_count: 5, min_seconds: 20, max_seconds: 45, download_model: false })
  const { url: source } = useMedia(api, project, 'source')
  const [sourceError, setSourceError] = useState(false)
  const busy = pending || active(job)
  const clip = clips.find(item => item.id === editing)

  const report = (problem: unknown) => setError(problem instanceof Error ? problem.message : 'A operação falhou.')
  const list = useCallback(async () => { setProjects(await api.request('/projects')) }, [api])
  const details = useCallback(async (id: string) => {
    const [item, data] = await Promise.all([
      api.request<Project>(`/projects/${id}`), api.request<Clip[]>(`/projects/${id}/clips`),
    ])
    return { item, data }
  }, [api])

  const run = async (task: () => Promise<unknown>) => {
    setPending(true); setError('')
    try { await task() } catch (problem) { report(problem) } finally { setPending(false) }
  }

  useEffect(() => {
    void list().catch(report)
    void api.request<Settings>('/settings').then(setSettings).catch(report)
    void api.request<Job[]>('/jobs').then(items => { if (items[0]) setJob(items[0]) }).catch(report)
  }, [api, list])

  useEffect(() => {
    setProject(null); setClips([]); setEditing(null); setPlaying(null); setSourceError(false)
    if (!selected) return
    let current = true
    void details(selected).then(({ item, data }) => {
      if (current) { setProject(item); setClips(data) }
    }).catch(problem => { if (current) report(problem) })
    return () => { current = false }
  }, [selected, details])

  const jobId = job?.id
  const isActive = active(job)
  useEffect(() => {
    if (!jobId || !isActive) return
    let current = true
    let timer = 0
    async function poll() {
      try {
        const latest = await api.request<Job>(`/jobs/${jobId}`)
        if (!current) return
        if (active(latest)) {
          setJob(latest)
          timer = window.setTimeout(poll, 700)
        } else {
          await list()
          if (latest.project_id === selected) {
            const { item, data } = await details(latest.project_id)
            if (current) { setProject(item); setClips(data) }
          }
          if (current) setJob(latest)
        }
      } catch (problem) {
        if (current) { report(problem); timer = window.setTimeout(poll, 1600) }
      }
    }
    void poll()
    return () => { current = false; window.clearTimeout(timer) }
  }, [api, details, list, jobId, isActive, selected])

  function showProject(id: string) {
    setSelected(id); setView('project'); setError(''); setExporting(null)
  }
  async function track(id: string, currentProject = selected) {
    const next = await api.request<Job>(`/jobs/${id}`)
    setJob(next)
    if (!active(next) && currentProject === next.project_id) {
      const { item, data } = await details(next.project_id)
      setProject(item); setClips(data)
    }
    await list()
  }

  async function saveClip(draft: Clip, subtitles: boolean, offset: number) {
    setError(''); setPending(true)
    try {
      const data = await api.request<Clip>(`/clips/${draft.id}`, 'PATCH', {
        start_ms: draft.start_ms, end_ms: draft.end_ms, title: draft.title.trim(), center_x: draft.center_x,
        caption_style: draft.caption_style, framing: draft.framing, effects: draft.effects,
        subtitles: subtitles ? { cues: draft.cues, offset_ms: offset } : undefined,
      })
      setClips(current => current.map(item => item.id === data.id ? data : item))
      return data
    } catch (problem) {
      report(problem); throw problem
    } finally { setPending(false) }
  }

  const renderPreview = (item: Clip) => run(async () => {
    const response = await api.request<JobResponse>(`/clips/${item.id}/preview`, 'POST')
    await track(response.job_id)
  })

  function showExport(items: Clip[]) {
    setDirectory(settings?.default_export_dir ?? '')
    setFilename('')
    setExporting(items)
  }

  return <div className="layout">
    <aside className="sidebar">
      <button className="brand" disabled={pending} onClick={() => { setView('home'); setSelected(null); setExporting(null) }}><span className="mark">▶</span> Clip Factory</button>
      <nav aria-label="Menu principal">
        <button disabled={pending} aria-current={view === 'home' ? 'page' : undefined} onClick={() => { setSelected(null); setView('home'); setExporting(null) }}>Projetos</button>
        <button disabled={pending} aria-current={view === 'import' ? 'page' : undefined} onClick={() => setView('import')}>Novo projeto</button>
        <button disabled={pending} aria-current={view === 'settings' ? 'page' : undefined} onClick={() => setView('settings')}>Configurações</button>
      </nav>
      <div className="sidebar-foot"><span /> Motor local conectado</div>
    </aside>
    <main>
      <header><h1>{view === 'project' ? project?.title ?? 'Projeto' : { home: 'Seus projetos', import: 'Novo projeto', settings: 'Configurações' }[view]}</h1>
        {view === 'home' && <button className="primary" onClick={() => setView('import')}>Novo projeto</button>}</header>
      {error && <p className="error" role="alert">{error}</p>}
      {job && <section className={`job ${job.status === 'failed' ? 'error' : ''}`} aria-live="polite">
        <div className="section-head"><strong>{job.message}</strong>
          {active(job) ? <button onClick={() => void run(() => api.request(`/jobs/${job.id}/cancel`, 'POST'))}>Cancelar</button>
            : <button onClick={() => setJob(null)}>Fechar aviso</button>}</div>
        {active(job) && <progress aria-label="Progresso da etapa" max={1} value={job.progress ?? undefined} />}
        {job.result?.files?.map(file => <p className="export-result" key={file.path}><span className="path">{file.path} · {size(file.size)} · {time(file.duration_ms)}</span>
          <button onClick={() => void run(() => revealItemInDir(file.path))}>Abrir pasta</button></p>)}
      </section>}
      {view === 'home' && <>
        {projects.length === 0 && <section className="panel empty"><h2>Comece com um vídeo</h2><p>Importe um arquivo ou link para criar o primeiro projeto.</p><button className="primary" onClick={() => setView('import')}>Importar vídeo</button></section>}
        <div className="project-grid">{projects.map(item => <button className="project-card" key={item.id} onClick={() => showProject(item.id)}>
          <Thumbnail api={api} item={item} /><strong>{item.title}</strong><span>{item.metadata ? time(item.metadata.duration_ms) : 'Fonte pendente'} · {new Date(item.updated_at).toLocaleDateString('pt-BR')}</span>
        </button>)}</div>
      </>}
      {view === 'import' && <Import api={api} busy={busy} run={run} done={async item => { showProject(item.id); await track(item.job_id, item.id) }} />}
      {view === 'settings' && settings && <Configuration api={api} settings={settings} setSettings={setSettings} disabled={busy} run={run} />}
      {view === 'project' && project && <>
        <div className="project-actions">
          <button disabled={busy} onClick={() => void run(async () => {
            const title = window.prompt('Nome do projeto', project.title)?.trim()
            if (!title || title === project.title) return
            await api.request(`/projects/${project.id}`, 'PATCH', { title })
            const { item } = await details(project.id); setProject(item); await list()
          })}>Renomear</button>
          {project.source_kind === 'local' && !project.source_available &&
            <button disabled={busy} onClick={() => void run(async () => {
              const path = await open({ filters: videoFilters }); if (typeof path !== 'string') return
              await api.request(`/projects/${project.id}`, 'PATCH', { source_uri: path })
              const { item } = await details(project.id); setProject(item); setSourceError(false); await list()
            })}>Localizar arquivo</button>}
          <button disabled={busy} onClick={() => void run(async () => {
            if (!window.confirm(`Excluir o projeto “${project.title}” e seus arquivos de trabalho?`)) return
            await api.request(`/projects/${project.id}`, 'DELETE')
            setView('home'); setSelected(null); await list()
          })}>Excluir projeto</button>
        </div>
        {!project.metadata ? <section className="panel"><p>A fonte ainda não foi importada.</p>
          <button disabled={busy} onClick={() => void run(async () => track((await api.request<JobResponse>(`/projects/${project.id}/import`, 'POST')).job_id))}>Tentar novamente</button></section>
          : <>
            <div className="columns">
              <section className="panel"><h2>Vídeo original</h2>
                {source && !sourceError ? <video className="original" controls preload="metadata" src={source} onError={() => setSourceError(true)} aria-label="Vídeo original" />
                  : <p className="muted">{sourceError ? 'Formato indisponível no player original. A prévia do corte usa H.264.' : 'A fonte está indisponível ou ainda está carregando.'}</p>}
                <p>{project.metadata.width} × {project.metadata.height} · {time(project.metadata.duration_ms)} · {size(project.metadata.size)} · {project.metadata.has_audio ? 'Com áudio' : 'Sem áudio'}</p>
              </section>
              <section className="panel"><h2>Análise de fala</h2>
                {project.analysis && <p className="notice">{project.analysis.message} {project.analysis.segment_count} segmentos em {project.analysis.language}. {project.analysis.device.toUpperCase()}{project.analysis.cpu_fallback ? ' (fallback)' : ''} · {project.analysis.ranking === 'hybrid' ? 'Ollama + heurísticas' : project.analysis.ranking === 'heuristic_fallback' ? 'Heurísticas · Ollama indisponível' : 'Heurísticas'}</p>}
                {!project.metadata.has_audio ? <p>Este vídeo não tem áudio. Crie um corte manual.</p> :
                  <fieldset className="form" disabled={busy || !settings || !project.source_available}>
                    <div className="inline-fields">
                      <label>Até quantos cortes<select value={analysis.clip_count} onChange={e => setAnalysis({ ...analysis, clip_count: +e.target.value })}>
                        {[3, 4, 5].map(n => <option key={n}>{n}</option>)}</select></label>
                      <label>Mínimo (s)<input type="number" min="15" max="60" value={analysis.min_seconds} onChange={e => setAnalysis({ ...analysis, min_seconds: +e.target.value })} /></label>
                      <label>Máximo (s)<input type="number" min="15" max="60" value={analysis.max_seconds} onChange={e => setAnalysis({ ...analysis, max_seconds: +e.target.value })} /></label>
                    </div>
                    <label className="checkbox"><input type="checkbox" checked={analysis.download_model} onChange={e => setAnalysis({ ...analysis, download_model: e.target.checked })} />
                      Permitir download do modelo Whisper {settings?.whisper_model}, se necessário.</label>
                    <button className="primary" onClick={() => void run(async () => track((await api.request<JobResponse>(`/projects/${project.id}/analyze`, 'POST', {
                      ...analysis, language: settings?.language, use_llm: settings?.use_llm,
                    })).job_id))}>Gerar cortes automáticos</button>
                  </fieldset>}
              </section>
            </div>
            <section className="panel">
              <div className="section-head"><h2>Cortes</h2><div className="project-actions">
                <button disabled={busy} onClick={() => void run(async () => {
                  const item = await api.request<Clip>(`/projects/${project.id}/clips`, 'POST', {})
                  setClips(current => [...current, item]); setPlaying(null); setEditing(item.id)
                })}>Criar corte manual</button>
                <button disabled={busy || !clips.some(item => item.selected)} onClick={() => showExport(clips.filter(item => item.selected))}>Exportar selecionados</button>
              </div></div>
              {clips.length === 0 && <p className="muted">Gere sugestões ou crie um corte manual.</p>}
              <div className="clip-grid">{clips.map(item => <article className="clip-card" key={item.id}>
                {playing === item.id && item.preview_path
                  ? <ClipPlayback key={item.preview_path} api={api} project={project} clip={item} />
                  : <ClipThumbnail api={api} project={project} clip={item} />}
                <label className="checkbox"><input type="checkbox" aria-label={`Selecionar ${item.title}`} checked={Boolean(item.selected)} disabled={busy} onChange={e => {
                  const checked = e.target.checked
                  void run(async () => {
                    const updated = await api.request<Clip>(`/clips/${item.id}`, 'PATCH', { selected: checked })
                    setClips(current => current.map(other => other.id === item.id ? updated : other))
                  })
                }} /> Selecionar para exportação</label>
                <h3>{item.title}</h3><p>{time(item.start_ms)} – {time(item.end_ms)} · {(item.end_ms - item.start_ms) / 1000} s</p>
                {item.reason && <p>{item.reason}</p>}
                <div className="project-actions">
                  {playing === item.id && item.preview_path
                    ? <button onClick={() => setPlaying(null)}>Fechar prévia</button>
                    : <button disabled={!item.preview_path && (busy || !project.source_available)} onClick={() => {
                      setPlaying(item.id)
                      if (!item.preview_path) void renderPreview(item)
                    }}>{playing === item.id && busy ? 'Preparando prévia…' : 'Reproduzir corte'}</button>}
                  <button aria-pressed={editing === item.id} onClick={() => { setPlaying(null); setEditing(item.id) }}>Editar</button>
                </div>
              </article>)}</div>
            </section>
            {clip && <Editor key={clip.id} clip={clip} project={project} api={api} disabled={busy} save={saveClip}
              preview={renderPreview}
              exportClip={item => showExport([item])} />}
          </>}
      </>}
      {view === 'project' && exporting && project && <section className="panel form export-panel" aria-label="Exportar MP4">
        <div className="section-head"><h2>Exportar MP4</h2><button onClick={() => setExporting(null)}>Fechar</button></div>
        {!!(import.meta.env.DEV && !('__TAURI_INTERNALS__' in window)) ? <label>Pasta de saída<input value={directory} onChange={e => setDirectory(e.target.value)} /></label>
          : <><button onClick={() => void run(async () => {
            const path = await open({ directory: true }); if (typeof path === 'string') setDirectory(path)
          })}>Escolher pasta de saída…</button>{directory && <p className="path">{directory}</p>}</>}
        {exporting.length === 1 && <label>Nome do arquivo<input value={filename} maxLength={180} onChange={e => setFilename(e.target.value)} placeholder={exporting[0].title} /></label>}
        <label>Resolução<select value={preset} onChange={e => setPreset(e.target.value as typeof preset)}>
          <option value="1080p">1080 × 1920</option><option value="720p">720 × 1280</option>
        </select></label>
        <button className="primary" disabled={busy || !directory} onClick={() => void run(async () => {
          const response = await api.request<JobResponse>('/exports', 'POST', {
            project_id: project.id, clip_ids: exporting.map(item => item.id), output_dir: directory, preset, filename: filename.trim() || undefined,
          })
          setExporting(null); await track(response.job_id)
        })}>Exportar {exporting.length === 1 ? '1 corte' : `${exporting.length} cortes`}</button>
      </section>}
    </main>
  </div>
}

function App() {
  const [engine, setEngine] = useState<Engine | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    void connect().then(async connection => {
      const api = new Engine(connection)
      await api.request('/health')
      setEngine(api)
    }).catch(() => setError('Não foi possível iniciar a sessão local. Reabra o aplicativo ou execute o diagnóstico de instalação.'))
  }, [])
  if (engine) return <Studio api={engine} />
  return <main><h1>Clip Factory</h1><p role={error ? 'alert' : 'status'}>{error || 'Conectando ao motor local…'}</p></main>
}

createRoot(document.getElementById('root')!).render(<App />)
