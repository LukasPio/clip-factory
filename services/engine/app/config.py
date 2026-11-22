import os
import re
import shutil
import sys
from pathlib import Path

DATA = Path(os.environ.get("CLIP_FACTORY_DATA", Path.home() / ".clip-factory")).resolve()
PROJECTS = DATA / "projects"
MODELS = DATA / "models"
ORIGINS = {
    "http://127.0.0.1:1420", "http://localhost:1420",
    "http://tauri.localhost", "https://tauri.localhost", "tauri://localhost",
}
BYTES_PER_GB = 1_000_000_000
DEFAULT_DOWNLOAD_LIMIT_GB = 20
MAX_DOWNLOAD_LIMIT_GB = 2**53 - 1
DEFAULTS = {
    "whisper_model": "base", "language": "auto", "use_gpu": False,
    "use_llm": False, "default_export_dir": "", "default_caption_style": "white",
    "download_limit_gb": DEFAULT_DOWNLOAD_LIMIT_GB,
}
PRODUCTION_SETTINGS = {**DEFAULTS, "whisper_model": "medium", "use_gpu": True, "use_llm": True}
PRODUCTION_ANALYSIS = {
    "clip_count": 5, "min_seconds": 15, "max_seconds": 60, "language": "auto",
    "use_llm": True, "download_model": True,
}


def production_mode():
    return os.environ.get("CLIP_FACTORY_MODE") != "test"


class Problem(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def binary(name):
    folder = os.environ.get("CLIP_FACTORY_BIN")
    executable = f"{name}.exe" if os.name == "nt" else name
    path = str(Path(folder) / executable) if folder else shutil.which(executable)
    if not path or not Path(path).is_file():
        raise Problem("DEPENDENCY_MISSING", f"{name} não encontrado. Execute scripts/doctor.ps1.")
    return path


def worker(name, *args):
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.main"]
    return [*command, "--worker", name, *map(str, args)]


def safe_filename(title):
    clean = re.sub(r'[^\w -]', '_', title, flags=re.UNICODE).strip(' ._')[:70]
    return f"clip-{clean or 'sem-titulo'}"
