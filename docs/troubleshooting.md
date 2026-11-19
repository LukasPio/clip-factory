# Diagnóstico

| Sintoma | Ação |
| --- | --- |
| WinGet não encontrado | Instale ou atualize o [Instalador de Aplicativo (App Installer)](https://apps.microsoft.com/detail/9NBLGGH4NNS1) e abra um novo PowerShell. |
| O instalador pediu para reiniciar | Após reiniciar, execute o mesmo comando de `setup-windows.ps1`. |
| A janela não inicia em desenvolvimento | Execute `scripts/doctor.ps1`. Confira Python 3.11, Build Tools com C++, Rust/MSVC, Node e WebView2. |
| FFmpeg ou FFprobe ausente | Use os dois executáveis de uma mesma distribuição. No desenvolvimento, inclua a pasta no PATH ou use `CLIP_FACTORY_BIN`. |
| Falha ao gerar legendas | Confira que o diagnóstico identifica libass. Para exportação em CPU, confira também libx264. |
| A fonte local sumiu | Use **Localizar arquivo** e selecione o mesmo vídeo em sua nova pasta. O app mantém apenas uma referência ao original. |
| O link falhou | Confirme que o vídeo está publicado, gravado e pode ser baixado com autorização. Se a plataforma oferecer apenas streaming segmentado ou bloquear o acesso, use um arquivo local obtido de forma autorizada. |
| Whisper não inicia | Autorize o primeiro download, verifique espaço livre e teste o perfil CPU com `tiny` ou `base`. |
| CUDA ou NVENC falhou | A transcrição e exportação tentam CPU automaticamente. Antes de usar a GPU, confira driver e dependências CUDA/cuDNN da versão do CTranslate2 no ambiente alvo. |
| Abri um MOV/MKV e o player está indisponível | Crie ou abra um corte e use **Atualizar prévia** para gerar um MP4 compatível. |
| Uma legenda está fora de sincronia | Confira o primeiro e o último timestamp do cue e ajuste o deslocamento global se todo o corte apresentar o mesmo atraso. |
| O arquivo já existe ou a pasta está cheia | Escolha outro nome ou outra pasta. Arquivos existentes ficam preservados. |

O log rotativo do motor fica em `engine.log` dentro do diretório de dados da aplicação. Em desenvolvimento manual a pasta padrão é `~/.clip-factory`. O log registra códigos dos jobs e classes de falha, sem tokens, caminhos ou transcrições.
