"""Offline contracts: real yt-dlp selection, native transfer, merge and FFprobe.

Only extraction and remote responses are fixtures; these tests do not establish
current availability of a public platform (see test_downloader_live.py).
"""
from io import BytesIO
import subprocess

import pytest
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp import YoutubeDL
from yt_dlp.networking import Response
from yt_dlp.utils import DownloadError

from app import downloader, media
from app.config import Problem, binary


@pytest.fixture(scope="module")
def remote_media(tmp_path_factory):
    root = tmp_path_factory.mktemp("remote-media")
    common = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run([*common, "-f", "lavfi", "-i", "color=size=160x90:rate=10:duration=3",
                    "-an", "-c:v", "libx264", "-g", "10", str(root / "video.mp4")], check=True, capture_output=True)
    subprocess.run([*common, "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:a", "aac", str(root / "audio.m4a")], check=True, capture_output=True)
    subprocess.run([*common, "-i", str(root / "video.mp4"), "-i", str(root / "audio.m4a"),
                    "-c", "copy", str(root / "direct.mp4")], check=True, capture_output=True)
    subprocess.run([*common, "-i", str(root / "direct.mp4"), "-c", "copy", "-f", "hls",
                    "-hls_time", "1", "-hls_list_size", "0", str(root / "manifest.m3u8")],
                   check=True, capture_output=True)
    direct = (root / "direct.mp4").read_bytes()
    middle = len(direct) // 2
    (root / "dash-0.mp4").write_bytes(direct[:middle])
    (root / "dash-1.mp4").write_bytes(direct[middle:])
    return root


@pytest.mark.parametrize("platform,mode,url", [
    ("youtube", "separate", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("youtube-dash", "dash", "https://youtu.be/jNQXAC9IVRw"),
    ("twitch-vod", "hls", "https://www.twitch.tv/videos/635475444"),
    ("twitch-clip", "direct", "https://clips.twitch.tv/FaintLightGullWholeWheat"),
    ("twitter", "hls", "https://twitter.com/starwars/status/665052190608723968"),
    ("x", "direct", "https://x.com/starwars/status/665052190608723968"),
    ("instagram", "direct", "https://www.instagram.com/p/BQ0eAlwhDrw/"),
    ("unknown-size", "unknown", "https://x.com/starwars/status/665052190608723968"),
    ("large", "large", "https://x.com/starwars/status/665052190608723968"),
    ("limited-dash", "limited-dash", "https://youtu.be/jNQXAC9IVRw"),
    ("limited-hls", "limited-hls", "https://www.twitch.tv/videos/635475444"),
    ("limited-separate", "limited-separate", "https://youtu.be/jNQXAC9IVRw"),
    ("low-disk-merge", "low-disk-merge", "https://youtu.be/jNQXAC9IVRw"),
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
                  "protocol": "http_dash_segments",
                  "fragments": [{"url": base + f"dash-{index}.mp4"} for index in range(2)]}],
    }
    format_mode = mode.removeprefix("limited-")
    if mode in {"unknown", "large"}:
        format_mode = "direct"
    elif mode == "low-disk-merge":
        format_mode = "separate"

    class FixtureIE(InfoExtractor):
        _VALID_URL = r"https://.+"

        def _real_extract(self, _url):
            return {"id": "fixture", "title": platform, "formats": formats[format_mode]}

    requests = []

    def response(client, request):
        request_url = request if isinstance(request, str) else request.url
        requests.append(request_url)
        assert request_url.startswith(base), "Unexpected remote request"
        path = remote_media / request_url.removeprefix(base)
        data = path.read_bytes()
        if mode == "large":
            # Simulate bytes already received without allocating several GB.
            client.payload = 2_100_000_000
        if mode.startswith("limited-") and path.name in {"dash-1.mp4", "manifest1.ts", "audio.m4a"}:
            assert client.payload > 0
            client.limit = client.payload + len(data) - 1
        headers = {} if mode in {"unknown", "large"} else {"Content-Length": str(len(data))}
        return Response(BytesIO(data), url=request_url, headers=headers)

    def add_extractors(client):
        client.add_info_extractor(FixtureIE())

    monkeypatch.setattr(YoutubeDL, "add_default_info_extractors", add_extractors)
    monkeypatch.setattr(YoutubeDL, "urlopen", response)
    monkeypatch.setattr(downloader, "public_addresses", lambda name: [])
    monkeypatch.setattr(downloader, "free_space", lambda path: (
        downloader.DISK_RESERVE + 1 if mode == "low-disk-merge" and
        any(tmp_path.glob("source.faudio.*")) and not any(tmp_path.glob("*.part")) else 50_000_000_000
    ))
    updates = []
    if mode.startswith("limited-") or mode == "low-disk-merge":
        with pytest.raises(Problem) as error:
            downloader.download(url, tmp_path, updates.append)
        assert error.value.code == ("DISK_FULL" if mode == "low-disk-merge" else "SOURCE_TOO_LARGE")
        return
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
        assert sum(request.endswith(".ts") for request in requests) == 3
    if mode == "dash":
        assert all(base + f"dash-{index}.mp4" in requests for index in range(2))


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
        def __init__(self, options, _folder, _limit_gb):
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

    monkeypatch.setattr(downloader, "BudgetedYoutubeDL", Client)
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


def test_cumulative_wire_limit():
    with downloader.GuardedProxy(20_000_000_000) as proxy:
        assert proxy.count(20_000_000_000)
        assert not proxy.count(1_000_000_001)
        assert not proxy.count(1)


def test_workspace_estimates_selected_tracks_and_caps_remote_metadata():
    info = {"duration": 100, "requested_formats": [{"filesize": 3_000_000_000}, {"tbr": 128}]}
    assert downloader.estimated_workspace(info, 20_000_000_000) == 6_103_200_000
    assert downloader.estimated_workspace({"filesize": 90_000_000_000}, 20_000_000_000) == 20_100_000_000
    assert downloader.estimated_workspace({}, 20_000_000_000) == 200_000_000


def test_checks_disk_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "free_space", lambda path: downloader.DISK_RESERVE - 1)
    monkeypatch.setattr(downloader, "public_addresses", lambda name: pytest.fail("Network used before disk check"))
    with pytest.raises(Problem) as error:
        downloader.download("https://example.com/video", tmp_path, lambda _: None)
    assert error.value.code == "DISK_FULL"
