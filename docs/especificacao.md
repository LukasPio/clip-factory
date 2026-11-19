# Especificação técnica — MVP de editor automático de vídeos com IA

**Versão:** 1.1  
**Data:** 19/11/2026  
**Status:** pronta para implementação por agente de programação  
**Plataforma inicial:** Windows 10/11 x64  
**Hardware de desenvolvimento e testes principais:** Intel Core i7 de 11ª geração (modelo exato a confirmar), Intel Iris Xe integrada, 16 GB RAM, Windows 10/11 x64. **O fluxo P0 deve funcionar integralmente sem CUDA.**  
**Hardware de produção/processamento pesado após validação:** NVIDIA RTX 2060 Super (8 GB VRAM), AMD Ryzen 5 5600G (6C/12T), 32 GB RAM, Windows 10/11 x64. CUDA e NVENC são acelerações opcionais, não pré-requisitos para iniciar o aplicativo.  
**Modelo de produto:** aplicativo desktop local-first, sem servidor remoto obrigatório  
**Linguagem da interface:** português brasileiro

## 1. Missão do agente

Construir um aplicativo desktop funcional que importe um vídeo local ou um vídeo gravado acessível por URL, transcreva o áudio, proponha cortes relevantes para TikTok/Reels/Shorts, permita revisá-los/ajustá-los e exporte MP4 vertical com legendas embutidas. **Entregar um fluxo real de ponta a ponta; não entregar apenas uma interface estática ou resultados simulados.**

O aplicativo deve funcionar sem conta, pagamento, API paga, banco de dados na nuvem ou envio dos vídeos para serviços externos. A internet é permitida para baixar vídeos autorizados, dependências e modelos na primeira utilização. O modelo de linguagem local é um aprimoramento do ranking, não uma dependência que bloqueia todo o fluxo.

## 2. Escopo obrigatório e não escopo

### 2.1 Incluído no MVP (P0)

1. Criar, abrir, renomear e excluir projetos locais.
2. Importar arquivo de vídeo local por seletor de arquivo: MP4, MOV, MKV e WEBM, conforme codecs suportados pelo FFmpeg.
3. Importar URL pública de vídeo **já gravado** por `yt-dlp` quando o acesso for autorizado e tecnicamente suportado; mostrar erro claro se a plataforma bloquear.
4. Inspecionar duração, codecs, resolução, FPS, tamanho e presença de áudio por `ffprobe`.
5. Extrair áudio e transcrever com `faster-whisper` local; idioma automático com preferência por `pt`; guardar segmentos e, quando disponíveis, tempos por palavra obrigatórios para geração de legendas sincronizadas (com estratégia de recuperação quando o alinhamento falhar).
6. Identificar de 3 a 5 candidatos a cortes com base em transcrição, regras de pontuação e, se disponível, modelo local `qwen2.5:3b` via Ollama.
7. Exibir lista dos cortes com título sugerido, intervalo, duração, motivo textual de seleção e prévia reproduzível.
8. Editar manualmente início/fim, título, posição horizontal do enquadramento e texto/tempo das legendas.
9. Renderizar vídeos verticais 9:16 com legendas sincronizadas com a fala, queimadas no vídeo, áudio preservado, formato MP4/H.264/AAC, 1080×1920 a 30 FPS por padrão.
10. Exportar um corte isoladamente ou todos os cortes selecionados para uma pasta escolhida.
11. Mostrar status por etapa, barra de progresso aproximada, erros acionáveis, cancelamento e histórico local de projetos.
12. Realizar diagnóstico de FFmpeg, FFprobe, NVENC, CUDA/CTranslate2, Ollama/modelo, memória e espaço livre; oferecer CPU/fallback.
13. Persistir projetos, transcrições, cortes e edições entre reinicializações.
14. Incluir testes automatizados e instruções de instalação, desenvolvimento, empacotamento e troubleshooting.

### 2.2 Fora do MVP (P1/P2)

- Captura e corte de transmissões **ao vivo em tempo real**.
- Publicação automática em TikTok, Instagram ou YouTube.
- Conta, assinatura, colaboração, sincronização na nuvem ou telemetria.
- Edição multicamadas, máscaras, keyframes, efeitos complexos ou editor equivalente ao CapCut.
- Diarização perfeita, tradução, clonagem de voz, geração de voz ou música.
- Detecção confiável de eventos visuais de gameplay sem áudio/fala. O ranking inicial usa principalmente o áudio/transcrição.
- Seguimento automático sofisticado de múltiplas pessoas. No MVP, o enquadramento é manual e o centro é aplicado por padrão.
- DRM, autenticação privada, evasão de paywall ou download contrário a direitos/termos da fonte.

## 3. Critério de sucesso do MVP

Dado um vídeo gravado, com áudio falado em português e entre 5 e 60 minutos, o usuário consegue importá-lo, iniciar análise, receber candidatos válidos, editar um dos cortes e exportar um MP4 vertical 1080×1920 com legendas audíveis/legíveis sem usar terminal. A qualidade editorial da escolha dos melhores momentos será avaliada manualmente e melhorada em versões posteriores; **não prometer identificação perfeita de momentos engraçados ou importantes**.

