$ErrorActionPreference = "Continue"
foreach ($name in "py", "node", "npm", "rustc", "cargo", "ffmpeg", "ffprobe") {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { Write-Host "$name encontrado em $($command.Source)" }
    else { Write-Warning "$name não encontrado no PATH" }
}
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    ffmpeg -hide_banner -filters 2>&1 | Select-String ' ass '
    foreach ($encoder in "libx264", "h264_nvenc", "h264_qsv") {
        ffmpeg -v error -f lavfi -i "color=s=256x256:r=30" -frames:v 1 -c:v $encoder -f null - 2>$null
        Write-Host "${encoder}: $(if ($LASTEXITCODE -eq 0) { 'funcional' } else { 'indisponível' })"
    }
}
