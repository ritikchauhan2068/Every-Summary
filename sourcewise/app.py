import asyncio
import hashlib
import logging
import re
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from sourcewise.agent import Agent
from sourcewise.ai import Provider
from sourcewise.config import COOKIE_SECURE, DATA_DIR, MAX_MEDIA_BYTES, MAX_PDF_BYTES, WORKERS
from sourcewise.domain import Material, Passage, SourceError
from sourcewise.ingest import github, pdf, website, youtube
from sourcewise.ingest.network import parse_http_url
from sourcewise.store import Store

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SID = "sourcewise_session"
logger = logging.getLogger(__name__)
MEDIA_TYPES = {".mp3", ".wav", ".m4a", ".aac", ".mp4", ".mov", ".webm", ".ogg", ".flac", ".mkv", ".opus"}


def secure_unlink(path):
    if path:
        Path(path).unlink(missing_ok=True)


class Runtime:
    def __init__(self, directory):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.uploads = directory / "uploads"
        self.uploads.mkdir(mode=0o700, exist_ok=True)
        self.store = Store(directory / "sourcewise.sqlite3")
        self.provider = Provider()
        self.agent = Agent(self.provider)
        self.finished = threading.Event()
        self.jobs = threading.Event()
        self.chat_slots = asyncio.Semaphore(4)
        self.threads = [threading.Thread(target=self.run_jobs, name=f"sourcewise-jobs-{i}", daemon=True)
                        for i in range(WORKERS)]

    def run_jobs(self):
        while not self.finished.is_set():
            try:
                row = self.store.claim()
                if row:
                    self.process(row)
                    continue
            except Exception:
                logger.exception("Worker could not advance its queue")
            self.jobs.wait(0.5)
            self.jobs.clear()

    def process(self, row):
        def progress(stage):
            self.store.progress(row["id"], stage)
        url, path, name = row["url"], row["attachment"], row["filename"]
        try:
            if url == "demo:web":
                sample = (ROOT / "samples/retrieval.txt").read_text()
                material = Material("How retrieval-augmented generation works", "Built-in reading sample",
                                    [Passage(part, f"Section {i}") for i, part in enumerate(sample.strip().split("\n\n"), 1)])
            elif url == "demo:code":
                material = github.analyze((ROOT / "samples/reading_queue.py").read_text(), "reading_queue.py")
            elif row["kind"] == "website":
                material = website.load(url, progress)
            elif row["kind"] == "youtube":
                material = youtube.load(url, path, name, progress)
            elif row["kind"] == "pdf":
                material = pdf.load(path, name, progress)
            else:
                material = github.load_file(path, name, progress) if path else github.load(url, progress)
            if not material.passages:
                raise SourceError("The source did not contain any usable passages.")
            result = self.agent.prepare(material, progress)
            self.store.finish(row["id"], result=result)
            try:
                secure_unlink(path)
            except OSError:
                logger.warning("A processed attachment could not be removed")
        except SourceError as exc:
            self.store.finish(row["id"], error=str(exc))
        except Exception:
            logger.exception("A source could not be processed")
            self.store.finish(row["id"], error="Processing failed unexpectedly. Retry or choose another source.")


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class Demo(BaseModel):
    demo: Literal["web", "code"]


