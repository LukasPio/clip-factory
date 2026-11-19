from app import editorial
from app.downloader import authority
from app.config import Problem
import pytest


def test_cues_relative_to_mid_video_and_gap():
    segments = [{
        "start_ms": 72000, "end_ms": 76000, "text": "Hoje começa. Depois.",
        "words": [
            {"id": "a", "start_ms": 72300, "end_ms": 72600, "text": "Hoje"},
            {"id": "b", "start_ms": 72610, "end_ms": 73000, "text": "começa."},
            {"id": "c", "start_ms": 74300, "end_ms": 74800, "text": "Depois."},
        ],
    }]
    cues = editorial.project_cues(segments, 72500, 74600)
    assert [(c["start_ms"], c["end_ms"], c["word_ids"]) for c in cues] == [
        (0, 500, ["a", "b"]), (1800, 2100, ["c"]),
    ]


def test_missing_word_alignment_is_marked():
    [cue] = editorial.project_cues([{"start_ms": 1000, "end_ms": 2000, "text": "Frase", "words": []}], 1500, 3000)
    assert cue["alignment_needs_review"]
    assert (cue["start_ms"], cue["end_ms"]) == (0, 500)


def test_candidates_bounded_deduplicated_and_llm_fallback(monkeypatch):
    segments = [
        {"start_ms": i, "end_ms": i + 6500, "words": [],
         "text": "Imagina como essa nova escolha pode mudar o ritmo e melhorar a sua próxima tentativa."}
        for i in range(0, 100000, 7000)
    ]
    options = editorial.candidates(segments, 100000, 15000, 45000)
    assert options
    assert all(15000 <= item["end_ms"] - item["start_ms"] <= 45000 and item["end_ms"] <= 100000 for item in options)

    def invalid(_items):
        raise ValueError("JSON inválido")

    monkeypatch.setattr(editorial, "ollama_ranks", invalid)

    class Task:
        def check(self):
            pass

    chosen, mode = editorial.rank_options(Task(), options, 5, True)
    assert mode == "heuristic_fallback"
    assert chosen == editorial.rank_options(Task(), options, 5, False)[0]
    for index, a in enumerate(chosen):
        for b in chosen[index + 1:]:
            overlap = max(0, min(a["end_ms"], b["end_ms"]) - max(a["start_ms"], b["start_ms"]))
            assert overlap / (a["end_ms"] - a["start_ms"] + b["end_ms"] - b["start_ms"] - overlap) <= .2


@pytest.mark.parametrize("url", [
    "http://example.com/x", "https://localhost", "https://foo.internal", "https://user@example.com/video",
    "https://example.com:444/", "https://example.com\\private", "file:///tmp/test",
])
def test_input_rejects_unsupported_urls(url):
    with pytest.raises(Problem):
        authority(url)


def test_dns_rejects_private_and_mixed_addresses(monkeypatch):
    import socket
    from app.downloader import public_addresses
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443)),
    ])
    with pytest.raises(Problem, match="redes privadas"):
        public_addresses("example.com")
