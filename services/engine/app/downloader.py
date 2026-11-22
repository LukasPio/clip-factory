import ipaddress
import math
import os
import re
import select
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.dash import DashSegmentsFD
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.http import HttpFD
from yt_dlp.dependencies import Cryptodome
from yt_dlp.networking import Request
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import DownloadError

from .config import BYTES_PER_GB, DEFAULT_DOWNLOAD_LIMIT_GB, Problem, binary
from .media import EXTENSIONS, free_space

DISK_RESERVE = BYTES_PER_GB
WORKSPACE_ALLOWANCE = 100_000_000
# Native yt-dlp buffers one whole fragment for decryption/assembly.
FRAGMENT_LIMIT = 128 * 1024**2
MANIFEST_LIMIT = 16 * 1024**2


def check_download_space(folder, additional=0):
    required = DISK_RESERVE + additional
    free = free_space(folder)
    if free is None:
        raise Problem("DISK_UNAVAILABLE", "Não foi possível consultar o espaço livre na unidade de download.")
    if free < required:
        raise Problem(
            "DISK_FULL",
            f"Espaço insuficiente na unidade de download. Livre: {free / BYTES_PER_GB:.2f} GB. "
            f"Necessário nesta etapa: {required / BYTES_PER_GB:.2f} GB, incluindo a reserva de segurança.",
        )


def estimated_workspace(info, limit):
    tracks = info.get("requested_formats") or [info]
    sizes = []
    for track in tracks:
        size = track.get("filesize") or track.get("filesize_approx")
        bitrate, duration = track.get("tbr"), info.get("duration")
        if not size and bitrate and duration:
            size = bitrate * duration * 125  # kbps × seconds ÷ 8
        sizes.append(size if size and math.isfinite(size) and size > 0 else WORKSPACE_ALLOWANCE)
    payload = min(math.ceil(sum(sizes)), limit)
    # Fragment assembly and FFmpeg remux/merge can keep input and output on disk.
    staged = len(tracks) > 1 or any(
        track.get("protocol") in {"m3u8_native", "http_dash_segments"} or track.get("stretched_ratio") not in (None, 1)
        for track in tracks
    )
    return payload * (2 if staged else 1) + WORKSPACE_ALLOWANCE


