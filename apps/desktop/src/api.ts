import { invoke } from '@tauri-apps/api/core'

export type Connection = { url: string; token: string }
export type Metadata = { duration_ms: number; width: number; height: number; fps: number | null; size: number; has_audio: boolean; video_codec: string; audio_codec: string | null }
export type Project = {
  id: string; title: string; source_kind: 'local' | 'url'; source_available?: boolean; updated_at: string;
  metadata: Metadata | null; analysis: { language: string; device: string; ranking?: string; segment_count: number; cpu_fallback: boolean; message?: string } | null
}
export type Cue = { id?: string; start_ms: number; end_ms: number; text: string; alignment_needs_review?: boolean }
export type Clip = {
  id: string; title: string; start_ms: number; end_ms: number; center_x: number; selected: boolean; preview_path: string | null; thumbnail_path: string | null;
  caption_style: 'white' | 'yellow'; reason?: string; score?: number; cues: Cue[]; updated_at: string
}
export type ExportFile = { path: string; size: number; duration_ms: number; encoder: string }
export type Job = {
  id: string; project_id: string; kind: string; status: 'queued' | 'running' | 'failed' | 'cancelled' | 'done';
  phase: string; progress: number | null; message: string; result: { files?: ExportFile[] } | null
}
export type Settings = {
  whisper_model: 'tiny' | 'base' | 'small' | 'medium'; language: 'auto' | 'pt'; use_gpu: boolean; use_llm: boolean;
  default_export_dir: string; default_caption_style: 'white' | 'yellow'
}
export type Diagnostics = {
  ffmpeg: { available: boolean; version?: string }; ffprobe: { available: boolean; version?: string };
  libass: boolean; libx264: boolean; nvenc: boolean; qsv: boolean; cuda_devices: number; whisper: boolean;
  models: string[]; ollama: { available: boolean; model: boolean }; memory: { total: number; available: number } | null;
  disk_free: number; recommendation: string
}

export function connect(): Promise<Connection> {
  if (import.meta.env.DEV && import.meta.env.VITE_ENGINE_URL && !('__TAURI_INTERNALS__' in window)) {
    return Promise.resolve({ url: import.meta.env.VITE_ENGINE_URL, token: import.meta.env.VITE_ENGINE_TOKEN })
  }
  return invoke<Connection>('engine_connection')
}

export class Engine {
  constructor(readonly connection: Connection) {}

  async request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
    const response = await fetch(this.connection.url + path, {
      method, headers: {
        Authorization: `Bearer ${this.connection.token}`,
        ...(data === undefined ? {} : { 'Content-Type': 'application/json' }),
      }, body: data === undefined ? undefined : JSON.stringify(data),
    }).catch(() => { throw new Error('Sem conexão com o motor local. Reabra o aplicativo.') })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error?.message ?? 'A solicitação falhou. Tente novamente.')
    return result as T
  }

  async media(project: string, kind: 'source' | 'thumbnail' | 'clip-thumbnail' | 'preview', clip?: string) {
    const { url } = await this.request<{ url: string }>(
      `/projects/${project}/media/${kind}${clip ? `?clip_id=${clip}` : ''}`,
    )
    return this.connection.url + url
  }
}

export function active(job: Job | null) {
  return job?.status === 'queued' || job?.status === 'running'
}

export function time(ms: number) {
  const seconds = Math.floor(ms / 1000)
  return [Math.floor(seconds / 60), seconds % 60].map(n => String(n).padStart(2, '0')).join(':')
}

export function size(bytes: number) {
  const divisor = bytes >= 1e9 ? 1e9 : 1e6
  return `${(bytes / divisor).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${divisor === 1e9 ? 'GB' : 'MB'}`
}
