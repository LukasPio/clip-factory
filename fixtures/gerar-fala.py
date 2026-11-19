"""Gera um vídeo de teste independente com voz sintética em português."""
import ctypes
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from espeakng_loader import get_data_path, get_library_path

SCRIPT = """
Imagine que você precise organizar uma pequena oficina no fim de semana.
Primeiro, separe as ferramentas que usa com mais frequência.
Uma chave, um martelo e uma fita métrica já resolvem vários problemas.
Deixe espaço para trabalhar sem esbarrar em objetos perigosos.
Se uma ferramenta estiver quebrada, coloque-a de lado para consertar depois.

Agora vamos escolher um projeto simples para começar.
Que tal construir uma caixa para guardar sementes no jardim?
Meça a madeira duas vezes antes de fazer o primeiro corte.
Uma pequena diferença na medida pode impedir a tampa de encaixar.
Experimente as peças sobre a mesa antes de usar cola ou parafusos.

Depois, pense no acabamento da caixa.
Passe uma lixa fina em cada borda até eliminar as farpas.
Você pode proteger a madeira com um produto adequado para o ar livre.
Leia as instruções do fabricante e espere o tempo de secagem indicado.
Enquanto isso, separe as sementes e prepare etiquetas para cada espécie.

Por fim, organize tudo de um jeito que seja fácil de encontrar.
Nas primeiras semanas, observe quais sementes germinam mais rápido.
Registre a temperatura, a quantidade de água e a hora em que o sol aparece.
As anotações ajudam a lembrar o que deu certo quando chegar a próxima estação.
Compartilhe os resultados com alguém que também goste de cultivar plantas.
"""


def generate(output):
    lib = ctypes.CDLL(get_library_path())
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    rate = lib.espeak_Initialize(2, 0, str(Path(get_data_path()).parent).encode(), 0)
    if rate <= 0 or lib.espeak_SetVoiceByName(b"pt-br") != 0:
        raise RuntimeError("Voz sintética pt-BR indisponível")
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    with tempfile.TemporaryDirectory() as scratch:
        audio = Path(scratch) / "fala.wav"
        with wave.open(str(audio), "wb") as file:
            file.setparams((1, 2, rate, 0, "NONE", "not compressed"))

            @callback_type
            def collect(data, samples, _events):
                if data and samples:
                    file.writeframesraw(ctypes.string_at(data, samples * 2))
                return 0

            lib.espeak_SetSynthCallback(collect)
            for paragraph in SCRIPT.strip().split("\n\n"):
                content = paragraph.replace("\n", " ").encode()
                if lib.espeak_Synth(content, len(content) + 1, 0, 1, 0, 1 | 0x1000, None, None) != 0:
                    raise RuntimeError("Falha ao sintetizar a fixture")
                file.writeframesraw(bytes(2 * rate))
        lib.espeak_Terminate()
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30",
            "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output),
        ], check=True)


if __name__ == "__main__":
    generate(Path(sys.argv[1]))
