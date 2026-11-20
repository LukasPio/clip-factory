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


class Task:
    def check(self):
        pass


def transcript(*passages):
    return [{"start_ms": start, "end_ms": end, "text": text, "words": []} for start, end, text in passages]


STORY = transcript(
    (1000, 4200, "Você sabe por que a padaria quase fechou?"),
    (4280, 8300, "O aluguel subiu e fiquei com medo de perder tudo."),
    (8400, 12900, "Em vez de cortar a equipe, começamos a vender pão por encomenda,"),
    (13000, 17400, "porque a receita dos pedidos pagava o aluguel."),
    (17500, 22300, "No fim, as encomendas salvaram a padaria e ninguém perdeu o emprego."),
)


def test_selects_setup_and_payoff_instead_of_ending_before_the_resolution():
    filler = transcript((27500, 33500, "Mudando de assunto, no escritório organizei os armários e arregacei as mangas."),
                        (33600, 42000, "Conferi papéis, janelas, pastas, estantes, cadeiras, impressoras e material de limpeza."),
                        (42100, 50000, "O calendário ficou sobre a mesa com os formulários e documentos administrativos."))
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(STORY + filler, 52000, 15000, 35000), 5, False)
    [clip] = chosen
    assert clip["transcript"].startswith(STORY[0]["text"])
    assert clip["transcript"].endswith(STORY[-1]["text"])
    assert clip["title"] == "Você sabe por que a padaria quase fechou?"
    assert "emoção" in clip["reason"]
    assert (clip["start_ms"], clip["end_ms"]) == (600, 22850)


def test_leaves_out_the_story_when_the_conclusion_cannot_fit():
    segments = transcript(
        (1000, 4800, "Imagine perder todas as fotos da sua filha em um segundo."),
        (4900, 12000, "Fiquei tremendo quando vi que o cartão da câmera não abria."),
        (12100, 16900, "Foi ali que eu percebi que"),
        (17100, 25100, "existia uma cópia automática que salvou as fotos da família."),
    )
    assert editorial.candidates(segments, 30000, 15000, 20000) == []
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 30000, 15000, 27000), 5, False)
    [clip] = chosen
    assert clip["end_ms"] >= 25100
    assert clip["transcript"].endswith("salvou as fotos da família.")


def test_complete_sentences_are_not_enough_when_the_outcome_is_later():
    segments = transcript(
        (1000, 4400, "O que aconteceu quando a escola ficou sem energia?"),
        (4500, 10100, "A escola ficou escura e eu fiquei com medo de perder a comida da cozinha."),
        (10200, 17900, "Em vez de esperar pela energia, decidi ligar a cozinha à bateria do ônibus."),
        (18000, 21700, "O ônibus saiu para buscar as crianças e tiraram a bateria."),
        (21800, 28000, "No fim, um vizinho emprestou um gerador e salvamos toda a comida da escola."),
    )
    assert editorial.candidates(segments, 32000, 15000, 20000) == []
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 32000, 15000, 30000), 5, False)
    [clip] = chosen
    assert clip["transcript"].startswith(segments[0]["text"])
    assert clip["transcript"].endswith(segments[-1]["text"])


def test_rejects_an_answer_that_loses_its_question_and_referent():
    segments = transcript(
        (1000, 13300, "Por que a prefeitura cancelou as bolsas de estudo para quem morava longe da faculdade?"),
        (13400, 18200, "A mudança assustou os estudantes que dependiam daquele dinheiro para pegar o ônibus."),
        (18300, 25000, "Em vez de aceitar a mudança, eles levaram ao conselho os recibos da passagem."),
        (25100, 32800, "No fim, o conselho devolveu o dinheiro e os estudantes voltaram para a faculdade."),
    )
    assert editorial.candidates(segments, 35000, 15000, 21000) == []
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 35000, 15000, 34000), 5, False)
    assert [clip["title"] for clip in chosen] == [segments[0]["text"]]