Os vídeos até 60 minutos são a faixa-alvo de teste, não um limite rígido de software. Para entradas mais longas, mostrar estimativas/avisos de espaço e permitir processamento se houver recursos.

## 4. Arquitetura e stack

| Camada | Tecnologia | Responsabilidade |
|---|---|---|
| Shell desktop | Tauri 2 (Rust) | Janela, diálogos nativos, inicialização/encerramento do backend local e permissões |
| Frontend | React + TypeScript + Vite | Telas, player, galeria, editor, configurações |
| Estilo/UI | Tailwind CSS + componentes acessíveis | Interface dark responsiva para 1366×768 e 1920×1080 |
| Estado/dados | TanStack Query + Zustand | Consulta de API, estado do editor |
| Backend | Python 3.11 + FastAPI + Pydantic | API local, orquestração de processos e validação |
| Banco | SQLite + SQLAlchemy | Projetos, tarefas, cortes, legendas e configurações |
| Vídeo | FFmpeg/FFprobe | Metadados, extração, proxies, montagem, exportação |
| Importação URL | yt-dlp | Vídeos públicos finalizados, sujeitos à disponibilidade da fonte |
| Transcrição | faster-whisper/CTranslate2 | Reconhecimento de fala e timestamps |
| Ranking IA opcional | Ollama + qwen2.5:3b | Pontuação e explicação textual de trechos |
| Testes | pytest + Vitest + Playwright | Backend, interface e fluxo integrado |

### 4.1 Decisões de arquitetura obrigatórias

- Uma única tarefa pesada de IA/renderização por vez. Processar transcrição, ranking e exportação em sequência, liberando memória/modelos ao terminar.
- Backend escuta **somente** `127.0.0.1` em porta aleatória, iniciada e supervisionada pelo Tauri; token aleatório por sessão para chamadas HTTP, restrição de `Origin/CORS` e limpeza no fechamento. Jamais abrir API na rede local.
- Em desenvolvimento, permitir iniciar o backend manualmente; na distribuição, empacotar Python como sidecar (por exemplo, PyInstaller) e incluir executáveis compatíveis de FFmpeg/FFprobe observando licenças. Não depender de Python instalado pelo usuário final.
- **Ollama como dependência opcional externa** na primeira versão empacotada: detectar e orientar instalação/modelo, sem embuti-lo silenciosamente; funcionar com ranking heurístico caso esteja ausente.
- Modelos de transcrição baixados no primeiro uso após consentimento, armazenados no diretório do aplicativo, com indicador de download e opção CPU. Nunca presumir que GPU está funcional só porque uma placa NVIDIA foi detectada.
- Usar chamadas de processos com arrays de argumentos (sem `shell=True`) e caminhos controlados; nunca concatenar URLs/paths em comandos shell.
- Colocar arquivos e bancos em pastas locais de dados do usuário; não gravar em diretórios de instalação protegidos.

### 4.2 Fluxo de dados

```text
Tauri/React
  └── API FastAPI local autenticada
       ├── SQLite (projetos, jobs, clips, cues)
       ├── Importador (arquivo local ou yt-dlp)
       ├── FFprobe (metadados)
       ├── FFmpeg (áudio WAV mono 16 kHz)
       ├── faster-whisper (transcrição + timestamps)
       ├── Gerador de janelas candidatas
       ├── Ranking (regras + Qwen local opcional)
       ├── Gerador de thumbnails/prévias
       └── FFmpeg (MP4 9:16 + legendas .ASS)
```

## 5. Pastas e organização do repositório

```text
video-ai-mvp/
  README.md
  .gitignore
  .env.example
  docs/
    architecture.md
    user-flow.md
    troubleshooting.md
  apps/desktop/
    package.json
    src/
      app/
      pages/
      components/
        ImportView.tsx
        ProjectList.tsx
        AnalysisProgress.tsx
        ClipGallery.tsx
        ClipEditor.tsx
        VideoPreview.tsx
        SubtitleEditor.tsx
        ExportDialog.tsx
        DiagnosticsView.tsx
      lib/api.ts
      types/
      styles/
    src-tauri/
      src/
      tauri.conf.json
      capabilities/
      binaries/   # gerados no build; não commitar binários enormes
  services/engine/
    pyproject.toml
    app/
      main.py
      config.py
      api/
      models/
      db/
      schemas/
      jobs/
      services/
        probe.py
        downloader.py
        audio.py
        transcription.py
        candidate_windows.py
        ranking.py
        subtitle.py
        preview.py
        export.py
        diagnostics.py
      security/
    tests/
  scripts/
    dev.ps1
    build-windows.ps1
    doctor.ps1
  fixtures/   # arquivos pequenos sintéticos, autorizados
```

## 6. Jornada e telas

### T1 — Início e projetos

- Botão **Novo projeto**; lista com nome, data, duração, status e miniatura.
- Ações: abrir, renomear, excluir (com confirmação) e localizar arquivos ausentes.
- Indicação amigável da disponibilidade de IA/GPU em configurações; sem obrigar login.

