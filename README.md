# Clip Factory

Editor desktop local para transformar vídeos gravados em cortes verticais. O motor usa FFmpeg para ler e renderizar vídeo e faster-whisper para transcrever a fala. O modo Produção prepara o Ollama automaticamente para revisar os cortes. O modo Teste também pode gerar sugestões com heurísticas em CPU.

## Instalar pelo GitHub no Windows x64

Execute este bloco no Windows PowerShell de 64 bits em um computador com WinGet (Instalador de Aplicativo do Windows).

```powershell
& {
    $script = Join-Path $env:TEMP 'clip-factory-install-windows.ps1'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/LukasPio/clip-factory/main/scripts/install-windows.ps1' -OutFile $script -ErrorAction Stop
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Launch
}
```

O script baixa a revisão atual da `main` em `%LOCALAPPDATA%\ClipFactory\source`, instala as dependências e prepara o Ollama, o Qwen 2.5 7B e o Whisper. Em seguida, compila o aplicativo e cria o atalho **Clip Factory** no menu Iniciar. A opção `-Launch` também abre o aplicativo ao terminar.

Abra o Clip Factory pelo menu Iniciar. Na tela **Projetos**, clique em **Atualizar pelo GitHub** para instalar a revisão mais recente da `main`. O app baixa e compila a revisão, atualiza o atalho e reabre após concluir. As versões ficam em pastas separadas para que uma falha de compilação preserve o aplicativo em uso. Os projetos continuam na pasta de dados do aplicativo.

Mantenha a internet disponível e espaço livre para ferramentas de compilação e modelos. Aceite as solicitações do Windows durante a instalação. Se algum instalador pedir uma reinicialização ou se a conexão cair, execute o mesmo comando novamente. Para escolher outro destino, passe `-InstallDir 'C:\caminho\ClipFactory'` ao script.

## Desenvolver no Windows x64

