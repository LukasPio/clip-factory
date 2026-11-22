import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, db, diagnostics, downloader, jobs, main, pipeline

AUTH = {"Authorization": "Bearer session"}


@pytest.fixture
def engine_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_FACTORY_MODE", "test")
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


def test_large_local_import_keeps_sparse_original(client, engine_path, tmp_path):
    source = fixture_video(tmp_path / "gravação esparsa.mp4", seconds=1)
    if os.name == "nt":
        sparse = subprocess.run(["fsutil", "sparse", "setflag", str(source)], capture_output=True)
        if sparse.returncode:
            pytest.skip("A unidade de testes não oferece arquivos esparsos no Windows")
    original_size = source.stat().st_size
    large_size = 21_000_000_000
    with source.open("ab") as video:
        video.write(struct.pack(">I4sQ", 1, b"free", large_size - original_size))
        video.truncate(large_size)

    project = client.post("/projects", json={"source_kind": "local", "source_uri": str(source)}).json()
    job = wait_job(client, project["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["metadata"]["size"] == large_size
    saved = client.get(f"/projects/{project['id']}").json()
    assert Path(saved["source_path"]) == source.resolve()
    assert sorted(path.name for path in (engine_path / "projects" / project["id"]).iterdir()) == ["source.jpg"]


def test_download_settings_persist_across_engine_restart(engine_path, monkeypatch):
    with TestClient(main.create_app("session", "testserver"), headers=AUTH) as first:
        assert first.patch("/settings", json={"whisper_model": "small"}).status_code == 200
    monkeypatch.delenv("CLIP_FACTORY_MODE")
    with TestClient(main.create_app("session", "testserver"), headers=AUTH) as production:
        settings = production.get("/settings").json()
        assert settings["download_limit_gb"] == 20 and settings["download_disk_free"] > 0
        for invalid in (0, -1, 1.5, True, "6"):
            assert production.patch("/settings", json={"download_limit_gb": invalid}).status_code == 422
        assert production.patch("/settings", json={"whisper_model": "small"}).status_code == 403
        updated = production.patch("/settings", json={"download_limit_gb": 32}).json()
        assert updated["download_limit_gb"] == 32 and updated["mode"] == "production"
    monkeypatch.setenv("CLIP_FACTORY_MODE", "test")
    with TestClient(main.create_app("session", "testserver"), headers=AUTH) as restarted:
        settings = restarted.get("/settings").json()
        assert settings["download_limit_gb"] == 32 and settings["whisper_model"] == "small"


@pytest.mark.parametrize("stop", ["cancel", "disk"])
def test_interrupted_download_removes_scratch(client, engine_path, monkeypatch, stop):
    def fake_worker(kind, output, url, limit_gb):
        assert kind == "download" and limit_gb == 32
        return [sys.executable, "-c",
                "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(120)",
                str(output.parent / "source.mp4.part")]

    monkeypatch.setattr(pipeline, "worker", fake_worker)
    monkeypatch.setattr(downloader, "free_space", lambda path: 50_000_000_000)
    assert client.patch("/settings", json={"download_limit_gb": 32}).status_code == 200
    project = client.post("/projects", json={
        "source_kind": "url", "source_uri": "https://example.com/video", "authorized": True,
    }).json()
    folder = engine_path / "projects" / project["id"]
    deadline = time.monotonic() + 10
    while not list(folder.glob("download-*/source.mp4.part")):
        assert time.monotonic() < deadline, client.get(f"/jobs/{project['job_id']}").json()
        time.sleep(.05)
    if stop == "cancel":
        assert client.post(f"/jobs/{project['job_id']}/cancel").is_success
    else:
        monkeypatch.setattr(downloader, "free_space", lambda path: downloader.DISK_RESERVE - 1)
    job = wait_job(client, project["job_id"])
    assert job["error_code"] == ("CANCELLED" if stop == "cancel" else "DISK_FULL"), job
    assert not list(folder.iterdir())


def test_existing_clips_switch_to_full_frame_without_losing_edits(engine_path):
    engine_path.mkdir()
    legacy = "\n".join(line for line in db.SCHEMA.splitlines() if not any(
        feature in line for feature in ("framing TEXT", "effects TEXT")))
    with db.engine(engine_path / "clip-factory.sqlite3").connect() as conn:
        conn.connection.driver_connection.executescript(legacy)
    project_id, clip_id = db.uid(), db.uid()
    old_preview = engine_path / "projects" / project_id / f"{clip_id}-old.mp4"
    old_preview.parent.mkdir(parents=True)
    old_preview.touch()
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO projects(id,title,source_kind,source_uri,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                     (project_id, "Projeto", "local", "original.mp4", db.now(), db.now()))
        conn.execute("""INSERT INTO clips(id,project_id,start_ms,end_ms,title,center_x,preview_path,edited,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (clip_id, project_id, 1000, 4000, "Corte editado", .7, str(old_preview), 1, db.now()))
    db.initialize()
    with db.connect() as conn:
        clip = db.get(conn, "clips", clip_id)
    assert (clip["framing"], clip["preview_path"], clip["title"], clip["center_x"], clip["edited"]) == (
        "fit", None, "Corte editado", .7, 1)
    assert not old_preview.exists()
    assert clip["effects"] == "auto"


def test_preview_preserves_both_edges_and_invalidates_cache_when_framing_changes(client, tmp_path):
    source = fixture_video(tmp_path / "framing-base.mp4", seconds=2)
    marked = tmp_path / "framing.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vf",
                    "drawbox=x=0:y=0:w=60:h=ih:c=red:t=fill,drawbox=x=260:y=0:w=60:h=ih:c=blue:t=fill",
                    str(marked)], check=True)
    project = client.post("/projects", json={"source_kind": "local", "source_uri": str(marked)}).json()
    assert wait_job(client, project["job_id"])["status"] == "done"
    clip = client.post(f"/projects/{project['id']}/clips", json={}).json()
    assert clip["framing"] == "fit"
    target = f"/clips/{clip['id']}"

    def frame():
        job = wait_job(client, client.post(f"{target}/preview").json()["job_id"])
        assert job["status"] == "done", job
        return subprocess.check_output(["ffmpeg", "-v", "error", "-i", job["result"]["path"],
                                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])

    fit = frame()
    assert len(fit) == 540 * 960 * 3
    left, right = ((480 * 540 + x) * 3 for x in (30, 510))
    assert fit[left] > 200 and fit[right + 2] > 200
    updated = client.patch(target, json={"framing": "fill"}).json()
    assert updated["preview_path"] is None
    fill = frame()
    assert max(fill[left:left + 3] + fill[right:right + 3]) < 30
    assert client.patch(target, json={"framing": "fit", "effects": "motion"}).json()["preview_path"] is None
    motion = frame()
    assert motion[left] > 200 and motion[right + 2] > 200
    assert client.patch(target, json={"effects": "fade"}).json()["preview_path"] is None
    faded = frame()
    assert max(faded[left:left + 3] + faded[right:right + 3]) < 30


def test_caption_highlight_uses_the_actual_word_timing(tmp_path):
    class ClipCaptions:
        def execute(self, *_args):
            return [
                {"text": "Olá\nmundo", "start_ms": 400, "end_ms": 1700, "word_ids": '["first", "last"]'},
                {"text": "Texto manual", "start_ms": 1850, "end_ms": 2050, "word_ids": "[]"},
            ]

    clip = {"id": "clip", "start_ms": 10000}
    cues = pipeline.render_cues(ClipCaptions(), clip, {
        "first": {"text": "Olá", "start_ms": 10200, "end_ms": 10500},
        "last": {"text": "mundo", "start_ms": 11200, "end_ms": 11500},
    })
    captions = tmp_path / "captions.ass"
    pipeline.media.write_ass(captions, cues, "white")
    events = [line for line in captions.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 4
    assert "0:00:00.40,0:00:00.70" in events[0] and r"{\1c&H24DCFF&}OLÁ{\r}\NMUNDO" in events[0]
    assert r"OLÁ\NMUNDO" in events[1] and r"\1c" not in events[1]
    assert "0:00:01.40,0:00:01.70" in events[2] and r"OLÁ\N{\1c&H24DCFF&}MUNDO{\r}" in events[2]
    assert events[3].endswith("TEXTO MANUAL") and r"\1c" not in events[3]


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


@pytest.mark.parametrize("mode", ["test", "production"])
def test_analysis_reuses_transcript_and_keeps_the_conclusion_in_the_preview(client, tmp_path, monkeypatch, mode):
    from contextlib import nullcontext
    from app import editorial

    monkeypatch.setenv("CLIP_FACTORY_MODE", mode)
    prepared, reviewed = [], []
    endpoint = "http://127.0.0.1:41212"
    monkeypatch.setattr(pipeline, "ollama_server", lambda _task: nullcontext(endpoint))
    monkeypatch.setattr(pipeline, "prepare_production_review", lambda task, address: prepared.append(address))

    def review(batch, *, model, endpoint, **_kwargs):
        assert endpoint in prepared
        reviewed.append(model)
        return {item["candidate_id"]: editorial.Rank(candidate_id=item["candidate_id"], usable=True, score=90,
                title="Como o café recuperou os empregos", reason="Mostra o problema e o desfecho.") for item in batch}

    monkeypatch.setattr(editorial, "ollama_ranks", review)
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
            "transcript_key": ["medium", "auto", stat.st_mtime_ns, stat.st_size] if mode == "production" else
            ["base", "pt", stat.st_mtime_ns, stat.st_size], "language": "pt",
            "device": "cpu", "segment_count": len(passages),
        }), identifier))
        conn.executemany("INSERT INTO segments VALUES (?,?,?,?,?,?)",
                         [(db.uid(), identifier, start, end, text, "[]") for start, end, text in passages])

    response = client.post(f"{root}/analyze", json={"language": "pt", "min_seconds": 15, "max_seconds": 25, "use_llm": False})
    result = wait_job(client, response.json()["job_id"])
    assert result["status"] == "done" and result["result"]["count"] == 1, result
    [clip] = client.get(f"{root}/clips").json()
    assert 23200 <= clip["end_ms"] <= 23300
    assert "recuperamos todos os empregos." in " ".join(clip["cues"][-1]["text"].split())
    assert all("jogo" not in cue["text"] for cue in clip["cues"])
    if mode == "production":
        assert prepared == [endpoint] and reviewed == [editorial.PRODUCTION_QWEN]
        assert client.patch("/settings", json={"use_llm": False}).status_code == 403
        assert result["result"]["ranking"] == "hybrid"

        def unavailable(*_args, **_kwargs):
            raise OSError("local service stopped")

        monkeypatch.setattr(editorial, "ollama_ranks", unavailable)
        retry = client.post(f"{root}/analyze", json={"use_llm": False}).json()
        failed = wait_job(client, retry["job_id"])
        assert failed["error_code"] == "OLLAMA_REVIEW_FAILED"
        assert [item["id"] for item in client.get(f"{root}/clips").json()] == [clip["id"]]
    else:
        assert not prepared and not reviewed and result["result"]["ranking"] == "heuristic"

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
