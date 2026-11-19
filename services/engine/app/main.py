import hmac
import json
import logging
import os
import secrets
import shutil
import socket
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from filelock import FileLock, Timeout
from starlette.middleware.cors import CORSMiddleware

from .config import DATA, ORIGINS, PROJECTS, Problem
from .db import initialize
from .jobs import Jobs

VERSION = "0.1.0"


def error_response(code, message, status):
    return JSONResponse({"error": {"code": code, "message": message, "details": None}}, status_code=status)


def create_app(token, host):
    @asynccontextmanager
    async def lifespan(app):
        initialize()
        PROJECTS.mkdir(exist_ok=True)
        for pattern in ("process-*", "projects/*/analysis-*", "projects/*/download-*"):
            for path in DATA.glob(pattern):
                if path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(DATA):
                    shutil.rmtree(path, ignore_errors=True)
        handler = RotatingFileHandler(DATA / "engine.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        logger = logging.getLogger("clip-factory")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        app.state.jobs = Jobs()
        try:
            yield
        finally:
            app.state.jobs.stop()
            logger.removeHandler(handler)
            handler.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def protected(request: Request, call_next):
        if request.headers.get("host") != host:
            return error_response("HOST_DENIED", "Host inválido.", 403)
        origin = request.headers.get("origin")
        if origin and origin not in ORIGINS:
            return error_response("ORIGIN_DENIED", "Origem inválida.", 403)
        path = request.url.path
        if path != "/health" and not path.startswith("/media/") and request.method != "OPTIONS":
            authorization = request.headers.get("authorization", "").encode()
            if not hmac.compare_digest(authorization, f"Bearer {token}".encode()):
                return error_response("UNAUTHORIZED", "Sessão inválida. Reabra o aplicativo.", 401)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Problem)
    async def known_error(_request, error):
        return error_response(error.code, str(error), error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, _error):
        return error_response("INVALID_INPUT", "Confira os campos e os limites solicitados.", 422)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": VERSION}

    from .api import router
    app.include_router(router)
    return app


def main():
    if sys.argv[1:2] == ["--worker"]:
        from .pipeline import worker_main
        worker_main(sys.argv[2], sys.argv[3:])
        return

    token = secrets.token_urlsafe(32)
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(DATA / "engine.lock", timeout=0):
            run_server(token)
    except Timeout:
        sys.exit("O motor local já está aberto neste perfil.")


def run_server(token):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        host = f"127.0.0.1:{listener.getsockname()[1]}"
        app = create_app(token, host)

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets)
                if self.started:
                    print(json.dumps({"url": f"http://{host}", "token": token}), flush=True)

        server = ReadyServer(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=4))
        if os.environ.get("CLIP_FACTORY_MANAGED") == "1":
            def watch_parent():
                sys.stdin.buffer.read()
                server.should_exit = True
                if hasattr(app.state, "jobs"):
                    with app.state.jobs.lock:
                        for job in app.state.jobs.active.values():
                            job.cancelled.set()

            Thread(target=watch_parent, daemon=True).start()

        server.run(sockets=[listener])


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