### T2 — Importar

- Abas **Arquivo local** e **Link de vídeo**.
- Local: abrir seletor nativo; não fazer upload para backend remoto.
- URL: validar `https://` (e `http://` apenas se explicitamente permitido), bloquear endereços privados/localhost, detectar vídeo não disponível, rejeitar playlists e lives ativas no MVP.
- Confirmar que o usuário possui permissão para editar o material; respeitar regras da plataforma, sem contornar DRM.
- Exibir título, duração, resolução, áudio detectado e espaço livre estimado antes da análise.

### T3 — Análise

- Botão **Gerar cortes automáticos** e opções: quantidade 3/4/5 (padrão 5), duração desejada 20–45 s (limites editáveis 15–60 s), idioma automático/PT-BR, modo de IA (híbrido ou heurístico).
- Etapas exibidas: importação/download, inspeção, áudio, transcrição, seleção, preparação das prévias.
- Barra de andamento como **estimativa por fase**, não progresso fictício linear; mostrar etapa atual e avisar quando operar em CPU.
- Botão cancelar; impedir execução de 2 tarefas pesadas simultâneas.

### T4 — Cortes encontrados

- Cards com thumbnail, título proposto, início/fim no original, duração, explicação objetiva da seleção e botão de reprodução.
- Ações: **Editar**, **Excluir da seleção**, **Exportar** e **Exportar selecionados**.
- Se não houver fala suficiente, explicar limitação e oferecer criar um corte manual.

### T5 — Editor de corte

- Player vertical com reprodução real do conteúdo, área de visualização 9:16, botões play/pause, avançar/retroceder e seek.
- Timeline simples de uma faixa com bordas arrastáveis de início/fim; campos de tempo numéricos e ajuste de 0,1 s via teclado.
- Controle horizontal de enquadramento `0.0..1.0` (esquerda/centro/direita), sem fingir detecção automática de rostos.
- Lista de cues de legenda editáveis com início, fim e texto; 2 presets visuais: **Branco com contorno preto** e **Amarelo com contorno preto**.
- Botões **Atualizar prévia**, **Salvar** e **Exportar MP4**. Salvar edições sem perder ao fechar o programa.
- Alterar tempos pode exigir regenerar prévia; sinalizar quando está desatualizada.

### T6 — Exportação

- Escolher diretório de saída, nome de arquivo e exportar um ou todos os clips.
- Preset padrão: MP4, H.264, AAC, 1080×1920, 30 FPS, áudio estéreo quando aplicável, pixel format `yuv420p`, `+faststart`.
- Preferir `h264_nvenc` se teste de capacidade real passar; fallback para `libx264` com aviso visível.
- Resumo após exportar: caminho do arquivo, tamanho, duração, abrir pasta e eventuais erros.

### T7 — Configurações/diagnóstico

- FFmpeg/FFprobe encontrados; encoder NVENC disponível; GPU/CUDA e faster-whisper operacional; estado do Ollama + modelo; espaço livre.
- Permitir escolher modelo Whisper `base` em CPU (padrão no hardware de teste), `small` em CUDA (padrão no hardware de produção), `medium` opcional, CPU como fallback e pasta de trabalho/exportação.
- Botão **Executar diagnóstico** com resultado estruturado e instruções acionáveis para corrigir falhas.

## 7. Pipeline de processamento (contrato)

### 7.1 Preparação

1. Validar fonte e metadados; se arquivo local, manter referência ao caminho original e permitir reconectar se ele for movido. Se URL, baixar para pasta privada do projeto.
2. Gerar ID UUID e criar diretório de trabalho. Verificar espaço livre antes de gerar cache. Se espaço insuficiente, abortar com aviso.
3. Invocar FFprobe (`-show_format`, `-show_streams`, `-of json`) para obter duração, resolução, FPS, streams e codecs.
4. Rejeitar vídeos sem stream de vídeo; se não houver áudio, aceitar edição manual, mas informar que seleção por fala estará indisponível.

### 7.2 Áudio e ASR

1. Extrair WAV temporário mono/16 kHz para inferência ou alimentar o modelo a partir de arquivo suportado.
2. Selecionar perfil automaticamente: no i7/Iris Xe usar `faster-whisper base`, `device=cpu`, `compute_type=int8`; na RTX 2060 Super testar `small`, `device=cuda`, `compute_type=int8_float16`. Validar em runtime e permitir fallback CPU/int8. Nunca exigir CUDA para executar o fluxo P0.
3. Ativar VAD do pipeline de transcrição quando compatível, `word_timestamps=True` e armazenar idioma detectado, segmentos e palavras.
4. Normalizar timestamps em **segundos relativos ao começo do vídeo original**; manter precisão em milissegundos no armazenamento.
5. Evitar trechos vazios e limitar textos/truncamento para não gerar entradas gigantes ao LLM.
6. Salvar resultado parcial após transcrição para retomar a análise sem transcrever tudo novamente.

### 7.3 Construção de candidatos

