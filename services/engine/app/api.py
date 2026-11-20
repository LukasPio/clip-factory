import hashlib
import hmac
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from . import db, diagnostics, media, pipeline
from .config import PROJECTS, Problem
from .downloader import authority

router = APIRouter()
Title = Annotated[str, Field(min_length=1, max_length=180)]
Time = Annotated[int, Field(ge=0)]
Style = Literal["white", "yellow"]


class ProjectInput(BaseModel):
    title: Title | None = None
    source_kind: Literal["local", "url"]
    source_uri: str = Field(min_length=1, max_length=4096)
    authorized: bool = False


class ProjectPatch(BaseModel):
    title: Title | None = None
    source_uri: str | None = Field(None, min_length=1, max_length=4096)


class Analyze(BaseModel):
    clip_count: int = Field(5, ge=3, le=5)
    min_seconds: int = Field(20, ge=15, le=60)
    max_seconds: int = Field(45, ge=15, le=60)
    language: Literal["auto", "pt"] = "auto"
    use_llm: bool = False
    download_model: bool = False

    @model_validator(mode="after")
    def limits(self):
        if self.min_seconds > self.max_seconds:
            raise ValueError("duração")
        return self


class ClipEdit(BaseModel):
    start_ms: Time | None = None
    end_ms: Time | None = None
    title: Title | None = None
    center_x: float | None = Field(None, ge=0, le=1)
    framing: Literal["fit", "fill"] | None = None
    effects: Literal["auto", "motion", "fade", "none"] | None = None
    selected: bool | None = None
    caption_style: Style | None = None


class Cue(BaseModel):
    start_ms: Time
    end_ms: Time
    text: str = Field(min_length=1, max_length=240)
    id: UUID | None = None


class CueEdit(BaseModel):
    cues: list[Cue] = Field(max_length=1000)
    offset_ms: int = Field(0, ge=-60000, le=60000)


class Edit(ClipEdit):
    subtitles: CueEdit | None = None


class Export(BaseModel):
    project_id: UUID
    clip_ids: list[UUID] = Field(min_length=1, max_length=100)
    output_dir: str = Field(min_length=1, max_length=4096)
    preset: Literal["720p", "1080p"] = "1080p"
    filename: Title | None = None


class Settings(BaseModel):
    whisper_model: Literal["tiny", "base", "small", "medium"] | None = None
    language: Literal["auto", "pt"] | None = None
    use_gpu: bool | None = None
    use_llm: bool | None = None
    default_export_dir: str | None = Field(None, max_length=4096)
    default_caption_style: Style | None = None


@contextmanager
def idle(request):
    jobs = request.app.state.jobs
    with jobs.lock:
        if jobs.active:
            raise Problem("BUSY", "Aguarde ou cancele a tarefa atual.", 409)
        yield jobs


def with_source(project):
    if project["metadata"] is None:
        raise Problem("SOURCE_UNAVAILABLE", "Importe um vídeo antes de iniciar.")
    return project


def timestamps(start, end, duration):
    if not 0 <= start < end <= duration:
        raise Problem("INVALID_TIMECODE", "Confira início e fim. O intervalo deve estar dentro do vídeo ou corte.")


@router.get("/diagnostics")
def diagnose():
    return diagnostics.run()


@router.get("/projects")
def projects():
    with db.connect() as conn:
        return [db.decode(row) for row in conn.execute("SELECT * FROM projects ORDER BY updated_at DESC")]


@router.post("/projects", status_code=201)
def project_create(data: ProjectInput, request: Request):
    identifier, now = db.uid(), db.now()
    if data.source_kind == "local":
        value = str(media.local_source(data.source_uri))
        title = data.title or Path(value).stem[:180]
    else:
        if not data.authorized:
            raise Problem("INVALID_SOURCE", "Confirme que você tem autorização para editar o vídeo.")
        authority(data.source_uri)
        value = data.source_uri
        title = data.title or "Vídeo por link"
    with idle(request) as jobs:
        with db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO projects(id,title,source_kind,source_uri,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (identifier, title, data.source_kind, value, now, now),
            )
            item = db.get(conn, "projects", identifier)
        job_id = jobs.submit(identifier, "import", lambda task: pipeline.import_project(task, item))
    return {**item, "job_id": job_id}


