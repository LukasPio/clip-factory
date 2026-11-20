"""Offline contracts: real yt-dlp selection, native transfer, merge and FFprobe.

Only extraction and remote responses are fixtures; these tests do not establish
current availability of a public platform (see test_downloader_live.py).
"""
from io import BytesIO
import subprocess

import pytest
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.networking import Response
from yt_dlp.utils import DownloadError

from app import downloader, media
from app.config import Problem, binary


@pytest.fixture(scope="module")
def remote_media(tmp_path_factory):
    root = tmp_path_factory.mktemp("remote-media")
    common = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run([*common, "-f", "lavfi", "-i", "color=size=160x90:rate=10:duration=1",
                    "-an", "-c:v", "libx264", str(root / "video.mp4")], check=True, capture_output=True)
    subprocess.run([*common, "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "aac", str(root / "audio.m4a")], check=True, capture_output=True)
    subprocess.run([*common, "-i", str(root / "video.mp4"), "-i", str(root / "audio.m4a"),
                    "-c", "copy", str(root / "direct.mp4")], check=True, capture_output=True)
    subprocess.run([*common, "-i", str(root / "direct.mp4"), "-c", "copy", "-f", "hls",
                    "-hls_time", "1", "-hls_list_size", "0", str(root / "manifest.m3u8")],
                   check=True, capture_output=True)
    return root


@pytest.mark.parametrize("platform,mode,url", [
    ("youtube", "separate", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("youtube-dash", "dash", "https://youtu.be/jNQXAC9IVRw"),
    ("twitch-vod", "hls", "https://www.twitch.tv/videos/635475444"),
    ("twitch-clip", "direct", "https://clips.twitch.tv/FaintLightGullWholeWheat"),
    ("twitter", "hls", "https://twitter.com/starwars/status/665052190608723968"),
    ("x", "direct", "https://x.com/starwars/status/665052190608723968"),
    ("instagram", "direct", "https://www.instagram.com/p/BQ0eAlwhDrw/"),
])
def test_platform_media_pipeline(platform, mode, url, remote_media, tmp_path, monkeypatch):
    # Assert this URL is recognized by a real platform extractor, not GenericIE.
    from yt_dlp.extractor import gen_extractor_classes
    assert any(ie.suitable(url) for ie in gen_extractor_classes() if ie.IE_NAME.lower() != "generic")
    base = "https://cdn.example.test/"
    formats = {
        "direct": [{"format_id": "direct", "url": base + "direct.mp4", "ext": "mp4"}],
        "separate": [
            {"format_id": "video", "url": base + "video.mp4", "ext": "mp4", "vcodec": "h264", "acodec": "none"},
            {"format_id": "audio", "url": base + "audio.m4a", "ext": "m4a", "vcodec": "none", "acodec": "aac"},
        ],
        "hls": [{"format_id": "hls", "url": base + "manifest.m3u8", "ext": "mp4", "protocol": "m3u8_native"}],
        "dash": [{"format_id": "dash", "url": base + "manifest.mpd", "ext": "mp4",
                  "protocol": "http_dash_segments", "fragments": [{"url": base + "direct.mp4"}]}],
    }

    class FixtureIE(InfoExtractor):
        _VALID_URL = r"https://.+"

        def _real_extract(self, _url):
            return {"id": "fixture", "title": platform, "formats": formats[mode]}

    requests = []

    class FixtureClient(downloader.GuardedYoutubeDL):
        def __init__(self, options):
            super().__init__(options, auto_init=False)
            self.add_info_extractor(FixtureIE())

        def urlopen(self, request):
            request_url = request if isinstance(request, str) else request.url
            requests.append(request_url)
            assert request_url.startswith(base), "Unexpected remote request"
            path = remote_media / request_url.removeprefix(base)
            data = path.read_bytes()
            return Response(BytesIO(data), url=request_url, headers={"Content-Length": str(len(data))})

    monkeypatch.setattr(downloader, "GuardedYoutubeDL", FixtureClient)
    monkeypatch.setattr(downloader, "public_addresses", lambda name: [])
    updates = []
    result = downloader.download(url, tmp_path, updates.append)
    output = tmp_path / result["file"]
    metadata = media.probe(output)
    assert metadata["duration_ms"] >= 900
    assert metadata["width"] == 160 and metadata["height"] == 90
    streams = media.capture([binary("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type",
                             "-of", "csv=p=0", str(output)])
    assert "audio" in streams and "video" in streams
    assert result["title"] == platform and updates and requests
    if mode == "separate":
        assert output.suffix == ".mkv"
        assert base + "audio.m4a" in requests and base + "video.mp4" in requests
    if mode == "hls":
        assert any(request.endswith(".ts") for request in requests)
    if mode == "dash":
        assert base + "direct.mp4" in requests


@pytest.mark.parametrize("message,code", [
    ("Sign in to confirm you're not a bot", "SOURCE_AUTH_REQUIRED"),
    ("Login required", "SOURCE_AUTH_REQUIRED"),
    ("HTTP Error 429: Too Many Requests", "SOURCE_RATE_LIMITED"),
    ("HTTP Error 403: Forbidden", "SOURCE_UNAVAILABLE"),
    ("This video is DRM protected", "UNSUPPORTED_SOURCE"),
    ("Video unavailable", "SOURCE_UNAVAILABLE"),
])
def test_platform_errors_have_actionable_codes(message, code):
    assert downloader.source_error(DownloadError(message)).code == code


@pytest.mark.parametrize("info", [
    {"is_live": True}, {"live_status": "is_upcoming"}, {"live_status": "post_live"},
    {"has_drm": True},
])
def test_rejects_unavailable_media_before_transfer(info, tmp_path, monkeypatch):
    class Client:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def extract_info(self, *_args, **_kwargs):
            return {"id": "fixture", **info}

        def process_ie_result(self, value, **_kwargs):
            self.options["match_filter"](value, incomplete=False)
            pytest.fail("Invalid media must be rejected before download")

    monkeypatch.setattr(downloader, "GuardedYoutubeDL", Client)
    monkeypatch.setattr(downloader, "public_addresses", lambda name: [])
    with pytest.raises(Problem):
        downloader.download("https://example.com/video", tmp_path, lambda value: None)


def test_rejects_external_network_downloader(tmp_path):
    with downloader.GuardedYoutubeDL({"quiet": True}) as client:
        with pytest.raises(Problem, match="protocolo"):
            client.dl(str(tmp_path / "video.mp4"), {"url": "rtmp://example.com/video", "protocol": "rtmp"})


@pytest.mark.parametrize("kind", ["playlist", "multi_video"])
def test_rejects_collections_before_processing_entries(kind):
    def entries():
        pytest.fail("A collection must be rejected before reading its entries")
        yield

    with downloader.GuardedYoutubeDL({"quiet": True}, auto_init=False) as client:
        with pytest.raises(Problem, match="único vídeo"):
            client.process_ie_result({"_type": kind, "entries": entries()})


def test_cumulative_transfer_limit(monkeypatch):
    monkeypatch.setattr(downloader, "MAX_BYTES", 100)
    with downloader.GuardedProxy() as proxy:
        assert proxy.count(60)
        assert not proxy.count(50)
