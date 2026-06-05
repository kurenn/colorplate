"""FastAPI server for the ColorPlate GUI.

Serves the static front end and exposes the conversion pipeline over a small
JSON/multipart API. Launch with the ``colorplate-web`` console script.
"""
from __future__ import annotations

import argparse
import os
import tempfile
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager

from . import analytics, service

try:
    from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    analytics.init()
    yield


app = FastAPI(title="ColorPlate", docs_url=None, redoc_url=None, lifespan=_lifespan)
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


class Mesh3DReq(BaseModel):
    uploadId: str
    size: float
    front: float
    back: float


class Stack3DReq(BaseModel):
    uploadId: str
    assignments: list[str]            # one filament hex per region, in order
    order: list[str]                  # distinct filament hexes, base -> top
    size: float
    base: float
    step: float
    layer: float


class GenerateReq(BaseModel):
    uploadId: str
    assignments: list[Filament]       # one per region, in order
    size: float
    front: float
    back: float
    backing: str | None = None        # filament hex or null


class StackGenerateReq(BaseModel):
    uploadId: str
    assignments: list[Filament]       # one per region, in order
    order: list[str]                  # distinct filament hexes, base -> top
    size: float
    base: float
    step: float
    layer: float


# ---- routes ----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.post("/api/detect")
async def api_detect(request: Request, file: UploadFile, maxColors: int = Form(4)):
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
    analytics.record("detect", request, ext=ext.lstrip("."),
                     max_colors=_clamp_colors(maxColors), regions=len(payload["regions"]),
                     kb=round(len(data) / 1024))
    return payload


@app.post("/api/redetect")
def api_redetect(request: Request, req: RedetectReq):
    session = _require(req.uploadId)
    payload = service.detect_from_path(session, _clamp_colors(req.maxColors))
    analytics.record("redetect", request, max_colors=_clamp_colors(req.maxColors),
                     regions=len(payload["regions"]))
    return payload


@app.post("/api/preview")
def api_preview(req: PreviewReq):
    session = _require(req.uploadId)
    return {"preview": service.render_preview(session, req.assignments)}


