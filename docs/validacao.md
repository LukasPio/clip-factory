# Validação

O ambiente de desenvolvimento Linux permite testar o motor, o frontend web e a saída FFmpeg. Os critérios referentes ao instalador e ao hardware alvo precisam de uma execução no Windows x64.

| Cenário | Verificação |
| --- | --- |
| MP4 original local | Importação real e metadados confirmados por FFprobe. |
| Recorte e sincronização de ASS | Teste decodifica quadros antes, durante e depois da legenda manual em um corte iniciado no meio da fonte. |
| Exportação | 1080 × 1920, H.264, 30 FPS e AAC validados por FFprobe em corte de 2,7 s. |
| Transcrição Whisper em CPU | Fixture de 89,53 s com fala sintética em português, modelo tiny/int8, 16 segmentos, 268 palavras alinhadas e três cortes sugeridos por heurísticas. |
| Frontend | Build de produção concluído e três testes Vitest aprovados. O smoke Playwright foi incluído, mas não teve execução conclusiva neste ambiente. |
| Falhas comuns | Arquivo com formato incompatível, vídeo sem áudio, cancelamento de subprocesso e tentativa de sobrescrever saída. |
| Persistência | Projeto, título e legendas lidos novamente do SQLite após inicialização. |
| URL | Bloqueio de URLs inválidas ou destinos não públicos verificado. A tentativa com URL pública terminou na resolução de DNS deste ambiente. |
| Windows e GPU | NSIS, início após instalação limpa, WebView2, CUDA/NVENC e desempenho no hardware alvo ainda exigem validação. |

A suíte do motor sem modelo teve 15 testes aprovados e um caso de ASR optativo. O caso real de ASR passou isoladamente antes da última ampliação do teste. A revisão automática bloqueou as reexecuções ampliadas com ASR após detectar tráfego de telemetria não autorizado para a Microsoft. O worker desativa a telemetria pelas opções públicas do ONNX Runtime e do Hugging Face. A revisão também bloqueou uma reexecução com essas opções ativadas, então ainda é necessário investigar o tráfego antes de certificar o requisito de privacidade ou executar esse teste automaticamente no CI.

O `cargo check` do alvo MSVC executado no Linux chegou ao build do aplicativo e parou pela ausência de `llvm-rc`. O CI inclui o check nativo no Windows. A distribuição NSIS ainda depende de teste no sistema alvo.

A amostra de fala é sintética. Falta medir o erro de sincronização contra anotações humanas, validar gravações de gameplay e executar os benchmarks de 5, 10, 20, 30 e 60 minutos nos equipamentos da especificação.
