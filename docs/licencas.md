# Componentes de terceiros

- [Tauri e plugins](https://github.com/tauri-apps/tauri) usam MIT ou Apache-2.0. [React](https://github.com/facebook/react) e [Vite](https://github.com/vitejs/vite) usam MIT.
- [Python](https://docs.python.org/3/license.html) usa a licença da PSF. [FastAPI](https://github.com/fastapi/fastapi), [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) e [faster-whisper](https://github.com/SYSTRAN/faster-whisper) usam MIT. [CTranslate2](https://github.com/OpenNMT/CTranslate2) usa MIT.
- [PyInstaller](https://pyinstaller.org/en/stable/license.html) descreve a licença e a exceção de distribuição do bootloader. [yt-dlp](https://github.com/yt-dlp/yt-dlp) registra as licenças de seus diferentes artefatos.
- [FFmpeg](https://ffmpeg.org/legal.html) pode estar sob LGPL ou GPL conforme a compilação. Habilitar libx264 normalmente exige `--enable-gpl`. Verifique a compilação exata, incluindo libass, x264 e demais bibliotecas. Não redistribua uma compilação `--enable-nonfree`.
- [Modelos Whisper Systran](https://huggingface.co/Systran), [Ollama](https://github.com/ollama/ollama) portátil e [Qwen 2.5 7B](https://ollama.com/library/qwen2.5:7b) são obtidos no primeiro uso em Produção. O instalador inclui o aviso de licença do [Node.js](https://github.com/nodejs/node/blob/main/LICENSE) junto ao executável e usa os DLLs da pasta redistribuível do Visual C++.

As versões resolvidas estão em `package-lock.json` e `uv.lock`. Antes de publicar um binário, reúna os avisos e textos de licença das dependências realmente empacotadas e disponibilize o código-fonte correspondente às obrigações da compilação FFmpeg usada. O script exige um arquivo de avisos para o bundle e não baixa ou redistribui FFmpeg por conta própria.