@app.post("/api/mesh3d")
def api_mesh3d(req: Mesh3DReq):
    session = _require(req.uploadId)
    try:
        return service.build_mesh3d(
            session, size_mm=max(1.0, req.size),
            front_mm=max(0.1, req.front), back_mm=max(0.1, req.back),
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(500, f"3D preview failed: {exc}")


@app.post("/api/stack3d")
def api_stack3d(req: Stack3DReq):
    session = _require(req.uploadId)
    try:
        return service.build_stack3d(
            session, assignments=req.assignments, order=req.order,
            size_mm=max(1.0, req.size), base_mm=max(0.1, req.base),
            step_mm=max(0.1, req.step), layer_mm=max(0.04, req.layer),
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(500, f"Single-extruder preview failed: {exc}")


@app.post("/api/generate")
def api_generate(request: Request, req: GenerateReq):
    session = _require(req.uploadId)
    try:
        t0 = time.monotonic()
        result = service.generate(
            session,
            [a.model_dump() for a in req.assignments],
            size_mm=req.size, front_mm=req.front, back_mm=req.back,
            backing_hex=req.backing,
        )
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")
    analytics.record("generate", request, files=len(result["files"]),
                     total_mb=result["totalMB"], size_mm=req.size,
                     backing=bool(req.backing), ms=round((time.monotonic() - t0) * 1000))
    return result


@app.post("/api/generate-stack")
def api_generate_stack(request: Request, req: StackGenerateReq):
    session = _require(req.uploadId)
    try:
        t0 = time.monotonic()
        result = service.generate_stack(
            session,
            [a.model_dump() for a in req.assignments],
            req.order,
            size_mm=req.size, base_mm=max(0.1, req.base),
            step_mm=max(0.1, req.step), layer_mm=max(0.04, req.layer),
        )
    except Exception as exc:
        raise HTTPException(500, f"Single-extruder export failed: {exc}")
    analytics.record("generate", request, mode="single", files=len(result["files"]),
                     total_mb=result["totalMB"], size_mm=req.size,
                     swaps=result["swaps"], ms=round((time.monotonic() - t0) * 1000))
    return result


@app.get("/api/file/{upload_id}/{name}")
def api_file(request: Request, upload_id: str, name: str):
    session = _require(upload_id)
    path = _safe_artifact(session, name)
    analytics.record("download", request, kind="stl", ext=os.path.splitext(name)[1].lstrip("."))
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/api/zip/{upload_id}/{name}")
def api_zip(request: Request, upload_id: str, name: str):
    session = _require(upload_id)
    path = _safe_artifact(session, name)
    analytics.record("download", request, kind="zip")
    return FileResponse(path, filename=name, media_type="application/zip")


_STATS_COOKIE = "cp_stats"


@app.get("/stats")
def stats_view(request: Request, token: str = "", format: str = "html"):
    """Usage dashboard. Protected by COLORPLATE_STATS_TOKEN when set (always in
    production); open locally when no token is configured.

    Pass ?token=<value> once and the response sets a cookie, so afterwards plain
    /stats works in that browser without the token in the URL."""
    expected = os.environ.get("COLORPLATE_STATS_TOKEN")
    if expected:
        provided = token or request.cookies.get(_STATS_COOKIE, "")
        if provided != expected:
            raise HTTPException(
                401, "Missing or invalid token. Visit /stats?token=<COLORPLATE_STATS_TOKEN> "
                     "once and this browser will be remembered.")

    data = analytics.stats()
    resp = JSONResponse(data) if format == "json" else HTMLResponse(_stats_html(data))

    # Remember a freshly-supplied query token so the URL token isn't needed again.
    if expected and token == expected:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        resp.set_cookie(_STATS_COOKIE, expected, max_age=60 * 60 * 24 * 90,
                        httponly=True, samesite="lax", secure=(proto == "https"))
    return resp


# ---- helpers ---------------------------------------------------------------
def _stats_html(d: dict) -> str:
    import html

    def esc(x):
        return html.escape(str(x))

    rows = "".join(
        f"<tr><td>{esc(r['day'])}</td><td>{esc(r['events'])}</td><td>{esc(r['visitors'])}</td></tr>"
        for r in d["daily"]
    ) or "<tr><td colspan='3' style='color:#888'>No activity yet.</td></tr>"
    by_type = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td><td>{esc(d['last7_by_type'].get(k, 0))}</td></tr>"
        for k, v in sorted(d["totals_by_type"].items())
    ) or "<tr><td colspan='3' style='color:#888'>—</td></tr>"
    cards = [
        ("Total events", d["total_events"]),
        ("Unique visitors", d["unique_visitors_total"]),
        ("Visitors (7d)", d["unique_visitors_7d"]),
        ("Generates", d["totals_by_type"].get("generate", 0)),
    ]
    card_html = "".join(
        f"<div class=card><div class=n>{esc(v)}</div><div class=l>{esc(l)}</div></div>"
        for l, v in cards
    )
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>ColorPlate · usage</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
 body{{font:14px/1.5 ui-sans-serif,system-ui,sans-serif;margin:0;background:#0c0c0e;color:#f3f3f4;padding:32px}}
 h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#9a9aa1;margin:0 0 24px;font-size:12px}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:28px}}
 .card{{background:#141417;border:1px solid #27272d;border-radius:10px;padding:16px}}
 .card .n{{font-size:28px;font-weight:700}} .card .l{{color:#9a9aa1;font-size:12px;margin-top:2px}}
 h2{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6a6a73;margin:24px 0 8px}}
 table{{width:100%;border-collapse:collapse;background:#141417;border:1px solid #27272d;border-radius:10px;overflow:hidden}}
 th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #1f1f24;font-variant-numeric:tabular-nums}}
 th{{color:#9a9aa1;font-weight:500;font-size:12px}} tr:last-child td{{border-bottom:0}}
 .foot{{color:#6a6a73;font-size:11px;margin-top:20px}}
</style></head><body>
<h1>ColorPlate · usage</h1>
<p class=sub>first event {esc(d['first_event'] or '—')} · latest {esc(d['last_event'] or '—')} (UTC)</p>
<div class=cards>{card_html}</div>
<h2>By event type</h2>
<table><tr><th>type</th><th>all time</th><th>last 7d</th></tr>{by_type}</table>
<h2>Daily (last 14 days)</h2>
<table><tr><th>day (UTC)</th><th>events</th><th>visitors</th></tr>{rows}</table>
<p class=foot>Privacy: no artwork, filenames, or raw IPs are stored — visitors are counted via a salted one-way hash.</p>
</body></html>"""



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
