import ipaddress
import os
import re
import select
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.dash import DashSegmentsFD
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.http import HttpFD
from yt_dlp.dependencies import Cryptodome
from yt_dlp.networking import Request
from yt_dlp.utils import DownloadError

from .config import Problem, binary

MAX_BYTES = 2_000_000_000


def authority(value):
    try:
        parsed = urlsplit(value)
        name = parsed.hostname
        if (
            parsed.scheme != "https" or not name or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or "." not in name or not re.fullmatch(r"[a-zA-Z0-9.-]+", name)
            or name.lower().rstrip(".").endswith((".local", ".localhost", ".internal"))
            or any(ord(char) < 33 or char == "\\" for char in value)
        ):
            raise ValueError
        return name
    except ValueError as error:
        raise Problem("INVALID_SOURCE", "Use um link HTTPS público de vídeo gravado.") from error


def public_addresses(name):
    try:
        endpoints = socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise Problem("SOURCE_UNAVAILABLE", "O domínio do vídeo não pôde ser encontrado.") from error
    for endpoint in endpoints:
        ip = ipaddress.ip_address(endpoint[4][0])
        if not ip.is_global or ip.is_multicast or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)):
            raise Problem("INVALID_SOURCE", "Links para redes privadas são bloqueados.")
    return endpoints


