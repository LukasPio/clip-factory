import importlib.util
import json
import os
import shutil
import subprocess
from urllib.error import URLError

from .config import DATA, MODELS, Problem, binary
from .editorial import LOCAL, OLLAMA, QWEN
from .media import capture, encoder_available


def tool(name):
    try:
        path = binary(name)
        version = capture([path, "-version"]).splitlines()[0]
        return {"available": True, "version": version}
    except (Problem, OSError, IndexError, subprocess.SubprocessError):
        return {"available": False}


def memory():
    if os.name == "nt":
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (key, ctypes.c_ulonglong) for key in ("total", "free", "page", "avail_page", "virtual", "avail_virtual", "extended")
            ]

        status = Memory()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"total": status.total, "available": status.free}
    elif hasattr(os, "sysconf"):
        page = os.sysconf("SC_PAGE_SIZE")
        return {"total": os.sysconf("SC_PHYS_PAGES") * page, "available": os.sysconf("SC_AVPHYS_PAGES") * page}
    return None


def run():
    ffmpeg = tool("ffmpeg")
    ass = False
    if ffmpeg["available"]:
        try:
            filters = capture([binary("ffmpeg"), "-hide_banner", "-filters"])
            ass = any(" ass " in line for line in filters.splitlines())
        except (OSError, subprocess.SubprocessError):
            pass
    cuda = 0
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count()
    except (ImportError, RuntimeError, OSError):
        pass
    ollama = {"available": False, "model": False}
    try:
        with LOCAL.open(f"{OLLAMA}/api/tags", timeout=1.5) as response:
            models = json.loads(response.read(200_000)).get("models", [])
        ollama = {"available": True, "model": any(item.get("name") == QWEN for item in models)}
    except (URLError, OSError, ValueError, KeyError):
        pass
    return {
        "ffmpeg": ffmpeg, "ffprobe": tool("ffprobe"), "libass": ass, "libx264": encoder_available("libx264"),
        "nvenc": encoder_available("h264_nvenc"), "qsv": encoder_available("h264_qsv"), "cuda_devices": cuda,
        "whisper": importlib.util.find_spec("faster_whisper") is not None,
        "models": [name for name in ("tiny", "base", "small", "medium") if (MODELS / name / "model.bin").is_file()],
        "ollama": ollama, "memory": memory(), "disk_free": shutil.disk_usage(DATA).free,
        "recommendation": "Perfil Produção GPU disponível para teste." if cuda else "Use Teste leve (CPU/int8).",
    }
