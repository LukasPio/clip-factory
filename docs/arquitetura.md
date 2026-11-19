# Arquitetura

O Tauri inicia o sidecar e recebe em um pipe uma porta aleatória em loopback e um token de sessão. O frontend obtém a conexão por IPC. A API exige Host e origem esperados e valida o token Bearer. A mídia usa URLs assinadas de curta duração, limitadas a um projeto e, quando aplicável, a um corte.

O SQLite, acessado por SQLAlchemy Core, guarda projetos, tarefas, transcrições, cortes, legendas e preferências. Uma tarefa pesada é executada por vez. Uma segunda instância do motor para o mesmo diretório de dados é bloqueada. Após reiniciar, tarefas que estavam ativas aparecem como interrompidas. A transcrição concluída permanece disponível para uma nova análise com o mesmo modelo, idioma e fonte.

A análise extrai PCM mono 16 kHz, transcreve com timestamps por palavra e salva a transcrição na linha temporal da fonte. Os candidatos são limitados pela fala encontrada. O ranking opcional com Qwen trabalha com IDs e não determina tempos. A geração de legendas agrupa palavras por pausas, pontuação e comprimento. Segmentos sem palavras alinhadas incluem aviso de revisão manual.

Cues persistidos são relativos ao corte. Ao modificar apenas o intervalo do corte, o motor mantém o tempo absoluto das legendas existentes, ajusta os limites ao novo intervalo e descarta as que ficam fora dele. Cues editados junto com o corte são tratados como relativos ao novo intervalo. O deslocamento global modifica os cues durante o salvamento.

Prévias e exportações compartilham o filtro geométrico e as legendas ASS. A saída temporária passa pelo FFprobe antes de ser publicada no diretório de destino. Arquivos existentes não são substituídos. Em exportação de lote cancelada, os MP4 que já haviam sido concluídos são mantidos e listados no resultado da tarefa.

Para links, o yt-dlp usa um proxy local exclusivo que resolve cada destino, bloqueia endereços não públicos e abre a conexão para um dos IPs já verificados. A importação restringe o downloader a arquivos HTTPS simples e tem limites de tempo e volume. FFmpeg recebe caminhos e opções em arrays e usa protocolos e demuxers restritos ao inspecionar a mídia.
