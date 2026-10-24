"""``pad-guard ui``: the local web interface (Phase 5).

A small Starlette server on 127.0.0.1 only. It serves the page and its files from ``static/`` (no
CDN, no font or script from the Internet: the Content-Security-Policy forbids it) and a JSON API
over the files PAD Guard writes. It computes nothing about the verdict: the analyses run the CLI.

Local protection: other web sites open in the same browser could send requests to 127.0.0.1. The
Host header must name this server (no DNS rebinding), an Origin header must be ours, and every API
call carries the session token written into the page (header ``X-PAD-Guard``, or ``?t=`` for the
links, images and the event stream, which cannot send headers).
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import socket
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from pad_guard import __version__
from pad_guard.ui import settings as settings_mod

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[3]  # repository: profiles/, normes/, diffuseurs/
HOST = "127.0.0.1"  # never anything else: nothing leaves the machine
DEFAULT_PORT = 8765
TOKEN_HEADER = "x-pad-guard"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")

# Windows may map .js to text/plain in its registry: a module script would then be refused.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/woff2", ".woff2")


class ApiError(Exception):
    """A user-facing (French) refusal of the API, sent as {"error": message}."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Context:
    token: str
    hosts: set[str]  # accepted Host headers
    settings_file: Path
    root: Path = ROOT
    extra: dict[str, Any] = field(default_factory=dict)  # services of the other modules (jobs...)

    @property
    def origins(self) -> set[str]:
        return {f"http://{h}" for h in self.hosts}

    def settings(self) -> settings_mod.Settings:
        return settings_mod.load(self.settings_file)


class LocalGuard:
    """Host and Origin checks on every request, session token on /api/ (except /api/ping)."""

    def __init__(self, app: ASGIApp, ctx: Context):
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        path = scope["path"]
        refusal = None
        if host not in self.ctx.hosts:
            refusal = "hôte non autorisé"
        elif origin is not None and origin not in self.ctx.origins:
            refusal = "origine non autorisée"
        elif path.startswith("/api/") and path != "/api/ping":
            given = request.headers.get(TOKEN_HEADER) or request.query_params.get("t")
            if not given or not secrets.compare_digest(given, self.ctx.token):
                refusal = "jeton de session absent ou invalide : recharger la page"
        if refusal:
            await JSONResponse({"error": refusal}, status_code=403)(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers += [(b"content-security-policy", CSP.encode()), (b"x-content-type-options", b"nosniff"),
                            (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def ctx_of(request: Request) -> Context:
    return request.app.state.ctx


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise ApiError("requête illisible (JSON attendu)") from None
    if not isinstance(data, dict):
        raise ApiError("requête illisible (objet JSON attendu)")
    return data


async def index(request: Request) -> Response:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("{{TOKEN}}", ctx_of(request).token).replace("{{VERSION}}", __version__))


async def ping(_: Request) -> Response:
    return JSONResponse({"app": "pad-guard", "version": __version__})


async def get_settings(request: Request) -> Response:
    s = ctx_of(request).settings()
    return JSONResponse({"analyses_root": str(s.root), "default_root": str(settings_mod.default_root())})


async def put_settings(request: Request) -> Response:
    ctx = ctx_of(request)
    data = await body(request)
    root = str(data.get("analyses_root") or "").strip()
    if not root:
        raise ApiError("dossier des analyses vide")
    path = Path(root)
    if not path.is_absolute():
        raise ApiError(f"chemin complet attendu (ex. C:\\Users\\…\\Documents\\PAD Guard\\analyses) : {root}")
    if path.resolve().is_relative_to(ctx.root.resolve()):
        raise ApiError("le dossier des analyses ne doit pas être dans le dépôt de PAD Guard")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ApiError(f"dossier impossible à créer : {path} ({exc.strerror})") from None
    settings_mod.save(settings_mod.Settings(analyses_root=str(path)), ctx.settings_file)
    return await get_settings(request)


async def api_error(_: Request, exc: ApiError) -> Response:
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


def routes() -> list:
    from pad_guard.ui import api  # noqa: PLC0415 - the API modules import this one

    return [
        Route("/", index),
        Route("/api/ping", ping),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", put_settings, methods=["PUT"]),
        *api.routes(),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]


def create_app(ctx: Context) -> Starlette:
    app = Starlette(routes=routes(), middleware=[Middleware(LocalGuard, ctx=ctx)],
                    exception_handlers={ApiError: api_error})
    app.state.ctx = ctx
    from pad_guard.ui import api  # noqa: PLC0415

    api.start(ctx)
    return app


def _bind(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if hasattr(socket, "SO_EXCLUSIVEADDRUSE")
                    else socket.SO_REUSEADDR, 1)
    sock.bind((HOST, port))
    return sock


def _already_running(port: int) -> bool:
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/ping", timeout=2) as r:  # noqa: S310 - 127.0.0.1
            return json.loads(r.read()).get("app") == "pad-guard"
    except (OSError, ValueError):
        return False


def serve(port: int = DEFAULT_PORT, open_browser: bool = True, say=print) -> None:
    import uvicorn  # noqa: PLC0415

    try:
        sock = _bind(port)
    except OSError:
        if port and _already_running(port):
            say(f"PAD Guard est déjà lancé : http://{HOST}:{port}/")
            if open_browser:
                webbrowser.open(f"http://{HOST}:{port}/")
            return
        sock = _bind(0)  # port taken by another program: any free port
    port = sock.getsockname()[1]
    url = f"http://{HOST}:{port}/"
    ctx = Context(token=secrets.token_urlsafe(32), hosts={f"{HOST}:{port}", f"localhost:{port}"},
                  settings_file=settings_mod.settings_path())
    app = create_app(ctx)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    say(f"PAD Guard : {url}  (local, rien ne sort de la machine ; Ctrl+C pour arrêter)")
    if open_browser:
        def wait_and_open() -> None:
            for _ in range(100):
                if server.started:
                    webbrowser.open(url)
                    return
                threading.Event().wait(0.1)

        threading.Thread(target=wait_and_open, daemon=True).start()
    server.run(sockets=[sock])