1. Agrupar frases ou segmentos com base em pausas e mudanças de fala.
2. Criar janelas entre 15 e 60 s (alvo 20–45 s), preferencialmente com começo e fim em fronteiras de frase; aplicar pequena margem de contexto de 0,5–2 s quando não cortar diálogo.
3. Calcular features básicas por candidato: duração, densidade de fala, pausas, variedade lexical, presença de palavras de reação/pergunta/ênfase, contexto suficiente para compreensão e transcrição contida.
4. Eliminar janelas vazias, inválidas, fora do intervalo do vídeo e com fala insuficiente, salvo criação manual.
5. Ranqueamento heurístico determinístico que funcione mesmo sem Ollama. Nunca retornar timestamps inventados.

### 7.4 Ranking com LLM (melhoria opcional)

- Usar `qwen2.5:3b` local via API do Ollama, passando candidatos com `candidate_id`, `start`, `end`, transcript e critérios de avaliação.
- Solicitar JSON estruturado: `candidate_id`, `score` inteiro 0–100, `title` curto, `reason` curta e `tags` opcionais. O modelo não pode redefinir timestamps: eles são de responsabilidade do algoritmo.
- Critérios: começo compreensível sem contexto longo, momento surpreendente/interessante pelo **conteúdo falado**, ritmo, potencial de entretenimento/informação e fechamento natural.
- Validar Pydantic; em saída inválida, timeout ou Ollama indisponível, usar heurística e avisar que a escolha foi básica.
- Processar em pequenos lotes; não enviar transcrição completa de vídeos longos num único prompt.
- Selecionar até `N` candidatos, aplicando deduplicação e limiar de sobreposição (`intersection-over-union` temporal máximo 0,20), sempre respeitando limites do vídeo.
- Se houver menos de `N` bons trechos, retornar menos e explicar; não fabricar conteúdo.
- **Limitação explícita:** o LLM só avalia texto, não identifica sozinho momentos visuais de gameplay sem fala.

### 7.5 Prévia e thumbnails

- Thumbnail via FFmpeg em momento representativo do corte.
- Prévia vertical temporária 540×960 ou resolução similar, 24/30 FPS, com os mesmos filtros geométricos e legendas da exportação.
- Se transcodificação de prévia ficar cara, gerar sob demanda para o clip selecionado; mostrar thumbnail e linha temporal enquanto processa.
- Usar URLs locais de mídia assinadas/temporárias ou protocolo de asset permitido pelo Tauri. Não expor leitura arbitrária do sistema de arquivos.

### 7.6 Enquadramento, legenda e exportação

1. Recortar fonte com tempos precisos; reencodar para evitar imprecisão de keyframes.
2. Para modo padrão **preencher 9:16**, escalar proporcionalmente até cobrir quadro e recortar para 1080×1920; `center_x` ajusta eixo horizontal no intervalo válido. Não esticar imagem.
3. Manter saída 1080×1920, 30 FPS e SAR 1:1, com áudio AAC. Para entrada sem áudio, exportar corretamente sem stream de áudio.
4. Gerar legendas no formato ASS com os cues editados, até 2 linhas por cue quando viável, margens inferiores e contorno contrastante. Aplicar renderização por filtro FFmpeg compilado com libass; checar suporte no diagnóstico.
5. Evitar legenda fora do quadro; garantir timings dentro de `[clip_start, clip_end]` convertidos para a linha temporal do **clip** antes de gerar ASS.
6. Construir filtros reutilizáveis para prévia e exportação. Utilizar diretório temporário controlado e nomes de arquivos simples para minimizar erros de escape em paths do Windows.
7. Exportar para arquivo temporário, validar com FFprobe, e só então mover/renomear de maneira segura para destino final. Não sobrescrever arquivo existente sem confirmação.
8. Limpar temporários órfãos após cancelamento/erro, preservando fonte, transcrição e edições.

## 8. Modelo de dados e invariantes

### Entidades mínimas

```text
Project:
  id: UUID
  title: string
  source_kind: "file" | "url"
  source_uri: string        # caminho local ou URL original
  resolved_video_path: string | null
  duration_ms: int | null
  width: int | null
  height: int | null
  fps: float | null
  has_audio: bool | null
  created_at, updated_at: ISO datetime

Job:
  id: UUID
  project_id: UUID
  type: "analyze" | "preview" | "export" | "download"
  status: "queued" | "running" | "done" | "failed" | "cancelled"
  phase: string
  progress: float        # 0..1, estimado quando aplicável
  message: string
  error_code: string | null
  created_at, updated_at: ISO datetime

TranscriptSegment:
  id: UUID
  project_id: UUID
  start_ms: int
  end_ms: int
  text: string
  words_json: JSON | null

Clip:
  id: UUID
  project_id: UUID
  start_ms: int
  end_ms: int
  title: string
  score: int | null
  reason: string | null
  center_x: float        # 0..1; default 0.5
  selected: bool
  preview_path: string | null
  updated_at: ISO datetime

SubtitleCue:
  id: UUID
  clip_id: UUID
  start_ms: int          # RELATIVO ao início do clip
  end_ms: int
  text: string
  sort_order: int

Settings:
  whisper_model, language, use_gpu, use_llm,
  default_export_dir, default_caption_style
```