@router.get("/projects/{identifier}")
def project_get(identifier: UUID):
    with db.connect() as conn:
        project = db.get(conn, "projects", str(identifier))
    try:
        pipeline.source_for(project)
        project["source_available"] = True
    except Problem:
        project["source_available"] = False
    return project


@router.patch("/projects/{identifier}")
def project_patch(identifier: UUID, data: ProjectPatch, request: Request):
    identifier = str(identifier)
    with idle(request), db.connect(write=True) as conn:
        item = db.get(conn, "projects", identifier)
        if data.source_uri is not None:
            if item["source_kind"] != "local":
                raise Problem("INVALID_SOURCE", "Apenas a fonte de um projeto local pode ser reconectada.")
            path = media.local_source(data.source_uri)
            metadata = media.probe(path)
            original = item["metadata"]
            if original and any(metadata[k] != original[k] for k in ("duration_ms", "size", "width", "height", "has_audio")):
                raise Problem("INVALID_SOURCE", "Selecione o mesmo vídeo original para preservar a sincronia dos cortes.")
            (PROJECTS / identifier).mkdir(exist_ok=True)
            conn.execute("UPDATE projects SET source_uri=?,source_path=?,metadata=? WHERE id=?",
                         (str(path), str(path), json.dumps(metadata), identifier))
        if data.title is not None:
            conn.execute("UPDATE projects SET title=? WHERE id=?", (data.title, identifier))
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), identifier))
        return db.get(conn, "projects", identifier)


@router.post("/projects/{identifier}/import", status_code=202)
def import_again(identifier: UUID, request: Request):
    identifier = str(identifier)
    with idle(request) as jobs, db.connect() as conn:
        item = db.get(conn, "projects", identifier)
        if item["metadata"]:
            raise Problem("INVALID_SOURCE", "O projeto já tem uma fonte. Use a opção de relocalização.")
        return {"job_id": jobs.submit(identifier, "import", lambda task: pipeline.import_project(task, item))}


@router.delete("/projects/{identifier}")
def project_delete(identifier: UUID, request: Request):
    identifier = str(identifier)
    with idle(request), db.connect(write=True) as conn:
        db.get(conn, "projects", identifier)
        path = PROJECTS / identifier
        if path.exists():
            shutil.rmtree(path)
        conn.execute("DELETE FROM projects WHERE id=?", (identifier,))
    return {"deleted": True}


@router.post("/projects/{identifier}/analyze", status_code=202)
def analyze(identifier: UUID, opts: Analyze, request: Request):
    identifier = str(identifier)
    with idle(request) as jobs, db.connect() as conn:
        project = with_source(db.get(conn, "projects", identifier))
        if not project["metadata"]["has_audio"]:
            raise Problem("NO_AUDIO", "Este vídeo não tem áudio. Crie um corte manual.")
        saved = db.settings(conn)
        job = jobs.submit(identifier, "analyze", lambda task: pipeline.analyze(task, project, opts.model_dump(), saved))
    return {"job_id": job}


@router.get("/projects/{identifier}/clips")
def clips(identifier: UUID):
    with db.connect() as conn:
        db.get(conn, "projects", str(identifier))
        rows = conn.execute("SELECT * FROM clips WHERE project_id=? ORDER BY score DESC, start_ms", (str(identifier),))
        return [decorate_clip(conn, db.decode(row)) for row in rows]


def decorate_clip(conn, clip):
    return {**clip, "cues": db.clip_cues(conn, clip["id"])}