class GuardedProxy(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.downloaded = 0
        self.counter = Lock()
        super().__init__(("127.0.0.1", 0), Tunnel)

    def count(self, size):
        with self.counter:
            self.downloaded += size
            return self.downloaded <= MAX_BYTES


class Tunnel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_CONNECT(self):
        if not re.fullmatch(r"[A-Za-z0-9.-]+:443", self.path):
            self.send_error(403)
            return
        try:
            endpoints = public_addresses(authority(f"https://{self.path}"))
        except Problem:
            self.send_error(403)
            return
        for family, kind, proto, _, address in endpoints:
            upstream = socket.socket(family, kind, proto)
            try:
                upstream.settimeout(8)
                upstream.connect(address)
            except OSError:
                upstream.close()
                continue
            break
        else:
            self.send_error(502)
            return
        with upstream:
            self.send_response(200)
            self.end_headers()
            self.connection.settimeout(15)
            try:
                while True:
                    ready, _, _ = select.select([upstream, self.connection], [], [], 30)
                    if not ready:
                        return
                    for channel in ready:
                        block = channel.recv(65536)
                        if not block:
                            return
                        if channel is upstream:
                            if not self.server.count(len(block)):
                                return
                            self.connection.sendall(block)
                        else:
                            upstream.sendall(block)
            except OSError:
                return


class Quiet:
    def debug(self, _message):
        pass

    warning = error = debug


class GuardedYoutubeDL(YoutubeDL):
    """Keep remote media inside the proxy; FFmpeg only processes local files."""

    def process_ie_result(self, ie_result, download=True, extra_info=None):
        if ie_result.get("_type") in {"playlist", "multi_video"}:
            raise Problem("INVALID_SOURCE", "Informe o link de um único vídeo gravado.")
        return super().process_ie_result(ie_result, download, extra_info)

    def dl(self, name, info, subtitle=False, test=False):
        downloader = get_suitable_downloader(info, self.params)
        if downloader not in {HttpFD, HlsFD, DashSegmentsFD}:
            raise Problem("UNSUPPORTED_SOURCE", "Este protocolo de vídeo não é suportado.")
        if downloader is HlsFD:
            # HlsFD otherwise silently falls back to an external FFmpeg process,
            # which would bypass the DNS and transfer limit enforced by our proxy.
            manifest = info.get("hls_media_playlist_data")
            if manifest is None:
                request = Request(info["url"], headers=info.get("http_headers"))
                with self.urlopen(request) as response:
                    manifest = response.read().decode("utf-8", "replace")
                    info["url"] = response.url
            if "#EXT-X-ENDLIST" not in manifest:
                raise Problem("INVALID_SOURCE", "Apenas vídeos gravados e disponíveis.")
            if not HlsFD.can_download(manifest, info) or (
                "#EXT-X-KEY:METHOD=AES-128" in manifest and not Cryptodome.AES
            ):
                raise Problem("UNSUPPORTED_SOURCE", "Vídeo protegido por DRM ou HLS incompatível.")
            info["hls_media_playlist_data"] = manifest
        return super().dl(name, info, subtitle=subtitle, test=test)


def source_error(error):
    message = str(error).lower()
    if any(word in message for word in ("sign in", "login", "log in", "cookies", "authentication", "private video")):
        return Problem("SOURCE_AUTH_REQUIRED", "A plataforma exige login. Configure CLIP_FACTORY_COOKIES com um arquivo de cookies Netscape exportado da sua sessão e tente novamente.")
    if "drm" in message:
        return Problem("UNSUPPORTED_SOURCE", "Este vídeo está protegido por DRM.")
    if "429" in message or "rate-limit" in message or "rate limit" in message:
        return Problem("SOURCE_RATE_LIMITED", "A plataforma limitou os acessos. Aguarde e tente novamente.")
    if any(word in message for word in ("403", "geo", "not available in your country")):
        return Problem("SOURCE_UNAVAILABLE", "A plataforma recusou o acesso ao vídeo nesta conexão ou região.")
    return Problem("SOURCE_UNAVAILABLE", "Não foi possível baixar este vídeo. Confira se o link está disponível e se o yt-dlp está atualizado.")


def download(url, folder, report):
    public_addresses(authority(url))
    ffmpeg = binary("ffmpeg")
    bundled_node = os.environ.get("CLIP_FACTORY_NODE")
    with GuardedProxy() as proxy:
        thread = Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            def progress(data):
                if proxy.downloaded > MAX_BYTES:
                    raise Problem("SOURCE_TOO_LARGE", "O vídeo excedeu o limite de 2 GB.")
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                report(data.get("downloaded_bytes", 0) / total if total else None)

            def filter_media(info, *, incomplete):
                if info.get("live_status") in {"is_live", "is_upcoming", "post_live"} or info.get("is_live"):
                    raise Problem("INVALID_SOURCE", "Apenas vídeos gravados e disponíveis.")
                if info.get("has_drm"):
                    raise Problem("UNSUPPORTED_SOURCE", "Este vídeo está protegido por DRM.")
                return None

            options = {
                "proxy": f"http://127.0.0.1:{proxy.server_port}",
                "quiet": True, "logger": Quiet(), "noplaylist": True, "match_filter": filter_media,
                "format": "bv*+ba/b",
                "merge_output_format": "mkv", "ffmpeg_location": ffmpeg,
                "hls_prefer_native": True, "external_downloader": {"default": "native"},
                "fragment_retries": 3, "skip_unavailable_fragments": False,
                "concurrent_fragment_downloads": 1,
                "js_runtimes": {"node": {"path": bundled_node}} if bundled_node else {"node": {}, "deno": {}},
                "outtmpl": str(folder / "source.%(ext)s"),
                "fixup": "detect_or_warn", "max_filesize": MAX_BYTES, "socket_timeout": 20,
                "retries": 3, "progress_hooks": [progress], "cachedir": False,
                "noprogress": True, "nopart": False, "enable_file_urls": False,
            }
            cookies = os.environ.get("CLIP_FACTORY_COOKIES")
            if cookies:
                if not Path(cookies).is_file():
                    raise Problem("SOURCE_AUTH_REQUIRED", "O arquivo CLIP_FACTORY_COOKIES não foi encontrado.")
                # Copy into the job folder: yt-dlp writes updates to its cookie jar.
                jar = folder / "cookies.txt"
                shutil.copyfile(cookies, jar)
                options["cookiefile"] = str(jar)
            with GuardedYoutubeDL(options) as client:
                info = client.extract_info(url, download=False, process=False)
                if not info:
                    raise Problem("INVALID_SOURCE", "Informe o link de um único vídeo gravado.")
                info = client.process_ie_result(info, download=True)
                if not info:
                    raise Problem("SOURCE_UNAVAILABLE", "A plataforma não forneceu um vídeo compatível.")
                output = folder / f"source.{info.get('ext')}"
                if proxy.downloaded > MAX_BYTES or (output.is_file() and output.stat().st_size > MAX_BYTES):
                    raise Problem("SOURCE_TOO_LARGE", "O vídeo excedeu o limite de 2 GB.")
                if output.suffix not in {".mp4", ".webm", ".mkv", ".mov"} or not output.is_file():
                    raise Problem("SOURCE_UNAVAILABLE", "A plataforma bloqueou o acesso ou o vídeo excedeu o limite de download.")
                return {"file": output.name, "title": (info.get("title") or "")[:180]}
        except DownloadError as error:
            if proxy.downloaded > MAX_BYTES:
                raise Problem("SOURCE_TOO_LARGE", "O vídeo excedeu o limite de 2 GB.") from error
            raise source_error(error) from error
        finally:
            proxy.shutdown()
            thread.join()