**Invariantes:** `0 <= clip.start_ms < clip.end_ms <= project.duration_ms`; `0 <= cue.start_ms < cue.end_ms <= clip.duration_ms`; `center_x ∈ [0,1]`; IDs nunca derivam de nomes de arquivos; atualizações de edição devem ser transacionais; paths são canonicalizados e nunca aceitos cegamente.

## 9. Contrato API local (FastAPI)

Todos os endpoints (exceto `GET /health`) exigem `Authorization: Bearer <token-de-sessao>`; validar origem e host. Endpoints de mídia usam token efêmero próprio ou asset protocol controlado.

| Método | Endpoint | Ação |
|---|---|---|
| GET | `/health` | Backend pronto e versão |
| GET | `/diagnostics` | Recursos detectados e recomendações |
| GET | `/projects` | Listar projetos |
| POST | `/projects` | Criar projeto `{title?, source_kind, source_uri}` |
| GET | `/projects/{id}` | Detalhes e metadados |
| PATCH | `/projects/{id}` | Renomear/relink fonte |
| DELETE | `/projects/{id}` | Excluir projeto e cache, mediante confirmação no UI |
| POST | `/projects/{id}/analyze` | `{clip_count, min_seconds, max_seconds, language, use_llm}` → `{job_id}` |
| GET | `/projects/{id}/clips` | Listar clips e legendas |
| POST | `/projects/{id}/clips` | Criar clip manual com intervalo válido |
| PATCH | `/clips/{id}` | Atualizar intervalo/título/centro/seleção |
| PUT | `/clips/{id}/subtitles` | Substituir cues validados atomicamente |
| POST | `/clips/{id}/preview` | Enfileirar render de prévia → `{job_id}` |
| POST | `/exports` | `{project_id, clip_ids, output_dir, preset}` → `{job_id}` |
| GET | `/jobs/{id}` | Estado/progresso/resultado/erro |
| POST | `/jobs/{id}/cancel` | Solicitar cancelamento |
| GET | `/settings` | Ler preferências |
| PATCH | `/settings` | Atualizar preferências |

### Exemplos mínimos de payload

`POST /projects/{id}/analyze`

```json
{
  "clip_count": 5,
  "min_seconds": 15,
  "max_seconds": 60,
  "language": "pt",
  "use_llm": true
}
```

`GET /jobs/{id}`

```json
{
  "id": "uuid",
  "status": "running",
  "phase": "transcribing",
  "progress": 0.42,
  "message": "Transcrevendo áudio localmente",
  "error_code": null,
  "result": null
}
```

`PATCH /clips/{id}`

```json
{
  "start_ms": 32200,
  "end_ms": 68400,
  "title": "Momento decisivo",
  "center_x": 0.65,
  "selected": true
}
```

**Erro padronizado:** `{ "error": { "code": "SOURCE_UNAVAILABLE", "message": "...", "details": null } }`. Códigos mínimos: `INVALID_SOURCE`, `SOURCE_UNAVAILABLE`, `UNSUPPORTED_MEDIA`, `NO_AUDIO`, `DISK_FULL`, `CUDA_UNAVAILABLE`, `MODEL_MISSING`, `FFMPEG_FAILED`, `CANCELLED`, `INVALID_TIMECODE`, `PATH_NOT_ALLOWED`, `INTERNAL_ERROR`.

## 10. Gerenciamento de tarefas, concorrência e resiliência

- Implementar fila em processo com persistência SQLite e limite **1 job pesado de cada vez**, com estado `queued/running/done/failed/cancelled`.
- API retorna `job_id` imediatamente; UI consulta a cada 500–1000 ms enquanto job estiver ativo.
- Progresso é por fases explícitas; capturar progresso real de FFmpeg via `-progress pipe:1` quando possível. Transcrição deve reportar fração do áudio processado sem simular percentuais exatos não disponíveis.
- Suportar cancelamento cooperativo entre fases e interrupção controlada de subprocessos; não corromper banco nem excluir fonte original.
- Na reinicialização, jobs `running` que perderam seu processo devem virar `failed/interrupted`, com opção de reexecutar sem apagar cache válido.
- Manter logs locais por projeto/job sem incluir tokens, credenciais ou textos completos por padrão; mostrar erro explicativo na UI.
- Evitar carregar o vídeo completo em RAM. Processar por streaming/chunks e arquivos em disco.
- Preferir execução sequencial de Whisper, LLM e FFmpeg por causa dos 8 GB de VRAM. Fechar/reliberar recursos quando possível.

## 11. Segurança, privacidade e licenças

