# Validação

O ambiente de desenvolvimento Linux permite testar o motor, o frontend web e a saída FFmpeg. Os critérios referentes ao instalador e ao hardware alvo precisam de uma execução no Windows x64.

| Cenário | Verificação |
| --- | --- |
| MP4 original local | Importação real e metadados confirmados por FFprobe. |
| Recorte e sincronização de ASS | Teste decodifica quadros antes, durante e depois da legenda manual em um corte iniciado no meio da fonte. |
| Exportação | 1080 × 1920, H.264, 30 FPS e AAC validados por FFprobe em corte de 2,7 s. |
| Transcrição Whisper em CPU | Amostra com fala sintética em português e Whisper tiny/int8, com 13 segmentos, 203 palavras alinhadas, três sugestões e MP4 final validado por FFprobe. |
| Frontend | Build de produção e quatro testes Vitest aprovados. O CI executa o fluxo Playwright em duas resoluções. |
| Falhas comuns | Arquivo com formato incompatível, vídeo sem áudio, cancelamento de subprocesso e tentativa de sobrescrever saída. |
| Persistência | Projeto, título e legendas lidos novamente do SQLite após inicialização. |
| URL | Bloqueio de URLs inválidas ou destinos não públicos verificado. A tentativa com URL pública terminou na resolução de DNS deste ambiente. |
| Windows e GPU | NSIS, início após instalação limpa, WebView2, CUDA/NVENC e desempenho no hardware alvo ainda exigem validação. |

A suíte regular do motor teve 15 testes aprovados. O caso opcional de ASR também passou com o modelo já em disco e a rede isolada. Assim, a execução confirmou o fluxo em CPU sem precisar baixar o modelo durante a análise.

O CI executa o setup, prepara o ambiente de desenvolvimento sem abrir a janela, testa o motor no Windows e verifica a compilação do shell Tauri/MSVC. O instalador NSIS e a primeira abertura em um Windows limpo ainda exigem teste no sistema alvo.

A amostra de fala é sintética. Falta medir o erro de sincronização contra anotações humanas, validar gravações de gameplay e executar os benchmarks de 5, 10, 20, 30 e 60 minutos nos equipamentos da especificação.
