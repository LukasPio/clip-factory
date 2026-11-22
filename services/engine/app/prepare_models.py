import sys

from .config import DEFAULTS, PRODUCTION_SETTINGS, Problem, production_mode
from .dependencies import ollama_server
from .editorial import PRODUCTION_QWEN as REVIEW_MODEL
from .editorial import prepare_production_review as prepare_review
from .pipeline import prepare_whisper_model


class ConsoleTask:
    def phase(self, _name, message):
        self.update(message=message)

    def update(self, *, message=None, progress=None):
        if message:
            print(message, flush=True)
        elif progress is not None and round(progress * 100) % 10 == 0:
            print(f"Ollama: {progress:.0%}", flush=True)

    def check(self):
        # Ctrl+C raises KeyboardInterrupt during synchronous preparation.
        pass


def main():
    task = ConsoleTask()
    settings = PRODUCTION_SETTINGS if production_mode() else DEFAULTS
    whisper_model = settings["whisper_model"]
    print(f"Preparando Ollama e {REVIEW_MODEL}...", flush=True)
    try:
        with ollama_server(task) as endpoint:
            prepare_review(task, endpoint)
        prepare_whisper_model(whisper_model, report=print)
    except Problem as error:
        print(error, file=sys.stderr, flush=True)
        return 1
    print(f"Modelos prontos: {REVIEW_MODEL} e Whisper {whisper_model}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
