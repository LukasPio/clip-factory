import json
import os
import shutil
import tempfile
import wave
from pathlib import Path

from . import db, media
from .config import DATA, MODELS, PROJECTS, Problem, safe_filename, worker
from .downloader import MAX_BYTES
from .editorial import candidates, normalize_segments, project_cues, rank_options


def source_for(project):
    path = media.local_source(project["source_path"] or "")
    if project["source_kind"] == "url" and not path.is_relative_to(PROJECTS / project["id"]):
        raise Problem("PATH_NOT_ALLOWED", "Vídeo baixado fora da pasta do projeto.")
    return path


def worker_main(kind, args):
    def report(message, progress=None):
        print(json.dumps({"message": message, "progress": progress}, ensure_ascii=True), flush=True)

    output = Path(args[0])
    try:
        if kind == "download":
            from .downloader import download
            result = download(args[1], output.parent, lambda progress: report("Baixando vídeo", progress))
        else:
            result = transcribe(*args[1:], report=report)
    except Problem as error:
        result = {"error": error.code, "message": str(error)}
    except ImportError:
        result = {"error": "DEPENDENCY_MISSING", "message": "Instale as dependências do motor e tente novamente."}
    except Exception:
        result = ({"error": "SOURCE_UNAVAILABLE", "message": "A plataforma bloqueou o vídeo ou não forneceu um arquivo compatível."}
                  if kind == "download" else
                  {"error": "ASR_FAILED", "message": "Falha na transcrição. Verifique o modelo, a memória e o diagnóstico."})
    output.write_text(json.dumps(result), encoding="utf-8")


