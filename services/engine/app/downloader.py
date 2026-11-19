import ipaddress
import re
import select
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import urlsplit

from .config import Problem

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


def download(url, folder, report):
    from yt_dlp import YoutubeDL
    public_addresses(authority(url))
    with GuardedProxy() as proxy:
        thread = Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            def progress(data):
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                report(data.get("downloaded_bytes", 0) / total if total else None)

            def filter_media(info, *, incomplete):
                if info.get("live_status") in {"is_live", "is_upcoming", "post_live"} or info.get("is_live"):
                    return "Apenas vídeos gravados e disponíveis."
                if info.get("_type") in {"playlist", "multi_video"}:
                    return "Playlists não são aceitas."
                return None

            # Restrict to single HTTP(S) media files. Stream manifests and external
            # downloaders would expand the network surface and are unsupported.
            options = {
                "proxy": f"http://127.0.0.1:{proxy.server_port}",
                "quiet": True, "logger": Quiet(), "noplaylist": True, "match_filter": filter_media,
                "format": "best[protocol=https][ext=mp4]/best[protocol=https][ext=webm]",
                "outtmpl": str(folder / "source.%(ext)s"),
                "fixup": "never", "max_filesize": MAX_BYTES, "socket_timeout": 15,
                "retries": 1, "progress_hooks": [progress], "cachedir": False,
                "noprogress": True, "nopart": False, "enable_file_urls": False,
            }
            with YoutubeDL(options) as client:
                info = client.extract_info(url, download=False, process=False)
                if not info or info.get("_type") in {"playlist", "multi_video"}:
                    raise Problem("INVALID_SOURCE", "Informe o link de um único vídeo gravado.")
                info = client.process_ie_result(info, download=True)
                output = folder / f"source.{info.get('ext')}"
                if output.suffix not in {".mp4", ".webm"} or not output.is_file():
                    raise Problem("SOURCE_UNAVAILABLE", "A plataforma bloqueou o acesso ou o vídeo excedeu o limite de download.")
                return {"file": output.name, "title": (info.get("title") or "")[:180]}
        finally:
            proxy.shutdown()
            thread.join()