@router.post("/projects/{identifier}/clips", status_code=201)
def clip_create(identifier: UUID, data: ClipEdit, request: Request):
    identifier, clip_id = str(identifier), db.uid()
    with idle(request), db.connect(write=True) as conn:
        project = with_source(db.get(conn, "projects", identifier))
        duration = project["metadata"]["duration_ms"]
        start = data.start_ms if data.start_ms is not None else 0
        end = data.end_ms if data.end_ms is not None else min(duration, start + 30000)
        timestamps(start, end, duration)
        conn.execute(
            """INSERT INTO clips(id,project_id,start_ms,end_ms,title,center_x,selected,caption_style,framing,effects,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (clip_id, identifier, start, end, data.title or "Corte manual", data.center_x if data.center_x is not None else .5,
             data.selected if data.selected is not None else True,
             data.caption_style or db.settings(conn)["default_caption_style"], data.framing or "fit",
             data.effects or "auto", db.now()),
        )
        db.write_cues(conn, clip_id, pipeline.project_cues(db.project_segments(conn, identifier), start, end))
        return decorate_clip(conn, db.get(conn, "clips", clip_id))


def apply_edit(conn, clip, fields, subtitles):
    project = with_source(db.get(conn, "projects", clip["project_id"]))
    start, end = fields.get("start_ms", clip["start_ms"]), fields.get("end_ms", clip["end_ms"])
    timestamps(start, end, project["metadata"]["duration_ms"])
    old = db.clip_cues(conn, clip["id"])
    old_by_id = {item["id"]: item for item in old}
    changed_times = (start, end) != (clip["start_ms"], clip["end_ms"])
    if subtitles is not None:
        cues = []
        for cue in subtitles.cues:
            previous = old_by_id.get(str(cue.id), {})
            left, right = cue.start_ms + subtitles.offset_ms, cue.end_ms + subtitles.offset_ms
            timestamps(left, right, end - start)
            changed = any(previous.get(k) != v for k, v in (("start_ms", left), ("end_ms", right), ("text", cue.text)))
            cues.append({
                "start_ms": left, "end_ms": right, "text": cue.text, "word_ids": previous.get("word_ids", []),
                "edited_by_user": changed or previous.get("edited_by_user", False),
                "alignment_needs_review": previous.get("alignment_needs_review", False) and not changed,
            })
    elif changed_times:
        cues = []
        for cue in old:
            left = max(0, clip["start_ms"] + cue["start_ms"] - start)
            right = min(end - start, clip["start_ms"] + cue["end_ms"] - start)
            if left < right:
                cues.append({**cue, "start_ms": left, "end_ms": right})
    else:
        cues = None
    if cues is not None:
        db.write_cues(conn, clip["id"], cues)
    visual_fields = ("center_x", "caption_style", "framing", "effects")
    if changed_times or subtitles is not None or any(fields.get(k, clip[k]) != clip[k] for k in visual_fields):
        fields["preview_path"] = None
    fields.update(updated_at=db.now(), edited=True)
    assignments = ", ".join(f"{key}=?" for key in fields)
    conn.execute(f"UPDATE clips SET {assignments} WHERE id=?", (*fields.values(), clip["id"]))
    return decorate_clip(conn, db.get(conn, "clips", clip["id"]))


def edit_clip(identifier, fields, subtitles, request):
    with idle(request), db.connect(write=True) as conn:
        clip = db.get(conn, "clips", str(identifier))
        updated = apply_edit(conn, clip, fields, subtitles)
    if updated["preview_path"] != clip["preview_path"]:
        media.discard_cache(clip["preview_path"])
    return updated


@router.patch("/clips/{identifier}")
def clip_patch(identifier: UUID, data: Edit, request: Request):
    fields = data.model_dump(exclude_none=True, exclude={"subtitles"})
    return edit_clip(identifier, fields, data.subtitles, request)


@router.put("/clips/{identifier}/subtitles")
def subtitles(identifier: UUID, data: CueEdit, request: Request):
    return edit_clip(identifier, {}, data, request)


@router.post("/clips/{identifier}/preview", status_code=202)
def preview(identifier: UUID, request: Request):
    with idle(request) as jobs, db.connect() as conn:
        clip = db.get(conn, "clips", str(identifier))
        project = with_source(db.get(conn, "projects", clip["project_id"]))
        return {"job_id": jobs.submit(project["id"], "preview", lambda task: pipeline.preview(task, project, clip))}


def output_directory(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or str(path).replace("/", "\\").startswith("\\\\"):
        raise Problem("PATH_NOT_ALLOWED", "Escolha uma pasta de saída em um disco local.")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise Problem("PATH_NOT_ALLOWED", "A pasta de saída não existe.") from error
    if not path.is_dir() or str(path).replace("/", "\\").startswith("\\\\") or path.is_relative_to(PROJECTS):
        raise Problem("PATH_NOT_ALLOWED", "Escolha uma pasta externa à área de projetos.")
    return path


@router.post("/exports", status_code=202)
def exports(data: Export, request: Request):
    folder = output_directory(data.output_dir)
    with idle(request) as jobs, db.connect() as conn:
        project = with_source(db.get(conn, "projects", str(data.project_id)))
        items = [db.get(conn, "clips", str(item)) for item in dict.fromkeys(data.clip_ids)]
        if any(clip["project_id"] != project["id"] for clip in items) or (data.filename and len(items) != 1):
            raise Problem("INVALID_INPUT", "Selecione cortes do mesmo projeto. Nome personalizado vale para um único corte.")
        gpu = db.settings(conn)["use_gpu"]
        return {"job_id": jobs.submit(project["id"], "export",
                                      lambda task: pipeline.export(task, project, items, folder, data.preset, data.filename, gpu))}


@router.get("/jobs")
def job_list(project_id: UUID | None = None):
    with db.connect() as conn:
        if project_id is None:
            query = conn.execute("SELECT * FROM jobs WHERE status IN ('queued','running')")
        else:
            query = conn.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 25", (str(project_id),))
        return [db.decode(row) for row in query]


@router.get("/jobs/{identifier}")
def job_get(identifier: UUID):
    with db.connect() as conn:
        return db.get(conn, "jobs", str(identifier))


@router.post("/jobs/{identifier}/cancel")
def job_cancel(identifier: UUID, request: Request):
    job_get(identifier)
    request.app.state.jobs.cancel(str(identifier))
    return {"requested": True}


@router.get("/settings")
def get_settings():
    with db.connect() as conn:
        return db.settings(conn)


@router.patch("/settings")
def set_settings(data: Settings, request: Request):
    fields = data.model_dump(exclude_none=True)
    if fields.get("default_export_dir"):
        fields["default_export_dir"] = str(output_directory(fields["default_export_dir"]))
    with idle(request), db.connect(write=True) as conn:
        result = {**db.settings(conn), **fields}
        conn.execute("INSERT OR REPLACE INTO settings VALUES(1,?)", (json.dumps(result),))
    return result


Media = Literal["source", "thumbnail", "clip-thumbnail", "preview"]


def asset(project, kind, clip_id):
    if kind == "source":
        return pipeline.source_for(project)
    root = PROJECTS / project["id"]
    if kind == "thumbnail":
        candidate = root / "source.jpg"
    else:
        if clip_id is None:
            raise Problem("NOT_FOUND", "Mídia do corte indisponível.", 404)
        with db.connect() as conn:
            clip = db.get(conn, "clips", str(clip_id))
        field = "thumbnail_path" if kind == "clip-thumbnail" else "preview_path"
        if clip["project_id"] != project["id"] or not clip[field]:
            raise Problem("NOT_FOUND", "Mídia do corte indisponível.", 404)
        candidate = Path(clip[field])
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise Problem("NOT_FOUND", "Mídia indisponível.", 404)
    return path


def media_signature(request, route, expires, clip_id):
    value = f"{route}:{expires}:{clip_id}".encode()
    return hmac.new(request.app.state.token.encode(), value, hashlib.sha256).hexdigest()


@router.get("/projects/{identifier}/media/{kind}")
def media_url(request: Request, identifier: UUID, kind: Media, clip_id: UUID | None = None):
    project = project_get(identifier)
    asset(project, kind, clip_id)
    route = f"/media/{identifier}/{kind}"
    expires = int(time.time()) + 1800
    query = {"expires": expires, "sig": media_signature(request, route, expires, clip_id)}
    if clip_id is not None:
        query["clip_id"] = str(clip_id)
    return {"url": f"{route}?{urlencode(query)}"}


@router.get("/media/{identifier}/{kind}")
def serve(request: Request, identifier: UUID, kind: Media, expires: int, sig: str, clip_id: UUID | None = None):
    route = f"/media/{identifier}/{kind}"
    expected = media_signature(request, route, expires, clip_id)
    if expires < time.time() or not hmac.compare_digest(expected.encode(), sig.encode()):
        raise Problem("UNAUTHORIZED", "Link de mídia expirado ou inválido.", 401)
    path = asset(project_get(identifier), kind, clip_id)
    content = "image/jpeg" if kind in ("thumbnail", "clip-thumbnail") else {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    }[path.suffix.lower()]
    return FileResponse(path, media_type=content, headers={"X-Content-Type-Options": "nosniff"})
