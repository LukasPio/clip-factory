# Clip Factory

Editor desktop local para transformar vídeos gravados em cortes verticais. O motor usa FFmpeg para ler e renderizar vídeo e faster-whisper para transcrever a fala. O aplicativo usa CPU por padrão e pode gerar sugestões com heurísticas, sem conta, CUDA ou Ollama.

## Desenvolver no Windows x64

Instale Python 3.11 x64 com o launcher `py`, Node.js 22 ou superior, Rust com alvo MSVC, Visual Studio Build Tools com C++ e Windows SDK, e WebView2. Coloque FFmpeg e FFprobe no PATH. Use uma compilação FFmpeg com `libx264` e `libass`.

```powershell
.\scripts\doctor.ps1
.\scripts\dev.ps1
```

O launcher cria uma venv, instala as dependências e abre o Tauri. A janela inicia e encerra o motor. Para trabalhar apenas na interface em Linux ou Windows, inicie `python -m app.main` de `services/engine`. Copie temporariamente `url` e `token` da primeira linha do motor para `VITE_ENGINE_URL` e `VITE_ENGINE_TOKEN` no shell antes de executar `npm run dev` de `apps/desktop`. O modo navegador de desenvolvimento aceita caminhos absolutos nos formulários. Use o app desktop para o seletor nativo.

## Usar

1. Crie um projeto e selecione o vídeo. Arquivos MOV e MKV podem exigir uma prévia de corte caso o player do sistema não decodifique o original.
2. Em **Análise de fala**, selecione a faixa de duração e permita o download do modelo caso necessário. Depois do download, vídeos de arquivo local podem ser analisados offline.
3. Abra uma sugestão ou crie um corte manual. Ajuste intervalo, enquadramento e legendas. Gere a prévia vertical para ouvir a fala e conferir os tempos.
4. Exporte um corte ou a seleção. As opções são 1080 × 1920 e 720 × 1280, ambas com 30 FPS. Para áudio presente, a saída contém AAC.

O perfil **Teste leve** usa Whisper `base` em CPU/int8. O perfil **Produção GPU** tenta CUDA com `small` e NVENC, com fallback para CPU. O diagnóstico faz um encode real para verificar NVENC e Quick Sync. Para ranking híbrido, instale Ollama separadamente, execute `ollama pull qwen2.5:3b` e habilite o ajuste. O motor envia somente a lista curta de trechos para o Ollama em loopback.

Use **Link de vídeo** somente para conteúdo gravado que você tem autorização para editar. A importação aceita um arquivo HTTPS MP4/WebM simples que o yt-dlp consiga obter. Fontes que exigem login, DRM, live ou streaming segmentado, incluindo sites que oferecem apenas faixas de áudio e vídeo separadas, podem falhar. O limite de download é 2 GB.

## Empacotar no Windows

Prepare uma compilação estática x64 do FFmpeg com `ffmpeg.exe`, `ffprobe.exe`, libass e libx264. Prepare um arquivo de avisos de terceiros da compilação. Os avisos devem registrar versão, origem, licenças e como obter o código-fonte correspondente e os scripts de build. Veja [componentes e distribuição](docs/licencas.md).

```powershell
.\scripts\build-windows.ps1 -FFmpegDir C:\ffmpeg\bin -ThirdPartyNotices C:\ffmpeg\NOTICES.txt
```

O script prepara o motor Python como sidecar e aciona a geração do instalador NSIS. A saída fica sob `apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis`. O fluxo de empacotamento precisa ser validado em Windows limpo antes de distribuir o instalador. Veja as referências do [sidecar](https://v2.tauri.app/develop/sidecar/) e do [instalador](https://v2.tauri.app/distribute/windows-installer/).

## Testes

```text
python -m pip install -e "services/engine[test]"
python -m pytest services/engine/tests
npm --prefix apps/desktop ci
npm --prefix apps/desktop run test
npm --prefix apps/desktop run build
```

Para o Playwright, execute `npx playwright install chromium` de `apps/desktop` e depois `npm run test:e2e` no mesmo diretório. Use `CLIP_FACTORY_PYTHON` para indicar a venv do motor e, opcionalmente, `CLIP_FACTORY_CHROMIUM` para usar Chromium instalado. FFmpeg e FFprobe precisam estar no PATH.

O teste Whisper usa uma fixture em português e um modelo real no disco. Gere a fixture com `python -m pip install espeakng-loader` e `python fixtures/gerar-fala.py <arquivo.mp4>`. Aponte `CLIP_FACTORY_ASR_FIXTURE` para o vídeo e `CLIP_FACTORY_ASR_MODELS` para uma pasta chamada `models` com o cache `tiny`. O perfil padrão do aplicativo continua sendo `base`.

Leia a [validação](docs/validacao.md), a [arquitetura](docs/arquitetura.md) e o [guia de diagnóstico](docs/troubleshooting.md). A [especificação v1.1](docs/especificacao.md) registra o escopo alvo.