- Processamento local por padrão, sem telemetria ou uploads ocultos.
- Baixar conteúdo somente quando usuário tiver direito/acesso; `yt-dlp` não garante suporte permanente e pode falhar por mudanças de plataformas.
- Não implementar bypass de DRM, login não autorizado, cookies coletados automaticamente ou scraping de rede interna.
- Validar URL e destino contra SSRF, redirects para IP privado/loopback, caminhos de arquivos hostis e traversal; limitar tempo/volume de downloads conforme configurações seguras.
- A API não pode aceitar qualquer path arbitrário para servir mídia; somente caminhos cadastrados e pertencentes ao projeto. Para entrada local, o usuário a autoriza pelo diálogo nativo.
- Permitir excluir projeto e caches localmente; não apagar vídeo original externo sem pedido explícito.
- Verificar redistribuição e licenças de FFmpeg/codec/libass, Ollama e modelos; registrar componentes de terceiros.

## 12. Requisitos não funcionais

- **Compatibilidade:** Windows x64 como alvo inicial, sem exigir internet após download inicial dos modelos, desde que a fonte seja arquivo local.
- **Desempenho:** medir separadamente no notebook i7/Iris Xe/16 GB (vídeos de 1, 3 e 5 min) e no desktop RTX 2060 Super/5600G/32 GB (vídeos de 5, 10 e 30 min). Registrar tempos por fase, RAM e VRAM. Não impor meta de velocidade não validada por benchmark.
- **Capacidade:** projetar para vídeos de até 60 min no teste de aceitação, processando sequencialmente e sem manter arquivos gigantes na memória.
- **Uso de disco:** estimar espaço para fonte baixada, áudio, proxies e exportações; avisar antes de iniciar se insuficiente.
- **UX:** tudo em PT-BR, estados vazios, progressos compreensíveis e erro útil; botão cancelar operacional.
- **Observabilidade:** log rotativo local, nível INFO, eventos por job sem vazar tokens; salvar diagnósticos (sem dados privados) opcionalmente.
- **Reprodutibilidade:** lockfiles para npm/Python, versões de modelos fixáveis/configuráveis, script de instalação em Windows e fixtures de testes próprios.

## 13. Estrutura de testes

### Unitários backend

- Normalização de timestamps; agrupamento por sentença; janelas 15–60 s; recorte no fim do vídeo.
- Deduplicação temporal e ordenação de ranking.
- JSON inválido do LLM gera fallback sem derrubar pipeline.
- Cues não podem ficar fora do clip após alterar início/fim; recalcular/recortar cues com política explícita.
- Bloqueio de path traversal, URLs locais/privadas, extensão inconsistente e argumentos maliciosos.
- Testes do fluxo com `ffprobe/ffmpeg` em fixture sintética pequena (gerada pelo próprio projeto).

### Integração

1. Arquivo 5 min com fala PT-BR → transcrição, sugestões, preview e MP4 exportado.
2. Arquivo 20 min com gameplay e fala → geração de até 5 clips, sem timestamps fora da fonte.
3. Arquivo 60 min → consumo controlado, estado de progresso e recuperação de falhas.
4. Vídeo sem áudio → mensagem amigável + criação manual de clip.
5. Ollama desligado → ranking heurístico funciona, com informação correta do modo utilizado.
6. CUDA indisponível → fallback CPU ou explicação de impossibilidade, sem travar aplicação.
7. URL inválida/indisponível → falha acionável sem projeto corrompido.
8. Cancelar durante FFmpeg → subprocesso termina e temporários são limpos.
9. Reabrir app → cortes e legendas persistidos.
10. Exportar → ffprobe confirma 1080×1920, H.264, 30 FPS, duração compatível e AAC se houver áudio.

### E2E interface

- Criar projeto, navegar entre telas, visualizar progresso, editar clip e legenda, salvar, fechar/reabrir e exportar.
- Testar em 1366×768 e 1920×1080; sem elementos essenciais inacessíveis por rolagem.
- Testar acessibilidade básica: foco, labels, teclado e feedback de erros.
- Executar o instalador gerado em Windows limpo/VM para verificar que sidecar/FFmpeg e paths funcionam sem Python instalado.

## 14. Ordem de implementação para o agente (não pular etapas)

### Marco 0 — Bootstrap e diagnóstico

Criar monorepo, Tauri 2 + React, FastAPI e SQLite; integração real Tauri↔backend. Endpoint `/health`, diagnósticos e scripts `dev.ps1`, `doctor.ps1`. **Entrega:** app abre e exibe status real do motor de vídeo.

### Marco 1 — Projeto e importação

CRUD de projetos; seletor nativo; FFprobe; lista, preview original e persistência. Depois integrar importação de URL via yt-dlp com tratamento de erros. **Entrega:** arquivo real pode ser aberto e reaberto.

### Marco 2 — Processamento e transcrição

Gerenciar jobs; extrair áudio; integrar faster-whisper; salvar segmentos e tempos; GPU/CPU fallback; progresso e cancelamento. **Entrega:** transcrição real de vídeo português.

### Marco 3 — Sugestão de cortes

Algoritmo de candidatos + ranking heurístico + deduplicação; depois adicionar Ollama opcional e validar JSON. **Entrega:** de 3 a 5 sugestões quando houver conteúdo suficiente.

### Marco 4 — Editor e prévias