1. Baixe e extraia o ZIP do repositório pelo GitHub (**Code → Download ZIP**).
2. Na pasta extraída que contém `README.md` e `scripts`, abra o Windows PowerShell.
3. Cole o comando abaixo para preparar o ambiente e abrir o Clip Factory.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Launch
```

O script usa o WinGet para instalar os componentes que faltarem, incluindo Python 3.11 x64, Node.js LTS, Visual Studio Build Tools com C++ e Windows SDK, WebView2, Visual C++ Redistributable e FFmpeg/FFprobe. O Rust/MSVC é preparado pelo instalador oficial do Rustup. O comando aceita os termos dos pacotes instalados pelo WinGet. Confirme as solicitações do Windows durante a instalação. Se algum instalador pedir reinicialização, reinicie e execute o mesmo comando. O primeiro preparo pode demorar devido ao download das ferramentas de C++. O parâmetro `-ExecutionPolicy Bypass` vale apenas para o processo iniciado pelo comando.

Com `-Launch`, o script chama `dev.ps1`, que cria a venv, instala as bibliotecas do motor e da interface e abre o Tauri. Para preparar somente as dependências do Windows, retire `-Launch`. Nos próximos usos, rode:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

O modo CPU funciona com esse preparo. O download do modelo de transcrição é solicitado dentro do aplicativo na primeira análise. Para distribuir o aplicativo a usuários finais, veja [Empacotar no Windows](#empacotar-no-windows).

A janela inicia e encerra o motor. Para trabalhar apenas na interface em Linux ou Windows, inicie `python -m app.main` de `services/engine`. Copie temporariamente `url` e `token` da primeira linha do motor para `VITE_ENGINE_URL` e `VITE_ENGINE_TOKEN` no shell antes de executar `npm run dev` de `apps/desktop`. O modo navegador de desenvolvimento aceita caminhos absolutos nos formulários. Use o app desktop para o seletor nativo.

## Usar

1. Crie um projeto e selecione o vídeo. Arquivos MOV e MKV podem exigir uma prévia de corte caso o player do sistema não decodifique o original.
2. Em **Análise de fala**, selecione a faixa de duração e permita o download do modelo caso necessário. Depois do download, vídeos de arquivo local podem ser analisados offline.
3. Abra uma sugestão ou crie um corte manual. Ajuste intervalo, enquadramento e legendas. Gere a prévia vertical para ouvir a fala e conferir os tempos.
4. Exporte um corte ou a seleção. As opções são 1080 × 1920 e 720 × 1280, ambas com 30 FPS. Para áudio presente, a saída contém AAC.

O app abre em **Produção**. Importe um vídeo e clique em **Gerar cortes automáticos**. A análise usa Whisper `medium` e revisa as sugestões localmente com Ollama e Qwen `7B`. Se os modelos ainda estiverem ausentes, o aplicativo os baixa no primeiro uso. Se a revisão falhar, a análise informa o erro e mantém as sugestões anteriores. A exportação usa 1080 × 1920. CUDA e NVENC são usados quando disponíveis, com fallback para CPU.

Para quem usa o aplicativo, basta instalar o Clip Factory para Windows x64. O instalador inclui o motor Python, FFmpeg, FFprobe, Node.js e o runtime redistribuível do C++. O WebView2 é instalado automaticamente se estiver ausente. Na primeira análise, o Clip Factory reutiliza o Ollama local ou prepara uma versão portátil e baixa os modelos necessários. Mantenha a internet disponível e reserve cerca de 15 GB livres para essa preparação. Se a conexão cair, clique em **Gerar cortes automáticos** novamente.

Para acessar os ajustes avançados durante o desenvolvimento, defina `$env:CLIP_FACTORY_MODE = 'test'` antes de executar o script de desenvolvimento. O modo Teste começa com Whisper `base` em CPU e a revisão com Ollama `3B` é opcional. Remova a variável para voltar a Produção. O aplicativo empacotado inicia sempre em Produção.

Use **Link de vídeo** para importar um vídeo gravado que você tem autorização para editar. O yt-dlp aceita links do YouTube, clipes e gravações da Twitch, posts do X/Twitter, Reels do Instagram e outros sites compatíveis. O importador baixa arquivos diretos e gravações em HLS ou DASH e usa o FFmpeg para juntar áudio e vídeo quando vêm separados. Transmissões em andamento, playlists e conteúdo com DRM são bloqueados.

Em **Configurações → Limite de download por vídeo**, o padrão é **20 GB** (1 GB = 1 bilhão de bytes). Esse limite cobre os dados de mídia recebidos em todos os segmentos e faixas e também é verificado no arquivo final. A tela mostra o espaço livre na unidade onde o aplicativo guarda os projetos, quando disponível. Downloads com áudio e vídeo separados podem precisar de aproximadamente duas vezes o tamanho das faixas, além da reserva de segurança, enquanto o FFmpeg monta o arquivo final.

Ao importar um **arquivo local**, o Clip Factory usa o original e inspeciona o formato com FFprobe. Arquivos locais podem ter qualquer tamanho aceito pelo disco e pelo formato.

O instalador inclui o Node.js para o YouTube. Em desenvolvimento manual, use Node.js ou Deno no PATH. Se a plataforma exigir login, inicie o aplicativo com `CLIP_FACTORY_COOKIES` apontando para um arquivo local de cookies no formato Netscape, exportado da sua própria sessão. Trate esse arquivo como uma credencial.

## Empacotar no Windows

Prepare uma compilação estática x64 do FFmpeg com `ffmpeg.exe`, `ffprobe.exe`, libass e libx264. Prepare um arquivo de avisos de terceiros da compilação. Os avisos devem registrar versão, origem, licenças e como obter o código-fonte correspondente e os scripts de build. Veja [componentes e distribuição](docs/licencas.md).

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1 -FFmpegDir C:\ffmpeg\bin -ThirdPartyNotices C:\ffmpeg\NOTICES.txt
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

Para testar downloads reais de YouTube, Twitch, X e Instagram no PowerShell, execute:

```powershell
$env:CLIP_FACTORY_LIVE_DOWNLOADS = '1'
.\.venv\Scripts\python.exe -m pytest services/engine/tests -m live_download -v
```

Se um vídeo de referência sair do ar, substitua o link com `CLIP_FACTORY_TEST_YOUTUBE_URL`, `CLIP_FACTORY_TEST_TWITCH_URL`, `CLIP_FACTORY_TEST_TWITTER_URL` ou `CLIP_FACTORY_TEST_INSTAGRAM_URL`.

O teste Whisper usa uma fixture em português e um modelo real no disco. Gere a fixture com `python -m pip install espeakng-loader` e `python fixtures/gerar-fala.py <arquivo.mp4>`. Aponte `CLIP_FACTORY_ASR_FIXTURE` para o vídeo e `CLIP_FACTORY_ASR_MODELS` para uma pasta chamada `models` com o cache `tiny`. O perfil padrão do aplicativo continua sendo `base`.

Leia a [validação](docs/validacao.md), a [arquitetura](docs/arquitetura.md) e o [guia de diagnóstico](docs/troubleshooting.md). A [especificação v1.1](docs/especificacao.md) registra o escopo alvo.
