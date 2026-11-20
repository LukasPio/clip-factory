"""Real platform downloads. Opt in with CLIP_FACTORY_LIVE_DOWNLOADS=1.

Failures are never converted into skips: authentication, removed videos, network
errors and platform throttling must remain visible to the person running this suite.
Each URL can be replaced with a public video owned by the tester.
"""
import os

import pytest

from app.downloader import download
from app.media import probe


PLATFORMS = {
    "youtube": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "twitch": "https://clips.twitch.tv/FaintLightGullWholeWheat",
    "twitter": "https://x.com/BrooklynNets/status/1349794411333394432",
    "instagram": "https://www.instagram.com/reel/Chunk8-jurw/",
}


@pytest.mark.live_download
@pytest.mark.skipif(os.environ.get("CLIP_FACTORY_LIVE_DOWNLOADS") != "1", reason="Enable real network downloads explicitly")
@pytest.mark.parametrize("platform", PLATFORMS)
def test_real_platform_download(platform, tmp_path):
    url = os.environ.get(f"CLIP_FACTORY_TEST_{platform.upper()}_URL", PLATFORMS[platform])
    updates = []
    result = download(url, tmp_path, updates.append)
    path = tmp_path / result["file"]
    assert path.is_file() and path.stat().st_size > 0
    metadata = probe(path)
    assert metadata["duration_ms"] > 0
    assert metadata["width"] > 0 and metadata["height"] > 0
    assert result["title"]
    assert updates, "Download must publish progress to the application"