Galeria com cards, vídeos temporários, editor de intervalos, posição de crop, título e cues de legendas. **Entrega:** usuário altera um corte e a prévia reflete a alteração.

### Marco 5 — Exportação real

Gerar ASS, aplicar filtros FFmpeg, codec H.264 e AAC, verificar NVENC/fallback, exportar lote, validar arquivo final. **Entrega:** MP4 vertical reproduzível em player comum.

### Marco 6 — Distribuição e qualidade

Construir sidecar Windows, integrar FFmpeg/FFprobe, verificação de dependências, README, testes e instalador; testar máquina sem ambiente de desenvolvimento. **Entrega:** instalador funcional e instruções completas.

**Política de execução:** ao final de cada marco, executar testes, corrigir falhas, registrar o que foi entregue e então avançar. Não declarar um marco concluído se depender de mocks não substituídos.

## 15. Critérios de aceite objetivos (Definition of Done)

- [ ] App instala e inicia no Windows x64 sem exigir terminal/Python instalado do usuário final.
- [ ] Tela inicial, projetos, importação, processamento, galeria, editor, exportação e diagnóstico são navegáveis.
- [ ] Importação de arquivo local e ao menos um vídeo público gravado autorizado via URL são demonstradas; falhas da plataforma são tratadas.
- [ ] Para fixture com fala, a transcrição é real, persistida e aparece nos metadados do projeto.
- [ ] Até 5 cortes reais são sugeridos, com justificativa, limites válidos e baixa sobreposição; caso contrário UI explica por quê.
- [ ] É possível alterar começo/fim, centralização, título e texto de uma legenda; alterações sobrevivem a reinicialização.
- [ ] Exportação produz MP4 1080×1920 H.264/30 FPS, áudio AAC quando existente e legendas visíveis no vídeo.
- [ ] CPU fallback e modo heurístico permitem fluxo sem CUDA/Ollama, com indicação de limitações.
- [ ] Cancelamento, erros de URL, falta de espaço e vídeos sem áudio não deixam UI travada nem corrompem banco.
- [ ] Testes unitários, integração e smoke E2E executam; comandos e resultados documentados.
- [ ] `README.md` contém como rodar em desenvolvimento, como empacotar, dependências, limitações, licenças e problemas conhecidos.
- [ ] Não há envio remoto de vídeos nem chaves/API pagas necessárias ao fluxo local.

## 16. Orientações finais para o agente construtor

> Você é o agente de implementação deste MVP. Analise a especificação, crie o projeto e construa um fluxo funcional **de ponta a ponta**, sem depender de serviços pagos. Comece pelo Marco 0 e avance sequencialmente até o Marco 6, validando cada etapa com testes e arquivos de vídeo reais ou fixtures sintéticas autorizadas. Use Windows x64, Tauri 2, React/TypeScript, Python 3.11/FastAPI/SQLite, FFmpeg/FFprobe, faster-whisper e Ollama opcional com qwen2.5:3b. Respeite o limite de 8 GB VRAM: processe cargas de IA pesadas em sequência e ofereça fallback CPU. Não substitua processamento por mocks, não simule progresso, não invente resultados de IA e não prometa qualidade editorial perfeita. Priorize confiabilidade, exportação real 9:16 com legendas sincronizadas por palavra, edições persistentes e instalador que inicia sem ambiente Python externo. Se algum recurso não for implementado, documente o impedimento e mantenha o caminho principal funcional. Ao concluir, forneça o código, instruções de execução, testes executados, evidência de exportação e limitações conhecidas.

## 17. Referências técnicas oficiais

- Tauri 2, sidecar: https://v2.tauri.app/develop/sidecar/
- faster-whisper e requisitos CUDA/cuDNN: https://github.com/SYSTRAN/faster-whisper
- yt-dlp, integração Python: https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp
- FFmpeg: https://ffmpeg.org/ffmpeg.html
- FFprobe: https://ffmpeg.org/ffprobe.html
- Ollama Qwen 2.5 3B: https://ollama.com/library/qwen2.5:3b

**Nota técnica:** versões exatas de dependências CUDA/cuDNN/CTranslate2 devem ser validadas e travadas em lockfile durante a implementação, pois a combinação compatível varia por release e driver. Não especificar versões arbitrárias sem teste no Windows alvo.

## 18. Requisito obrigatório — legendas sincronizadas com a voz (P0)

**Definição:** cada corte exportado deve apresentar legendas cujo início e fim acompanhem a fala real no áudio, não apenas blocos de texto distribuídos uniformemente pela duração do vídeo. Para o MVP, o padrão é **legenda por frase curta, com timestamps derivados das palavras**; oferecer destaque progressivo de palavra como preset opcional, sem tornar obrigatório um efeito visual complexo.

### 18.1 Pipeline de sincronização

