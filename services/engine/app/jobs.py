import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock

from .config import DATA, Problem
from .db import connect, now, uid

log = logging.getLogger("clip-factory")


class Jobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine")
        self.active = {}
        self.lock = RLock()
        self.closing = False

    def submit(self, project_id, kind, callback):
        with self.lock:
            if self.closing:
                raise Problem("BUSY", "O motor está encerrando.", 409)
            if self.active:
                raise Problem("BUSY", "Aguarde ou cancele a tarefa atual.", 409)
            identifier = uid()
            timestamp = now()
            with connect(write=True) as db:
                db.execute(
                    """INSERT INTO jobs(id, project_id, kind, status, phase, message, created_at, updated_at)
                       VALUES(?,?,?,'queued','queued','Na fila',?,?)""",
                    (identifier, project_id, kind, timestamp, timestamp),
                )
            job = Task(identifier)
            self.active[identifier] = job
            self.pool.submit(self._run, job, callback)
            return identifier

    def _run(self, job, callback):
        started = time.monotonic()
        try:
            job.update(status="running")
            result = callback(job)
            fields = {"status": "done", "progress": 1, "result": json.dumps(result),
                      "message": result.get("message", "Concluído.")}
        except Problem as error:
            fields = {"status": "cancelled" if error.code == "CANCELLED" else "failed",
                      "error_code": error.code, "message": str(error)}
        except Exception as error:
            log.error("job=%s unexpected=%s", job.id, type(error).__name__)
            fields = {"status": "failed", "error_code": "INTERNAL_ERROR",
                      "message": "Falha interna. Consulte o diagnóstico e tente novamente."}
        with self.lock:
            try:
                job.update(**fields)
            finally:
                self.active.pop(job.id, None)
        log.info("job=%s status=%s code=%s duration_s=%.2f",
                 job.id, fields["status"], fields.get("error_code"), time.monotonic() - started)

    def cancel(self, identifier):
        with self.lock:
            if job := self.active.get(identifier):
                job.cancelled.set()

    def stop(self):
        with self.lock:
            self.closing = True
            for job in self.active.values():
                job.cancelled.set()
        self.pool.shutdown(wait=True)


class Task:
    def __init__(self, identifier):
        self.id = identifier
        self.cancelled = Event()

    def check(self):
        if self.cancelled.is_set():
            raise Problem("CANCELLED", "Processamento cancelado.")

    def update(self, **fields):
        fields["updated_at"] = now()
        values = ", ".join(f"{key}=?" for key in fields)
        with connect(write=True) as db:
            db.execute(f"UPDATE jobs SET {values} WHERE id=?", (*fields.values(), self.id))

    def phase(self, phase, message, progress=None):
        self.check()
        self.update(phase=phase, message=message, progress=progress)

    def command(self, args, *, cwd=None, timeout=None, on_line=None, code="FFMPEG_FAILED",
                message="O FFmpeg não conseguiu processar o vídeo. Consulte o diagnóstico."):
        self.check()
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        with tempfile.TemporaryDirectory(dir=DATA, prefix="process-") as scratch:
            path = os.path.join(scratch, "progress.txt")
            with open(path, "wb") as output, open(path, encoding="utf-8", errors="replace") as reader:
                try:
                    proc = subprocess.Popen(
                        args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, **options,
                    )
                except OSError as error:
                    raise Problem(code, message) from error
                start = time.monotonic()
                try:
                    while proc.poll() is None:
                        self.check()
                        if timeout and time.monotonic() - start > timeout:
                            raise Problem(code, message)
                        if on_line:
                            self._progress(reader, on_line)
                        self.cancelled.wait(.2)
                    if on_line:
                        self._progress(reader, on_line)
                finally:
                    if proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(proc.pid)], **options,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        else:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait()
                self.check()
                if proc.returncode:
                    raise Problem(code, message)

    @staticmethod
    def _progress(reader, callback):
        for _ in range(500):
            position = reader.tell()
            line = reader.readline()
            if not line.endswith("\n"):
                reader.seek(position)
                break
            callback(line.strip())
