import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener, urlopen

from .config import DATA, Problem
from .jobs import terminate_process

OLLAMA = "http://127.0.0.1:11434"
OLLAMA_VERSION = "0.40.16"
# Official release digest for ollama-windows-amd64.zip.
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-windows-amd64.zip"
OLLAMA_SHA256 = "50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e"
OLLAMA_DOWNLOAD_LIMIT = 2_000_000_000
OLLAMA_EXTRACT_LIMIT = 8_000_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


LOCAL = build_opener(ProxyHandler({}), NoRedirect())


def ollama_ready(endpoint):
    try:
        with LOCAL.open(f"{endpoint}/api/version", timeout=2) as response:
            payload = json.loads(response.read(4096))
        version = payload.get("version") if isinstance(payload, dict) else None
        return isinstance(version, str) and bool(version)
    except (OSError, ValueError):
        return False


def download_ollama(task, target):
    task.phase("preparing_review", "Baixando Ollama pela primeira vez")
    with tempfile.TemporaryDirectory(dir=DATA, prefix="runtime-download-") as temporary:
        staging = Path(temporary)
        archive = staging / "ollama.zip"
        digest = hashlib.sha256()
        downloaded = 0
        previous = -1
        with urlopen(OLLAMA_URL, timeout=25) as response, archive.open("wb") as output:
            if not response.geturl().startswith("https://"):
                raise ValueError("insecure redirect")
            total = int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(1024 * 1024):
                task.check()
                downloaded += len(chunk)
                if downloaded > OLLAMA_DOWNLOAD_LIMIT:
                    raise ValueError("archive size")
                digest.update(chunk)
                output.write(chunk)
                if total:
                    percent = min(99, downloaded * 100 // total)
                    if percent != previous:
                        task.update(progress=percent / 100)
                        previous = percent
        if digest.hexdigest() != OLLAMA_SHA256:
            raise Problem("OLLAMA_INTEGRITY", "O arquivo baixado do Ollama não passou na verificação. Clique em Gerar cortes para baixar novamente.")

        task.phase("preparing_review", "Preparando Ollama")
        unpacked = staging / "unpacked"
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            if sum(member.file_size for member in members) > OLLAMA_EXTRACT_LIMIT:
                raise ValueError("expanded size")
            for member in members:
                task.check()
                name = PurePosixPath(member.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in member.filename or ':' in member.filename:
                    raise ValueError("unexpected archive path")
                destination = unpacked.joinpath(*name.parts)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, destination.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        task.check()
                        output.write(chunk)
        if not (unpacked / "ollama.exe").is_file():
            raise ValueError("missing ollama.exe")
        task.check()
        unpacked.rename(target)


def ollama_executable(task):
    if local := os.environ.get("LOCALAPPDATA"):
        standard = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if standard.is_file():
            return standard
    target = DATA / "dependencies" / f"ollama-{OLLAMA_VERSION}"
    executable = target / "ollama.exe"
    if executable.is_file():
        return executable
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(DATA).free < OLLAMA_DOWNLOAD_LIMIT + OLLAMA_EXTRACT_LIMIT:
            raise Problem("DISK_FULL", "Libere pelo menos 10 GB para preparar o Ollama e tente gerar os cortes novamente.")
        download_ollama(task, target)
    except (OSError, ValueError, HTTPException, zipfile.BadZipFile) as error:
        raise Problem("OLLAMA_SETUP_FAILED", "Não foi possível preparar o Ollama. Confira a internet e o espaço em disco e tente novamente.") from error
    return executable


@contextmanager
def ollama_server(task):
    task.phase("preparing_review", "Verificando revisão de cortes")
    if ollama_ready(OLLAMA):
        yield OLLAMA
        return
    if os.name != "nt":
        raise Problem("OLLAMA_UNAVAILABLE", "Inicie o Ollama local e tente gerar os cortes novamente.")

    executable = ollama_executable(task)
    task.phase("preparing_review", "Iniciando revisão de cortes")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        host = f"127.0.0.1:{listener.getsockname()[1]}"
    endpoint = f"http://{host}"
    env = {**os.environ, "OLLAMA_HOST": host, "OLLAMA_NO_CLOUD": "1"}
    if bundled_node := env.get("CLIP_FACTORY_NODE"):
        env["PATH"] = str(Path(bundled_node).parent) + os.pathsep + env.get("PATH", "")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW}
    try:
        process = subprocess.Popen([executable, "serve"], cwd=executable.parent, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   **options)
    except OSError as error:
        raise Problem("OLLAMA_UNAVAILABLE", "Não foi possível iniciar a revisão local. Tente gerar os cortes novamente.") from error
    try:
        until = time.monotonic() + 30
        while time.monotonic() < until and process.poll() is None:
            task.check()
            if ollama_ready(endpoint) and process.poll() is None:
                yield endpoint
                return
            time.sleep(.25)
        raise Problem("OLLAMA_UNAVAILABLE", "A revisão local não iniciou. Tente gerar os cortes novamente.")
    finally:
        terminate_process(process, options)