1. Extrair áudio em PCM mono 16 kHz e preservar o offset em relação ao vídeo original.
2. Executar `faster-whisper` com `word_timestamps=True` e VAD configurado; persistir `start`, `end`, `text`, `confidence` quando disponível, `segment_id` e `source_timebase`.
3. Remover palavras espúrias, ordenar timestamps, validar que `end > start` e impedir sobreposição incorreta dentro de uma mesma trilha de fala. Não deslocar palavras para esconder erros sem registrar correção.
4. Agrupar palavras em cues legíveis (preferencialmente 2–7 palavras, máximo de duas linhas), respeitando pausas, pontuação e velocidade da fala. Não dividir uma palavra no meio.
5. Ao gerar um corte `[clip_start, clip_end]`, selecionar apenas palavras que interceptam o intervalo, recortar limites quando necessário e converter cada timestamp para o tempo relativo ao corte: `local_start = max(0, word.start - clip_start)` e `local_end = min(clip_duration, word.end - clip_start)`.
6. Gerar `.ass` com tempos dos cues e queimar legendas via FFmpeg/libass. O texto precisa aparecer durante a fala correspondente e desaparecer após a frase; nunca exibir todas as legendas desde o início.
7. Permitir edição manual de texto, começo e fim dos cues e deslocamento global das legendas em milissegundos. A prévia deve refletir exatamente a temporização usada na exportação.
8. Se o modelo não retornar timestamps confiáveis, marcar o trecho como `alignment_needs_review` e oferecer correção manual; nunca apresentar alinhamento estimado como precisão garantida.

### 18.2 Estrutura de dados mínima

`TranscriptWord { id, segment_id, text, start_ms, end_ms, confidence? }`  
`SubtitleCue { id, clip_id, start_ms, end_ms, text, word_ids[], edited_by_user, alignment_needs_review }`

Todos os timestamps são inteiros em milissegundos; transcrição usa linha temporal do vídeo-fonte, legenda exportada usa linha temporal do corte. Persistir ambos de modo inequívoco.

### 18.3 Critérios de aceitação da sincronização

- Em uma fixture de áudio com falas e pausas conhecidas, o começo e o fim de cada cue devem corresponder aos timestamps alinhados, sem deslocamento introduzido pela lógica de corte/exportação.
- Testar corte iniciado no meio do vídeo (por exemplo, `clip_start=72.5s`) e verificar que as legendas aparecem no segundo correto do clipe, não no tempo absoluto da fonte.
- Testar pausas de silêncio, falas rápidas, pontuação, cortes na fronteira de uma frase e alterações manuais.
- Medir em amostra anotada manualmente o erro de início/fim das legendas; **meta inicial de até 250 ms para a maioria dos cues**, com relatório de casos fora da meta. Essa é uma meta de qualidade a validar, não garantia do modelo.
- Verificar por reprodução real que áudio, vídeo e legendas continuam sincronizados após exportação e reabertura.

## 19. Perfis de hardware e execução obrigatória

### 19.1 Perfil TESTE_LEVE (padrão no notebook)

- **Equipamento:** Intel Core i7 de 11ª geração, Iris Xe integrada, 16 GB RAM.
- **Inferência:** CPU/int8, `faster-whisper base` como padrão; permitir `tiny` para smoke tests e `small` como opção mais lenta.
- **Seleção de cortes:** heurísticas determinísticas P0; LLM local desabilitado por padrão, opcional se couber na memória.
- **Vídeos de validação:** 1–5 minutos, áudio em português; gerar prévias 540×960 e exportar inicialmente 720×1280, com 1080×1920 opcional.
- **Codificação:** `libx264` como fallback garantido; Intel Quick Sync (`h264_qsv`) somente após teste de encode real. Iris Xe não deve ser tratada como GPU CUDA.
- **Objetivo:** executar TODO o fluxo importar → transcrever → selecionar → editar → legendar sincronizado → exportar sem NVIDIA, Ollama ou serviços pagos.

### 19.2 Perfil PRODUCAO_GPU (após validação)

- **Equipamento:** NVIDIA RTX 2060 Super 8 GB VRAM, Ryzen 5 5600G, 32 GB RAM.
- **Inferência:** `faster-whisper small` em CUDA, com fallback CPU; `medium` opcional após benchmark.
- **Seleção de cortes:** heurísticas + LLM local quantizado opcional (`qwen2.5:3b`), executado sequencialmente para preservar VRAM.
- **Vídeos de validação:** 5, 10 e 30 minutos; exportação padrão 1080×1920.
- **Codificação:** `h264_nvenc` após teste de capacidade, fallback `libx264`.
- **Objetivo:** executar cargas longas com aceleração, sem alterar contratos de dados, interface ou fluxo do modo leve.

### 19.3 Regras transversais

- Detecção automática de hardware no primeiro uso e opção manual de perfil em Configurações.
- Não carregar modelos grandes simultaneamente na GPU; liberar recursos entre transcrição, análise e renderização.
- Registrar tempo por etapa, RAM máxima, VRAM máxima (quando disponível), falhas de fallback e qualidade de alinhamento.
- Não assumir desempenho em tempo real ou prometer duração fixa de processamento sem benchmark.
- Incluir testes de integração em CPU no CI; testes CUDA devem ser marcados como opcionais para máquina com NVIDIA.
- O agente não pode marcar o MVP como concluído se ele só funcionar na RTX 2060 Super.

