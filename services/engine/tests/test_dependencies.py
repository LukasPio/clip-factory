import hashlib
import io
import zipfile

import pytest

from app import dependencies
from app.config import Problem


class Task:
    def phase(self, *_args):
        pass

    def update(self, **_kwargs):
        pass

    def check(self):
        pass


def test_download_verifies_archive_and_reuses_the_local_cache(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("ollama.exe", b"fixture executable")
        package.writestr("lib/ollama/runner.dll", b"fixture library")
    payload = archive.getvalue()

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def geturl(self):
            return "https://release.example/ollama.zip"

    downloads = []

    def download(url, *, timeout):
        downloads.append(url)
        return Response(payload)

    monkeypatch.setattr(dependencies, "DATA", tmp_path)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(dependencies.shutil, "disk_usage", lambda _path: type("Capacity", (), {"free": 20_000_000_000})())
    monkeypatch.setattr(dependencies, "urlopen", download)
    with pytest.raises(Problem) as error:
        dependencies.ollama_executable(Task())
    assert error.value.code == "OLLAMA_INTEGRITY"
    assert not list(tmp_path.glob("runtime-download-*"))

    monkeypatch.setattr(dependencies, "OLLAMA_SHA256", hashlib.sha256(payload).hexdigest())
    executable = dependencies.ollama_executable(Task())
    assert executable.read_bytes() == b"fixture executable"
    assert (executable.parent / "lib" / "ollama" / "runner.dll").is_file()
    assert dependencies.ollama_executable(Task()) == executable
    assert downloads == [dependencies.OLLAMA_URL] * 2


def test_reuses_a_running_ollama_without_provisioning(monkeypatch):
    monkeypatch.setattr(dependencies, "ollama_ready", lambda endpoint: endpoint == dependencies.OLLAMA)
    monkeypatch.setattr(dependencies, "ollama_executable", lambda _task: pytest.fail("Unexpected installation"))
    with dependencies.ollama_server(Task()) as endpoint:
        assert endpoint == dependencies.OLLAMA