def too_large(limit_gb):
    return Problem("SOURCE_TOO_LARGE", f"O vídeo excedeu o limite de download de {limit_gb} GB.")


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

    def __init__(self, limit):
        # Encrypted tunnel traffic also includes extraction, headers and TLS framing.
        self.limit = limit + max(WORKSPACE_ALLOWANCE, limit // 20)
        self.downloaded = 0
        self.counter = Lock()
        super().__init__(("127.0.0.1", 0), Tunnel)

    def count(self, size):
        with self.counter:
            self.downloaded += size
            return self.downloaded <= self.limit


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
                    manifest = response.read(MANIFEST_LIMIT + 1)
                    if len(manifest) > MANIFEST_LIMIT:
                        raise Problem("UNSUPPORTED_SOURCE", "A lista de segmentos HLS é grande demais.")
                    manifest = manifest.decode("utf-8", "replace")
                    info["url"] = response.url
            if "#EXT-X-ENDLIST" not in manifest:
                raise Problem("INVALID_SOURCE", "Apenas vídeos gravados e disponíveis.")
            if not HlsFD.can_download(manifest, info) or (
                "#EXT-X-KEY:METHOD=AES-128" in manifest and not Cryptodome.AES
            ):
                raise Problem("UNSUPPORTED_SOURCE", "Vídeo protegido por DRM ou HLS incompatível.")
            info["hls_media_playlist_data"] = manifest
        return super().dl(name, info, subtitle=subtitle, test=test)


class BudgetedYoutubeDL(GuardedYoutubeDL):
    def __init__(self, options, folder, limit_gb):
        self.folder = folder
        self.limit_gb = limit_gb
        self.limit = limit_gb * BYTES_PER_GB
        self.payload = 0
        self.reading_media = False
        self.fragmented = False
        self.next_disk_check = 0
        super().__init__(options)

    def process_info(self, info):
        check_download_space(self.folder, estimated_workspace(info, self.limit))
        return super().process_info(info)

    def run_pp(self, pp, info):
        if isinstance(pp, FFmpegPostProcessor):
            inputs = info.get("__files_to_merge") if pp.PP_NAME == "Merger" else None
            size = sum(Path(path).stat().st_size for path in inputs or [info["filepath"]])
            # A second copy may coexist until FFmpeg finishes and yt-dlp renames it.
            check_download_space(self.folder, size + max(WORKSPACE_ALLOWANCE, size // 20))
        return super().run_pp(pp, info)

    def dl(self, name, info, subtitle=False, test=False):
        self.reading_media = True
        self.fragmented = get_suitable_downloader(info, self.params) in {HlsFD, DashSegmentsFD}
        try:
            return super().dl(name, info, subtitle=subtitle, test=test)
        finally:
            self.reading_media = False
            self.fragmented = False

    def urlopen(self, request):
        response = super().urlopen(request)
        if self.reading_media:
            read = response.read
            response_bytes = 0

            def counted_read(amount=None):
                nonlocal response_bytes
                available = self.limit - self.payload
                if self.fragmented:
                    available = min(available, FRAGMENT_LIMIT - response_bytes)
                size = available + 1 if amount is None or amount < 0 else min(amount, available + 1)
                try:
                    block = read(size)
                    response_bytes += len(block)
                    self.payload += len(block)
                    if self.payload > self.limit:
                        raise too_large(self.limit_gb)
                    if self.fragmented and response_bytes > FRAGMENT_LIMIT:
                        raise Problem("UNSUPPORTED_SOURCE", "Um segmento do vídeo é grande demais para importação segura.")
                    now = monotonic()
                    if now >= self.next_disk_check:
                        check_download_space(self.folder, len(block))
                        self.next_disk_check = now + .2
                    return block
                except BaseException:
                    response.close()
                    raise

            response.read = counted_read
        return response


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


def download(url, folder, report, limit_gb=DEFAULT_DOWNLOAD_LIMIT_GB):
    check_download_space(folder, WORKSPACE_ALLOWANCE)
    public_addresses(authority(url))
    ffmpeg = binary("ffmpeg")
    bundled_node = os.environ.get("CLIP_FACTORY_NODE")
    limit = limit_gb * BYTES_PER_GB
    with GuardedProxy(limit) as proxy:
        thread = Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            next_report = 0

            def progress(data):
                nonlocal next_report
                now = monotonic()
                if now < next_report and data.get("status") != "finished":
                    return
                next_report = now + .5
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
                "fixup": "detect_or_warn", "socket_timeout": 20,
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
            with BudgetedYoutubeDL(options, folder, limit_gb) as client:
                info = client.extract_info(url, download=False, process=False)
                if not info:
                    raise Problem("INVALID_SOURCE", "Informe o link de um único vídeo gravado.")
                info = client.process_ie_result(info, download=True)
                if not info:
                    raise Problem("SOURCE_UNAVAILABLE", "A plataforma não forneceu um vídeo compatível.")
                output = folder / f"source.{info.get('ext')}"
                if proxy.downloaded > proxy.limit or (output.is_file() and output.stat().st_size > limit):
                    raise too_large(limit_gb)
                check_download_space(folder)
                if output.suffix not in EXTENSIONS or not output.is_file():
                    raise Problem("SOURCE_UNAVAILABLE", "A plataforma não forneceu um vídeo compatível.")
                return {"file": output.name, "title": (info.get("title") or "")[:180]}
        except DownloadError as error:
            if proxy.downloaded > proxy.limit:
                raise too_large(limit_gb) from error
            check_download_space(folder)
            raise source_error(error) from error
        finally:
            proxy.shutdown()
            thread.join()