def transcribe(audio, model_name, language, use_gpu, consent, duration, *, report):
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import numpy as np
    import onnxruntime

    onnxruntime.disable_telemetry_events()
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download

    repo = f"Systran/faster-whisper-{model_name}"
    cache = MODELS / model_name
    if not (cache / "model.bin").is_file() or not (cache / "tokenizer.json").is_file():
        if consent != "1":
            raise Problem("MODEL_MISSING", "Autorize o download do modelo de voz para iniciar.")
        MODELS.mkdir(parents=True, exist_ok=True)
        media.disk(MODELS, 2_500_000_000)
        report(f"Baixando modelo Whisper {model_name}")
        try:
            snapshot_download(repo, local_dir=cache, token=False, allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
        except Exception as error:
            raise Problem("MODEL_MISSING", "Download do modelo falhou. Verifique a conexão e tente novamente.") from error
    with wave.open(audio, "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)
        pcm /= 32768
    device = "cuda" if use_gpu == "1" else "cpu"
    fallback = False
    while True:
        report(f"Transcrevendo com {'CUDA' if device == 'cuda' else 'CPU / int8'}")
        try:
            model = WhisperModel(str(cache), device=device, compute_type="int8_float16" if device == "cuda" else "int8",
                                 cpu_threads=4, local_files_only=True)
            chunks, info = model.transcribe(pcm, language=None if language == "auto" else language,
                                             vad_filter=True, word_timestamps=True)

            def timed():
                last = -1
                for chunk in chunks:
                    current = min(99, round(chunk.end * 100_000 / int(duration)))
                    if current > last:
                        report(f"Transcrevendo com {'CUDA' if device == 'cuda' else 'CPU / int8'}", current / 100)
                        last = current
                    yield chunk

            segments = normalize_segments(timed(), int(duration))
            return {"segments": segments, "language": info.language, "device": device, "fallback": fallback}
        except (RuntimeError, OSError, ValueError):
            if device != "cuda":
                raise
            device = "cpu"
            fallback = True
        finally:
            model = None


def worker_result(task, kind, output, *args, timeout):
    def progress(line):
        try:
            update = json.loads(line)
        except ValueError:
            return
        if "message" in update:
            value = update.get("progress")
            task.update(message=update["message"], progress=None if value is None else min(1, max(0, value)))

    task.command(worker(kind, output, *args), timeout=timeout, on_line=progress,
                 code="WORKER_FAILED", message="O processamento excedeu o tempo ou falhou. Tente novamente.")
    result = json.loads(output.read_text(encoding="utf-8"))
    if result.get("error"):
        raise Problem(result["error"], result["message"])
    return result


def import_project(task, project):
    identifier = project["id"]
    folder = PROJECTS / identifier
    folder.mkdir(exist_ok=True)
    if project["source_kind"] == "local":
        task.phase("inspecting", "Inspecionando fonte")
        path = media.local_source(project["source_uri"])
        metadata = media.probe(path)
        title = None
    else:
        task.phase("downloading", "Verificando link público")
        media.disk(folder, MAX_BYTES + 100_000_000)
        with tempfile.TemporaryDirectory(dir=folder, prefix="download-") as scratch:
            result = worker_result(task, "download", Path(scratch) / "result.json", project["source_uri"], timeout=900)
            path = folder / result["file"]
            downloaded = Path(scratch) / path.name
            metadata = media.probe(downloaded)
            task.check()
            downloaded.replace(path)
            title = result["title"]
    try:
        media.thumbnail(task, path, metadata, folder / "source.jpg")
    except Problem as error:
        if error.code == "CANCELLED":
            raise
    task.check()
    with db.connect(write=True) as conn:
        conn.execute(
            "UPDATE projects SET source_path=?,metadata=?,title=?,updated_at=? WHERE id=?",
            (str(path), json.dumps(metadata), title if title and project["title"] == "Vídeo por link" else project["title"],
             db.now(), identifier),
        )
    return {"metadata": metadata, "message": "Vídeo importado."}


def clip_thumbnail(task, project, source, item):
    filename = f"{item['id']}.jpg"
    path = PROJECTS / project["id"] / filename
    try:
        media.thumbnail(task, source, project["metadata"], path, (item["start_ms"] + item["end_ms"]) // 2)
    except Problem as error:
        if error.code == "CANCELLED":
            raise
        return
    with db.connect(write=True) as conn:
        conn.execute("UPDATE clips SET thumbnail_path=? WHERE id=?", (str(path), item["id"]))


def analyze(task, project, opts, settings):
    source = source_for(project)
    metadata = project["metadata"]
    if not metadata["has_audio"]:
        raise Problem("NO_AUDIO", "O vídeo não tem áudio. Crie um corte manual.")
    identifier = project["id"]
    folder = PROJECTS / identifier
    duration = metadata["duration_ms"]
    model = settings["whisper_model"]
    key = [model, opts["language"], source.stat().st_mtime_ns, source.stat().st_size]
    analysis = project["analysis"] or {}
    if analysis.get("transcript_key") == key:
        with db.connect() as conn:
            segments = db.project_segments(conn, identifier)
    else:
        with tempfile.TemporaryDirectory(dir=folder, prefix="analysis-") as scratch:
            audio = Path(scratch) / "audio.wav"
            task.phase("audio", "Extraindo áudio")
            media.extract(task, source, metadata, audio)
            task.phase("transcribing", "Preparando reconhecimento de voz")
            result = worker_result(task, "transcribe", Path(scratch) / "result.json", audio, model, opts["language"],
                                   int(settings["use_gpu"]), int(opts["download_model"]), duration, timeout=28800)
        task.check()
        segments = result["segments"]
        analysis = {"transcript_key": key, "language": result["language"], "device": result["device"],
                    "cpu_fallback": result["fallback"], "segment_count": len(segments)}
        with db.connect(write=True) as conn:
            conn.execute("DELETE FROM segments WHERE project_id=?", (identifier,))
            conn.executemany(
                "INSERT INTO segments VALUES (?,?,?,?,?,?)",
                [(seg["id"], identifier, seg["start_ms"], seg["end_ms"], seg["text"], json.dumps(seg["words"])) for seg in segments],
            )
            conn.execute("UPDATE projects SET analysis=?,updated_at=? WHERE id=?", (json.dumps(analysis), db.now(), identifier))
    task.phase("ranking", "Selecionando trechos da transcrição")
    options = candidates(segments, duration, opts["min_seconds"] * 1000, opts["max_seconds"] * 1000)
    selected, mode = rank_options(task, options, opts["clip_count"], opts["use_llm"])
    task.check()
    created = []
    with db.connect(write=True) as conn:
        obsolete = list(conn.execute(
            "SELECT thumbnail_path, preview_path FROM clips WHERE project_id=? AND automatic=1 AND edited=0", (identifier,),
        ))
        conn.execute("DELETE FROM clips WHERE project_id=? AND automatic=1 AND edited=0", (identifier,))
        for item in selected:
            existing = conn.execute("SELECT 1 FROM clips WHERE project_id=? AND start_ms=? AND end_ms=?",
                                    (identifier, item["start_ms"], item["end_ms"])).fetchone()
            if not existing:
                clip_id = db.uid()
                conn.execute(
                    """INSERT INTO clips(id, project_id, start_ms, end_ms, title, score, reason, caption_style, automatic, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,1,?)""",
                    (clip_id, identifier, item["start_ms"], item["end_ms"], item["title"], item["score"], item["reason"],
                     settings["default_caption_style"], db.now()),
                )
                db.write_cues(conn, clip_id, project_cues(segments, item["start_ms"], item["end_ms"]))
                created.append({**item, "id": clip_id})
        summary = "Sugestões geradas." if len(selected) == opts["clip_count"] else (
            f"{len(selected)} sugestões geradas. A fala disponível não rendeu mais trechos distintos nos limites escolhidos."
        )
        analysis.update(ranking=mode, message=summary)
        conn.execute("UPDATE projects SET analysis=?,updated_at=? WHERE id=?", (json.dumps(analysis), db.now(), identifier))
    for row in obsolete:
        media.discard_cache(row["thumbnail_path"])
        media.discard_cache(row["preview_path"])
    if created:
        task.phase("thumbnails", "Gerando miniaturas dos cortes")
        for item in created:
            clip_thumbnail(task, project, source, item)
    return {**analysis, "count": len(selected), "message": summary}


def preview(task, project, clip):
    source = source_for(project)
    folder = PROJECTS / project["id"]
    path = folder / f"{clip['id']}-{task.id}.mp4"
    task.phase("preview", "Renderizando prévia vertical", 0)
    with db.connect() as conn:
        cues = db.clip_cues(conn, clip["id"])
    result = media.render(task, source, project["metadata"], clip, cues, path, "preview")
    with db.connect(write=True) as conn:
        conn.execute("UPDATE clips SET preview_path=? WHERE id=?", (str(path), clip["id"]))
    media.discard_cache(clip["preview_path"])
    return result


def export(task, project, clips, folder, preset, name, gpu):
    source = source_for(project)
    outputs = []
    names = set()
    for index, clip in enumerate(clips, 1):
        base = safe_filename(name or clip["title"])
        filename = f"{base}.mp4"
        if filename.casefold() in names:
            filename = f"{base}-{clip['id'][:8]}.mp4"
        names.add(filename.casefold())
        if (folder / filename).exists():
            raise Problem("OUTPUT_EXISTS", f"O arquivo {filename} já existe. Escolha outro nome ou pasta.")
        outputs.append(folder / filename)
    files = []
    for index, (clip, output) in enumerate(zip(clips, outputs), 1):
        task.phase("export", f"Exportando {index} de {len(clips)}", 0)
        with db.connect() as conn:
            cues = db.clip_cues(conn, clip["id"])
        files.append(media.render(task, source, project["metadata"], clip, cues, output, preset, gpu))
        task.update(result=json.dumps({"files": files}))
    fallback = gpu and any(file["encoder"] == "libx264" for file in files)
    return {"files": files, "message": "Exportação concluída em CPU para os cortes sem NVENC." if fallback else "Exportação concluída."}
