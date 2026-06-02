"""FastAPI server for the ColorPlate GUI.

Serves the static front end and exposes the conversion pipeline over a small
JSON/multipart API. Launch with the ``colorplate-web`` console script.
"""
from __future__ import annotations

import argparse
import os
import tempfile
import uuid
import webbrowser

from . import service

try:
    from fastapi import FastAPI, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise SystemExit(
        "The web GUI needs the optional 'web' extra. Install it with:\n"
        "    pip install -e \".[web]\"\n"
        f"(missing: {exc.name})"
    )

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_ACCEPT = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class _RevalidatingStatic(StaticFiles):
    """Serve static assets with `Cache-Control: no-cache` so the browser always
    revalidates (cheap 304s via ETag) and never runs a stale JSX compile after
    the package is updated."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = "no-cache"
        return response


app = FastAPI(title="ColorPlate", docs_url=None, redoc_url=None)
store = service.SessionStore()
app.mount("/static", _RevalidatingStatic(directory=STATIC_DIR), name="static")


# ---- request models --------------------------------------------------------
class RedetectReq(BaseModel):
    uploadId: str
    maxColors: int


class PreviewReq(BaseModel):
    uploadId: str
    assignments: list[str]            # one filament hex per region, in order


class Filament(BaseModel):
    name: str
    hex: str


class GenerateReq(BaseModel):
    uploadId: str
    assignments: list[Filament]       # one per region, in order
    size: float
    front: float
    back: float
    backing: str | None = None        # filament hex or null


# ---- routes ----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.post("/api/detect")
async def api_detect(file: UploadFile, maxColors: int = Form(4)):
    name = file.filename or "logo.svg"
    ext = os.path.splitext(name)[1].lower()
    if ext not in _ACCEPT:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Use SVG or a raster image.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")

    sid = uuid.uuid4().hex
    out_dir = tempfile.mkdtemp(prefix="colorplate_")
    src_path = os.path.join(out_dir, "source" + ext)
    with open(src_path, "wb") as fh:
        fh.write(data)

    try:
        session, payload = service.load_session(
            sid, name, src_path, out_dir, _clamp_colors(maxColors)
        )
    except Exception as exc:
        service._cleanup_dir(out_dir)
        raise HTTPException(422, f"Could not read '{name}': {exc}")
    store.put(session)
    return payload


@app.post("/api/redetect")
def api_redetect(req: RedetectReq):
    session = _require(req.uploadId)
    return service.detect_from_path(session, _clamp_colors(req.maxColors))


@app.post("/api/preview")
def api_preview(req: PreviewReq):
    session = _require(req.uploadId)
    return {"preview": service.render_preview(session, req.assignments)}


@app.post("/api/generate")
def api_generate(req: GenerateReq):
    session = _require(req.uploadId)
    try:
        return service.generate(
            session,
            [a.model_dump() for a in req.assignments],
            size_mm=req.size, front_mm=req.front, back_mm=req.back,
            backing_hex=req.backing,
        )
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")


@app.get("/api/file/{upload_id}/{name}")
def api_file(upload_id: str, name: str):
    session = _require(upload_id)
    path = _safe_artifact(session, name)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/api/zip/{upload_id}/{name}")
def api_zip(upload_id: str, name: str):
    session = _require(upload_id)
    path = _safe_artifact(session, name)
    return FileResponse(path, filename=name, media_type="application/zip")


# ---- helpers ---------------------------------------------------------------
def _clamp_colors(n: int) -> int:
    return max(2, min(6, int(n)))


def _require(sid: str) -> service.Session:
    session = store.get(sid)
    if session is None:
        raise HTTPException(404, "Upload session expired — please re-upload the file.")
    return session


def _safe_artifact(session: service.Session, name: str) -> str:
    # prevent path traversal; only serve files inside the session's out_dir
    base = os.path.realpath(session.out_dir)
    path = os.path.realpath(os.path.join(base, name))
    if os.path.commonpath([base, path]) != base or not os.path.isfile(path):
        raise HTTPException(404, "File not found.")
    return path


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    # Env defaults make it deploy-friendly: hosts like Render inject $PORT and
    # expect the app to bind 0.0.0.0, so `colorplate-web` works with no flags.
    p = argparse.ArgumentParser(prog="colorplate-web",
                                description="Launch the ColorPlate GUI (and its API).")
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab.")
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev).")
    args = p.parse_args(argv)

    url = f"http://{args.host}:{args.port}/"
    is_local = args.host in ("127.0.0.1", "localhost", "::1")
    if is_local and not args.no_browser and not args.reload:
        import threading
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"ColorPlate serving on {url}")
    target = "colorplate.web.server:app" if args.reload else app
    uvicorn.run(target, host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
