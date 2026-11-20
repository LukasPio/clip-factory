import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, db, diagnostics, jobs, main, pipeline

AUTH = {"Authorization": "Bearer session"}


@pytest.fixture
def engine_path(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for module in (db, diagnostics, jobs, main, pipeline):
        if hasattr(module, "DATA"):
            monkeypatch.setattr(module, "DATA", data)
    for module in (api, main, pipeline):
        monkeypatch.setattr(module, "PROJECTS", data / "projects")
    return data


@pytest.fixture
def client(engine_path):
    with TestClient(main.create_app("session", "testserver"), headers=AUTH) as client:
        yield client


def wait_job(client, identifier, timeout=40):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        body = client.get(f"/jobs/{identifier}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(.1)
    pytest.fail("A tarefa excedeu o tempo do teste")


def fixture_video(path, audio=True, seconds=5):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe necessários")
    inputs = ["-f", "lavfi", "-i", "color=c=black:s=320x180:r=30"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    subprocess.run([
        "ffmpeg", "-v", "error", *inputs, "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)
    ], check=True)
    return path


def test_auth_and_origin(engine_path):
    with TestClient(main.create_app("session", "testserver")) as unauthenticated:
        assert unauthenticated.get("/health").status_code == 200
        assert unauthenticated.get("/projects").status_code == 401
        assert unauthenticated.get("/health", headers={"Host": "other"}).status_code == 403
        assert unauthenticated.get("/health", headers={"Origin": "https://example.org"}).status_code == 403
        assert unauthenticated.get("/media/invalid/source").status_code == 422


def test_video_end_to_end(client, tmp_path, monkeypatch):
    source = fixture_video(tmp_path / "vídeo original.mp4")
    created = client.post("/projects", json={"source_kind": "local", "source_uri": str(source)})
    assert created.status_code == 201, created.text
    project = created.json()
    identifier = project["id"]
    root = f"/projects/{identifier}"
    assert wait_job(client, project["job_id"])["status"] == "done"
    project = client.get(root).json()
    assert project["metadata"]["has_audio"]
    url = client.get(f"{root}/media/source").json()["url"]
    assert client.get(url, headers={"Range": "bytes=0-127"}).status_code == 206
    assert client.get(url.replace("sig=", "sig=invalid")).status_code == 401
    assert client.patch(root, json={"title": "Teste"}).json()["title"] == "Teste"
    clip = client.post(f"{root}/clips", json={"start_ms": 1000, "end_ms": 4000}).json()
    target = f"/clips/{clip['id']}"
    original = {"start_ms": 600, "end_ms": 1500, "text": "Legenda real"}
    edited = client.patch(target, json={"title": "Trecho testado", "center_x": .8, "subtitles": {"cues": [original]}})
    assert edited.status_code == 200, edited.text
    invalid = client.patch(target, json={"title": "Inválido", "subtitles": {"cues": [{**original, "end_ms": 4000}]}})
    assert invalid.status_code == 400
    moved = client.patch(target, json={"start_ms": 1300}).json()
    assert moved["title"] == "Trecho testado"
    assert (moved["cues"][0]["start_ms"], moved["cues"][0]["end_ms"]) == (300, 1200)
    preview = client.post(f"{target}/preview").json()
    result = wait_job(client, preview["job_id"])
    assert result["status"] == "done", result
    assert client.get(f"{root}/media/preview", params={"clip_id": clip["id"]}).status_code == 200

    old_preview = Path(result["result"]["path"])
    unlink = Path.unlink

    def unlink_while_playing(path, *args, **kwargs):
        if path == old_preview:
            raise PermissionError("preview is still open")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as playing:
        playing.setattr(Path, "unlink", unlink_while_playing)
        refreshed = wait_job(client, client.post(f"{target}/preview").json()["job_id"])
        assert refreshed["status"] == "done", refreshed

    old_preview = Path(refreshed["result"]["path"])
    with monkeypatch.context() as playing:
        playing.setattr(Path, "unlink", unlink_while_playing)
        edited = client.patch(target, json={"center_x": .6})
        assert edited.status_code == 200, edited.text
        assert edited.json()["preview_path"] is None

    payload = {"project_id": identifier, "clip_ids": [clip["id"]], "output_dir": str(tmp_path), "preset": "1080p"}
    export = wait_job(client, client.post("/exports", json=payload).json()["job_id"])
    assert export["status"] == "done", export
    output = Path(export["result"]["files"][0]["path"])
    meta = pipeline.media.probe(output)
    assert (meta["width"], meta["height"], meta["video_codec"], meta["audio_codec"], meta["fps"]) == (1080, 1920, "h264", "aac", 30)
    assert abs(meta["duration_ms"] - 2700) < 150

    def brightest(at):
        pixels = subprocess.check_output([
            "ffmpeg", "-v", "error", "-ss", at, "-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"
        ])
        return max(pixels)

    assert brightest("0.1") < 20
    assert brightest("0.7") > 180
    assert brightest("1.8") < 20
    repeat = wait_job(client, client.post("/exports", json=payload).json()["job_id"])
    assert repeat["error_code"] == "OUTPUT_EXISTS"
    assert client.get(f"{root}/clips").json()[0]["cues"][0]["text"] == "Legenda real"
    db.initialize()
    assert client.get(f"{root}/clips").json()[0]["title"] == "Trecho testado"
    assert client.delete(root).status_code == 200
    assert source.is_file() and output.is_file()


def test_no_audio_and_unsafe_path(client, tmp_path):
    invalid = client.post("/projects", json={"source_kind": "local", "source_uri": "../secret.mp4"})
    assert invalid.status_code == 400
    bogus = tmp_path / "falso.mp4"
    bogus.write_text("file 'private.mp4'\n")
    rejected = client.post("/projects", json={"source_kind": "local", "source_uri": str(bogus)}).json()
    assert wait_job(client, rejected["job_id"])["error_code"] == "UNSUPPORTED_MEDIA"
    source = fixture_video(tmp_path / "sem-audio.mp4", audio=False)
    project = client.post("/projects", json={"source_kind": "local", "source_uri": str(source)}).json()
    assert wait_job(client, project["job_id"])["status"] == "done"
    root = f"/projects/{project['id']}"
    assert client.post(f"{root}/analyze", json={}).json()["error"]["code"] == "NO_AUDIO"
    assert client.post(f"{root}/clips", json={}).status_code == 201


def test_cancel_running_subprocess(client, tmp_path):
    import sys
    import threading

    source = fixture_video(tmp_path / "cancel.mp4")
    project = client.post("/projects", json={"source_kind": "local", "source_uri": str(source)}).json()
    assert wait_job(client, project["job_id"])["status"] == "done"
    manager = client.app.state.jobs
    started = threading.Event()

    def work(task):
        task.command([sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(120)"],
                     on_line=lambda _: started.set())

    job_id = manager.submit(project["id"], "test", work)
    assert started.wait(5)
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 200
    assert wait_job(client, job_id, 8)["status"] == "cancelled"


def test_analysis_reuses_transcript_and_keeps_the_conclusion_in_the_preview(client, tmp_path):
    source = fixture_video(tmp_path / "café.mp4", seconds=27)
    project = client.post("/projects", json={"source_kind": "local", "source_uri": str(source)}).json()
    assert wait_job(client, project["job_id"])["status"] == "done"
    identifier = project["id"]
    root = f"/projects/{identifier}"
    stat = source.stat()
    passages = [
        (1000, 4500, "Por que o café da esquina quase fechou?"),
        (4700, 10000, "Tive medo de fechar o café porque o movimento caiu depois da obra."),
        (10200, 16300, "Em vez de esperar a rua abrir, começamos a levar café para os vizinhos."),
        (16500, 23200, "No fim, as entregas salvaram o café e recuperamos todos os empregos."),
        (23300, 26000, "Mudando de assunto, vamos ao jogo de amanhã."),
    ]
    with db.connect(write=True) as conn:
        conn.execute("UPDATE projects SET analysis=? WHERE id=?", (json.dumps({
            "transcript_key": ["base", "pt", stat.st_mtime_ns, stat.st_size], "language": "pt",
            "device": "cpu", "segment_count": len(passages),
        }), identifier))
        conn.executemany("INSERT INTO segments VALUES (?,?,?,?,?,?)",
                         [(db.uid(), identifier, start, end, text, "[]") for start, end, text in passages])

    response = client.post(f"{root}/analyze", json={"language": "pt", "min_seconds": 15, "max_seconds": 25})
    result = wait_job(client, response.json()["job_id"])
    assert result["status"] == "done" and result["result"]["count"] == 1, result
    [clip] = client.get(f"{root}/clips").json()
    assert 23200 <= clip["end_ms"] <= 23300
    assert "recuperamos todos os empregos." in " ".join(clip["cues"][-1]["text"].split())
    assert all("jogo" not in cue["text"] for cue in clip["cues"])

    preview = client.post(f"/clips/{clip['id']}/preview").json()
    preview_job = wait_job(client, preview["job_id"])
    assert preview_job["status"] == "done", preview_job
    assert abs(preview_job["result"]["duration_ms"] - (clip["end_ms"] - clip["start_ms"])) < 150


def test_real_whisper_cpu(client, monkeypatch, tmp_path):
    source = os.environ.get("CLIP_FACTORY_ASR_FIXTURE")
    cache = os.environ.get("CLIP_FACTORY_ASR_MODELS")
    if not source or not cache:
        pytest.skip("Informe fixture própria em português e cache Whisper tiny")
    monkeypatch.setenv("CLIP_FACTORY_DATA", str(Path(cache).parent))
    project = client.post("/projects", json={"source_kind": "local", "source_uri": source}).json()
    assert wait_job(client, project["job_id"])["status"] == "done"
    identifier = project["id"]
    client.patch("/settings", json={"whisper_model": "tiny", "use_gpu": False})
    job = client.post(f"/projects/{identifier}/analyze", json={
        "language": "pt", "min_seconds": 15, "max_seconds": 35, "clip_count": 3
    }).json()
    result = wait_job(client, job["job_id"], 250)
    assert result["status"] == "done", result
    assert result["result"]["language"] == "pt" and result["result"]["device"] == "cpu"
    assert result["result"]["segment_count"] > 0
    clips = client.get(f"/projects/{identifier}/clips").json()
    assert clips and any(cue for clip in clips for cue in clip["cues"] if not cue["alignment_needs_review"])
    with db.connect() as conn:
        words = [word for segment in db.project_segments(conn, identifier) for word in segment["words"]]
    assert len(words) > 30
    assert result["result"]["ranking"] == "heuristic"
    clip = clips[0]
    assert client.get(f"/projects/{identifier}/media/clip-thumbnail", params={"clip_id": clip["id"]}).status_code == 200
    output = client.post("/exports", json={
        "project_id": identifier, "clip_ids": [clip["id"]], "output_dir": str(tmp_path), "preset": "1080p"
    }).json()
    exported = wait_job(client, output["job_id"], 90)
    assert exported["status"] == "done", exported
    metadata = pipeline.media.probe(Path(exported["result"]["files"][0]["path"]))
    assert (metadata["width"], metadata["height"], metadata["fps"], metadata["video_codec"], metadata["audio_codec"]) == (
        1080, 1920, 30, "h264", "aac",
    )
    assert abs(metadata["duration_ms"] - clip["end_ms"] + clip["start_ms"]) < 150
    print(json.dumps({"segments": result["result"]["segment_count"], "words": len(words), "clips": len(clips),
                      "export": metadata}, ensure_ascii=False))