def test_avoids_cutting_a_list_before_the_promised_steps():
    segments = transcript(
        (1000, 5000, "Como eu melhorei o café da padaria com dois ajustes?"),
        (5100, 18300, "O primeiro passo foi ajustar a moagem porque o café ficava amargo e a água passava devagar."),
        (18400, 23800, "O segundo passo foi pesar a água para conseguir repetir a receita durante o turno."),
        (23900, 29500, "No fim, os dois ajustes deixaram o café da padaria mais doce em todos os turnos."),
    )
    assert editorial.candidates(segments, 32000, 15000, 20000) == []
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 32000, 15000, 31000), 5, False)
    assert len(chosen) == 1 and chosen[0]["transcript"].endswith(segments[-1]["text"])


def test_accepts_an_explanation_when_it_answers_the_opening_question():
    segments = transcript(
        (1000, 4400, "Por que os tomates racham depois da chuva?"),
        (4500, 9800, "Na estação seca, a casca dos tomates cresce devagar e fica menos flexível."),
        (9900, 19800, "Os tomates racham porque a chuva repentina faz a polpa crescer mais rápido do que a casca."),
    )
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 21500, 15000, 25000), 5, False)
    assert len(chosen) == 1 and chosen[0]["transcript"].endswith(segments[-1]["text"])


def test_explaining_a_detail_does_not_resolve_the_opening_question():
    segments = transcript(
        (1000, 4200, "Por que a padaria abandonou o forno a lenha?"),
        (4300, 10500, "Naquela época, o forno ficava aceso durante todo o turno da equipe."),
        (10600, 19000, "O forno demorava para aquecer porque a madeira armazenada ao ar livre estava úmida."),
    )
    assert editorial.candidates(segments, 21500, 15000, 25000) == []


def test_uses_word_timing_to_end_before_an_unrelated_topic_in_the_same_segment():
    segments = [*STORY[:-1], dict(STORY[-1])]
    last = segments[-1]
    tail = "Agora vamos falar sobre futebol no sábado."
    parts = [(last["text"].split(), 17500, 22300), (tail.split(), 22320, 25800)]
    last["words"] = [
        {"start_ms": start + index * (end - start) // len(tokens),
         "end_ms": start + (index + 1) * (end - start) // len(tokens), "text": token}
        for tokens, start, end in parts for index, token in enumerate(tokens)
    ]
    last.update(end_ms=25800, text=f'{last["text"]} {tail}')
    chosen, _ = editorial.rank_options(Task(), editorial.candidates(segments, 30000, 15000, 35000), 5, False)
    [clip] = chosen
    assert 22300 <= clip["end_ms"] <= 22320
    assert "futebol" not in clip["transcript"]


def test_candidates_bounded_deduplicated_and_llm_fallback(monkeypatch):
    segments = STORY + [{**s, "start_ms": s["start_ms"] + 50000, "end_ms": s["end_ms"] + 50000} for s in STORY]
    options = editorial.candidates(segments, 81000, 15000, 45000)
    assert len(options) >= 2
    assert all(15000 <= item["end_ms"] - item["start_ms"] <= 45000 and item["end_ms"] <= 81000 for item in options)

    def invalid(_items):
        raise ValueError("JSON inválido")

    monkeypatch.setattr(editorial, "ollama_ranks", invalid)

    chosen, mode = editorial.rank_options(Task(), options, 5, True)
    assert mode == "heuristic_fallback"
    assert chosen == editorial.rank_options(Task(), options, 5, False)[0]
    assert len(chosen) == 1


def test_hybrid_filters_out_fragments_the_semantic_review_rejected(monkeypatch):
    options = editorial.candidates(STORY, 28000, 15000, 26000)

    def reject(items):
        return {item["candidate_id"]: editorial.Rank(candidate_id=item["candidate_id"], usable=False,
                title="Tema", reason="A explicação ficou de fora.", score=20) for item in items}

    monkeypatch.setattr(editorial, "ollama_ranks", reject)
    assert editorial.rank_options(Task(), options, 5, True) == ([], "hybrid")
    assert editorial.rank_options(Task(), options, 5, False)[0]


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