def create_app(data_dir=DATA_DIR):
    @asynccontextmanager
    async def lifespan(app):
        runtime = Runtime(Path(data_dir))
        app.state.runtime = runtime
        runtime.store.recover()
        for thread in runtime.threads:
            thread.start()
        try:
            yield
        finally:
            runtime.finished.set()
            runtime.jobs.set()
            await asyncio.gather(*(asyncio.to_thread(thread.join, 2) for thread in runtime.threads))

    app = FastAPI(title="Sourcewise API", version="1.0.0", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.middleware("http")
    async def session(request: Request, call_next):
        if request.method in {"POST", "DELETE"} and request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Open the workspace directly to make changes."}, status_code=403)
        if request.url.path == "/api/sources" and request.method == "POST":
            raw_length = request.headers.get("content-length", "")
            if raw_length.isdigit() and int(raw_length) > MAX_MEDIA_BYTES + 1024 * 1024:
                return JSONResponse({"detail": "The request exceeds the maximum upload size."}, status_code=413)
        sid = request.cookies.get(SID, "")
        fresh = not re.fullmatch(r"[a-f0-9]{64}", sid)
        if fresh:
            sid = secrets.token_hex(32)
        request.state.owner = hashlib.sha256(sid.encode()).hexdigest()
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == "/" or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if fresh and (request.url.path == "/" or request.url.path.startswith("/api/")):
            response.set_cookie(SID, sid, httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=365 * 86400)
        return response

    @app.exception_handler(SourceError)
    async def source_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html", headers={"Content-Security-Policy":
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})

    @app.get("/api/health")
    def health(request: Request):
        runtime = request.app.state.runtime
        return {"status": "ok", "ai_enabled": runtime.provider.enabled,
                "ai_mode": runtime.provider.label}

    @app.get("/api/sources")
    def library(request: Request):
        return request.app.state.runtime.store.library(request.state.owner)

    @app.post("/api/sources", status_code=202)
    async def create_source(
        request: Request,
        kind: Annotated[Literal["website", "youtube", "pdf", "github"], Form()],
        url: Annotated[str, Form(max_length=2048)] = "",
        file: Annotated[UploadFile | None, File()] = None,
    ):
        url = url.strip()
        runtime = request.app.state.runtime
        identifier = secrets.token_hex(12)
        name = Path((file.filename or "").replace("\\", "/")).name[:180] if file else ""
        path = None
        if kind == "pdf":
            if not file or Path(name).suffix.lower() != ".pdf":
                raise SourceError("Choose a PDF file.")
            url = ""
        elif kind == "youtube":
            if not file and not url:
                raise SourceError("Paste a YouTube link or upload a video or audio file.")
            if url:
                youtube.video_id(url)
            if file and Path(name).suffix.lower() not in MEDIA_TYPES:
                raise SourceError("Choose a supported audio or video format.")
        elif kind == "github" and file:
            url = ""
            if not name:
                raise SourceError("Choose a source code file.")
        else:
            if file:
                raise SourceError("Use a source URL for this source type.")
            host = parse_http_url(url).hostname
            if kind == "github" and host not in {"github.com", "raw.githubusercontent.com"}:
                raise SourceError("Enter an individual GitHub file URL.")
        if file:
            limit, label = {
                "pdf": (MAX_PDF_BYTES, "25 MB"), "youtube": (MAX_MEDIA_BYTES, "100 MB"),
                "github": (github.MAX_CODE_BYTES, "200 KB"),
            }[kind]
            if file.size == 0:
                raise SourceError("The uploaded file is empty.")
            if file.size is not None and file.size > limit:
                raise SourceError(f"The upload exceeds {label}.")
            extension = ".code" if kind == "github" else Path(name).suffix.lower()
            path = runtime.uploads / (identifier + extension)
            def save():
                total = 0
                with path.open("xb") as out:
                    while block := file.file.read(256 * 1024):
                        total += len(block)
                        if total > limit:
                            raise SourceError(f"The upload exceeds {label}.")
                        out.write(block)
            try:
                await run_in_threadpool(save)
            except BaseException:
                secure_unlink(path)
                raise
            finally:
                await file.close()
        title = name or (urlsplit(url).hostname if kind != "youtube" else "YouTube video")
        row = {"id": identifier, "owner": request.state.owner, "kind": kind, "url": url,
               "filename": name, "attachment": str(path) if path else "", "title": title}
        try:
            await run_in_threadpool(runtime.store.create, row)
        except Exception:
            secure_unlink(path)
            raise
        runtime.jobs.set()
        return {"id": identifier, "status": "queued"}

    @app.post("/api/samples", status_code=202)
    def create_demo(request: Request, body: Demo):
        runtime = request.app.state.runtime
        identifier = secrets.token_hex(12)
        kind, title = ("website", "How retrieval-augmented generation works") if body.demo == "web" else (
            "github", "reading_queue.py"
        )
        runtime.store.create({"id": identifier, "owner": request.state.owner, "kind": kind, "url": "demo:" + body.demo,
                              "filename": "", "attachment": "", "title": title})
        runtime.jobs.set()
        return {"id": identifier, "status": "queued"}

    def get_owned(request, identifier):
        runtime = request.app.state.runtime
        row = runtime.store.source(request.state.owner, identifier)
        if not row:
            raise HTTPException(404, "Source not found.")
        return runtime, row

    @app.get("/api/sources/{identifier}")
    def detail(request: Request, identifier: str):
        runtime, row = get_owned(request, identifier)
        row.pop("owner")
        row.pop("attachment")
        if row["result"]:
            row["result"].pop("vectors")
            row["result"].pop("embedding_model")
            row["history"] = runtime.store.history(identifier)
        return row

    @app.post("/api/sources/{identifier}/retry", status_code=202)
    def retry(request: Request, identifier: str):
        runtime, row = get_owned(request, identifier)
        if row["status"] != "failed" or not runtime.store.retry(request.state.owner, identifier):
            raise HTTPException(409, "Only failed sources can be retried.")
        runtime.jobs.set()
        return {"id": identifier, "status": "queued"}

    @app.delete("/api/sources/{identifier}")
    def delete(request: Request, identifier: str):
        runtime = request.app.state.runtime
        path = runtime.store.delete(request.state.owner, identifier)
        if path is None:
            raise HTTPException(404, "Source not found.")
        secure_unlink(path)
        return {"status": "deleted"}

    @app.post("/api/sources/{identifier}/questions")
    async def ask(request: Request, identifier: str, body: Question):
        runtime, row = await run_in_threadpool(get_owned, request, identifier)
        if not row["result"]:
            raise HTTPException(409, "Wait for the source to finish processing.")
        if runtime.chat_slots.locked():
            raise HTTPException(429, "The question service is busy. Try again shortly.")
        async with runtime.chat_slots:
            history = await run_in_threadpool(runtime.store.history, identifier)
            result = await run_in_threadpool(runtime.agent.answer, row["result"], body.question, history)
            try:
                await run_in_threadpool(runtime.store.add_chat, identifier, body.question, result)
            except sqlite3.IntegrityError as exc:
                raise HTTPException(404, "Source not found.") from exc
        return {"question": body.question, **result}

    @app.get("/api/sources/{identifier}/summary.txt", response_class=PlainTextResponse)
    def download_summary(request: Request, identifier: str):
        _, row = get_owned(request, identifier)
        if not row["result"]:
            raise HTTPException(409, "The summary is still processing.")
        digest = row["result"]["summary"]
        by_id = {p["id"]: p for p in row["result"]["passages"]}
        def refs(ids):
            return " ".join(f"[{by_id[id]['label']}]" for id in ids)
        content = [
            row["title"], row["result"]["method"], "", digest["overview"] + " " + refs(digest["citations"]),
            "", "Key takeaways", *[f"- {item['text']} {refs(item['citations'])}" for item in digest["items"]],
        ]
        return PlainTextResponse("\n".join(content), headers={"Content-Disposition": 'attachment; filename="summary.txt"'})

    return app


app = create_app()
