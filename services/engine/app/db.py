import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

from .config import DATA, DEFAULTS, Problem
from .media import discard_cache

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, source_kind TEXT NOT NULL,
  source_uri TEXT NOT NULL, source_path TEXT, metadata TEXT, analysis TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects ON DELETE CASCADE,
  kind TEXT NOT NULL, status TEXT NOT NULL, phase TEXT, progress REAL, message TEXT,
  error_code TEXT, result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects ON DELETE CASCADE,
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, text TEXT NOT NULL, words TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects ON DELETE CASCADE,
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL CHECK(end_ms > start_ms), title TEXT NOT NULL,
  score INTEGER, reason TEXT, center_x REAL NOT NULL DEFAULT .5, selected INTEGER NOT NULL DEFAULT 1,
  preview_path TEXT, thumbnail_path TEXT, caption_style TEXT NOT NULL DEFAULT 'white',
  framing TEXT NOT NULL DEFAULT 'fit' CHECK(framing IN ('fit', 'fill')),
  effects TEXT NOT NULL DEFAULT 'auto' CHECK(effects IN ('auto', 'motion', 'fade', 'none')),
  automatic INTEGER NOT NULL DEFAULT 0, edited INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cues(
  id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES clips ON DELETE CASCADE,
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
  text TEXT NOT NULL, word_ids TEXT NOT NULL, edited_by_user INTEGER NOT NULL,
  alignment_needs_review INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id = 1), value TEXT NOT NULL);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def uid():
    return str(uuid4())


@lru_cache(maxsize=4)
def engine(path):
    database = create_engine(URL.create("sqlite", database=str(path)), poolclass=NullPool,
                             connect_args={"timeout": 10})

    @event.listens_for(database, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    return database


class Queries:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        return self.connection.exec_driver_sql(sql, parameters).mappings()

    def executemany(self, sql, parameters):
        if parameters:
            self.connection.exec_driver_sql(sql, parameters)


@contextmanager
def connect(write=False):
    with engine(DATA / "clip-factory.sqlite3").begin() as connection:
        if write:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        yield Queries(connection)


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    database = engine(DATA / "clip-factory.sqlite3")
    with database.connect() as connection:
        driver = connection.connection.driver_connection
        driver.execute("PRAGMA journal_mode = WAL")
        driver.executescript(SCHEMA)
    stale = []
    with connect(write=True) as db:
        columns = {column["name"] for column in db.execute("PRAGMA table_info(clips)")}
        if "framing" not in columns:
            db.execute("ALTER TABLE clips ADD COLUMN framing TEXT NOT NULL DEFAULT 'fit' CHECK(framing IN ('fit', 'fill'))")
        if "effects" not in columns:
            db.execute("ALTER TABLE clips ADD COLUMN effects TEXT NOT NULL DEFAULT 'auto' CHECK(effects IN ('auto', 'motion', 'fade', 'none'))")
        if not {"framing", "effects"} <= columns:
            stale = [Path(row["preview_path"]) for row in db.execute(
                "SELECT preview_path FROM clips WHERE preview_path IS NOT NULL")]
            db.execute("UPDATE clips SET preview_path=NULL WHERE preview_path IS NOT NULL")
        db.execute(
            """UPDATE jobs SET status='failed', error_code='INTERRUPTED',
               message='Processamento interrompido. Inicie a tarefa novamente.', updated_at=?
               WHERE status IN ('running','queued')""", (now(),)
        )
    for path in stale:
        if path.parent.resolve().is_relative_to((DATA / "projects").resolve()):
            discard_cache(path)


def decode(row):
    out = dict(row)
    for key in ("metadata", "analysis", "words", "word_ids", "result"):
        if out.get(key) is not None:
            out[key] = json.loads(out[key])
    return out


def get(db, table, identifier):
    # table is selected by the caller, never by a request field.
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise Problem("NOT_FOUND", "Item não encontrado.", 404)
    return decode(row)


def settings(db):
    row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
    return {**DEFAULTS, **(json.loads(row["value"]) if row else {})}


def project_segments(db, project_id):
    return [
        decode(row) for row in db.execute(
            "SELECT * FROM segments WHERE project_id=? ORDER BY start_ms, end_ms", (project_id,)
        )
    ]


def clip_cues(db, clip_id):
    return [
        decode(row) for row in db.execute(
            "SELECT * FROM cues WHERE clip_id=? ORDER BY start_ms, end_ms, rowid", (clip_id,)
        )
    ]


def write_cues(db, clip_id, cues):
    db.execute("DELETE FROM cues WHERE clip_id=?", (clip_id,))
    db.executemany(
        "INSERT INTO cues VALUES (?,?,?,?,?,?,?,?)",
        [
            (uid(), clip_id, cue["start_ms"], cue["end_ms"], cue["text"],
             json.dumps(cue.get("word_ids", [])), bool(cue.get("edited_by_user")),
             bool(cue.get("alignment_needs_review")))
            for cue in cues
        ],
    )
