
import asyncio
import base64
import hashlib
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field

from . import config, sarvam
from .career import router as career_router
from .db import (
    WorkspaceExpired,
    close,
    encode,
    entities,
    entity,
    erase,
    find_scan,
    now,
    provision,
    session,
    touch,
    transaction,
    workspace_write,
)
from .decision_context import explain
from .demo import DEMO_SCAN, ensure_demo, read_owner
from .github import (
    CONTRIBUTION_LABELS,
    CONTRIBUTION_LANGUAGES,
    GitHubError,
    api,
    client,
    contribution_issues,
    public_repositories,
    read_source,
    repo_name,
    source_href,
)
from .knowledge import graph_status, remove_graph, trail
from .knowledge_anchor import enrich
from .migrate import migrate, require_current_schema
from .practice import router as practice_router
from .review import enabled as ai_enabled
from .sample import SNAPSHOT, SOURCES
from .scanning import compile_snapshot, run_scans, source_for
from .scoring import OPTIONAL, RUBRIC, finalize
from .trail_answer import select_evidence

WORKER_ENABLED = os.getenv("SCAN_WORKER_ENABLED", "true").lower() == "true"
DIST = config.ROOT / "apps" / "web" / "dist"
OAUTH_COOKIE = "__Host-skillforge-oauth" if config.PRODUCTION else "skillforge-oauth"


@asynccontextmanager
async def lifespan(_app):
    worker = None
    try:
        await asyncio.to_thread(require_current_schema if config.PRODUCTION else migrate)
        if WORKER_ENABLED:
            await asyncio.to_thread(ensure_demo)
            worker = asyncio.create_task(run_scans())
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        await asyncio.to_thread(close)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def boundaries(request, call_next):
    rejection = None
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != config.ORIGIN:
            rejection = JSONResponse({"detail": "Request origin could not be verified."}, 403)
        else:
            content_length = request.headers.get("content-length")
            limit = sarvam.MAX_AUDIO if request.url.path == "/api/transcribe" else 64_000
            if content_length and (not content_length.isdecimal() or int(content_length) > limit):
                rejection = JSONResponse({"detail": "Request is too large."}, 413)
    response = rejection if rejection is not None else await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    is_api = request.url.path.startswith("/api/")
    if is_api:
        response.headers["Cache-Control"] = "no-store"
    if config.PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" if is_api else
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
    return response


@app.exception_handler(GitHubError)
async def github_failure(_request, exc):
    return JSONResponse({"detail": str(exc), "retryAt": exc.retry_at}, 429 if exc.retry_at else 502)


@app.exception_handler(WorkspaceExpired)
async def expired_workspace(_request, _exc):
    return JSONResponse({"detail": "Your workspace expired. Refresh to start a new session."}, 401)


@app.exception_handler(DriverError)
@app.exception_handler(Neo4jError)
async def database_failure(_request, _exc):
    return JSONResponse({"detail": "The workspace database is temporarily unavailable."}, 503)


def write_cookie(response, token, github=False):
    response.set_cookie(config.COOKIE, token, httponly=True, secure=config.PRODUCTION,
                        samesite="lax", max_age=30 * 86400 if github else None, path="/")


def current_session(request):
    token = request.cookies.get(config.COOKIE)
    return session(token)


def owner_of(request):
    token = request.cookies.get(config.COOKIE)
    account = session(token)
    if not account:
        raise HTTPException(401, "Your workspace expired. Refresh to start a new session.")
    touch(token, account)
    return account["owner"]


@app.get("/api/health")
def health():
    with transaction() as tx:
        tx.run("RETURN 1").consume()
    return {"ok": True}


@app.get("/api/session")
def workspace_session(request: Request, response: Response):
    token = request.cookies.get(config.COOKIE)
    account = session(token)
    if account:
        touch(token, account)
    else:
        write_cookie(response, provision())
    return {"login": account["github"] if account else None, "oauth": bool(
        config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET,
    ), "ai": ai_enabled(), "judge": bool(config.JUDGE_URL and config.JUDGE_TOKEN), "voice": sarvam.enabled()}


@app.get("/api/auth/github")
def github_login():
    if not config.GITHUB_CLIENT_ID or not config.GITHUB_CLIENT_SECRET:
        return RedirectResponse("/?auth=unavailable")
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    response = RedirectResponse("https://github.com/login/oauth/authorize?" + urlencode({
        "client_id": config.GITHUB_CLIENT_ID, "state": state, "redirect_uri": config.GITHUB_CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "allow_signup": "true",
    }))
    response.set_cookie(OAUTH_COOKIE, state + "." + verifier, secure=config.PRODUCTION,
                        httponly=True, samesite="lax", max_age=600, path="/")
    return response


@app.get("/api/auth/github/callback")
async def github_callback(request: Request, code: str = "", state: str = ""):
    expected, _, verifier = request.cookies.get(OAUTH_COOKIE, "").partition(".")
    response = RedirectResponse("/?auth=failed")
    response.delete_cookie(OAUTH_COOKIE, path="/", secure=config.PRODUCTION, httponly=True)
    if not code or not expected or not secrets.compare_digest(expected, state) or not verifier:
        return response
    try:
        async with client() as http:
            exchange = await http.post("https://github.com/login/oauth/access_token", data={
                "client_id": config.GITHUB_CLIENT_ID, "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code, "redirect_uri": config.GITHUB_CALLBACK, "code_verifier": verifier,
            }, headers={"Accept": "application/json"})
            exchange.raise_for_status()
            token = exchange.json()["access_token"]
            user = await api(http, "/user", token=token, limit=64_000)
        owner = "github:" + str(int(user["id"]))
        if not isinstance(user["login"], str) or len(user["login"]) > 100:
            return response
        new = await asyncio.to_thread(provision, owner, user["login"], request.cookies.get(config.COOKIE))
        response.headers["location"] = "/?auth=connected"
        write_cookie(response, new, True)
    except (GitHubError, httpx.HTTPError, KeyError, TypeError, ValueError):
        pass
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get(config.COOKIE)
    response = Response(status_code=204)
    write_cookie(response, provision(previous=token))
    return response


@app.delete("/api/account")
def erase_workspace(request: Request):
    owner = owner_of(request)
    with workspace_write(owner, request.cookies[config.COOKIE]) as tx:
        erase(tx, owner)
    response = Response(status_code=204)
    write_cookie(response, provision())
    return response


@app.get("/api/github/repos")
async def list_github(request: Request, page: int = 1):
    account = await asyncio.to_thread(current_session, request)
    if not account or not account["github"]:
        raise HTTPException(401, "Connect GitHub to browse your public repositories.")
    return await public_repositories(account["github"], min(10, max(1, page)))


class ImportRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=280)
    ai: bool = False


class RubricApproval(BaseModel):
    expected: list[str] = Field(default_factory=list, max_length=len(OPTIONAL))
    note: str = Field(default="", max_length=600)


def scan_view(row, details=False):
    response = {key: row[key] for key in ("id", "repo", "state", "created", "updated")}
    response["knowledgeReady"] = bool(row.get("knowledgeRevision"))
    if row["result"]:
        if row["state"] == "failed":
            response["result"] = row["result"]
            return response
        payload = row["result"]
        quality = payload["quality"]
        response["revision"] = payload["revision"]
        if row["state"] == "review":
            if details:
                preview = {key: value for key, value in quality.items() if key in (
                    "scale", "version", "archetype", "cohort", "coverage", "features",
                )}
                preview["criteria"] = [
                    {key: value for key, value in item.items() if key != "checks"} for item in quality["criteria"]
                ]
                response["result"] = {**payload, "quality": {**preview, "score": None, "rankable": False,
                                                              "dimensions": [], "findings": []}}
            return response
        response["summary"] = {key: quality[key] for key in (
            "score", "rankable", "cohort", "version", "coverage", "scale", "archetype", "grade", "comparisonKey",
        ) if key in quality}
        if details:
            response["result"] = payload
    return response


@app.post("/api/scans", status_code=202)
def start_scan(body: ImportRequest, request: Request):
    owner = owner_of(request)
    try:
        repository = repo_name(body.repository)
    except GitHubError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.ai and not ai_enabled():
        raise HTTPException(409, "AI review is unavailable. Start a static review instead.")
    with workspace_write(owner, request.cookies[config.COOKIE]) as tx:
        timestamp = now()
        active = entities(tx, """
            MATCH (s:SFScan {owner: $owner}) WHERE s.state IN ['queued', 'running']
            RETURN s AS node LIMIT 4
            """, owner=owner)
        existing = next((row for row in active if row["repo"] == repository and row["options"]["ai"] == body.ai), None)
        if existing:
            return scan_view(existing)
        recent = tx.run("""
            MATCH (s:SFScan {owner: $owner}) WHERE s.created >= $since
            WITH s LIMIT 12 RETURN count(s) AS total
            """, owner=owner, since=timestamp - 3600).single()["total"]
        if len(active) >= 3 or recent >= 12:
            raise HTTPException(429, "This workspace has reached its scan limit. Try again later.")
        row = {"id": str(uuid4()), "repo": repository, "owner": owner, "state": "queued",
               "created": timestamp, "updated": timestamp, "options": {"ai": body.ai}, "result": None}
        tx.run("CREATE (s:SFScan) SET s = $row", row={**row, "options": encode(row["options"])}).consume()
    return scan_view(row)


@app.get("/api/scans")
def list_scans(request: Request):
    owner = owner_of(request)
    with transaction() as tx:
        rows = entities(tx, """
            MATCH (s:SFScan {owner: $owner})
            RETURN s AS node ORDER BY s.created DESC, s.id DESC LIMIT 60
            """, owner=owner)
    return [scan_view(row) for row in rows]


def lookup(owner, scan_id):
    with transaction() as tx:
        row = find_scan(tx, owner, scan_id)
    if not row:
        raise HTTPException(404, "This scan is unavailable in your workspace.")
    return row


@app.get("/api/scans/{scan_id}")
def scan_details(scan_id: str, request: Request):
    return scan_view(lookup(read_owner(owner_of(request), scan_id), scan_id), details=True)


@app.post("/api/scans/{scan_id}/rubric")
def publish_rubric(scan_id: str, body: RubricApproval, request: Request):
    owner = owner_of(request)
    row = lookup(owner, scan_id)
    if row["state"] == "complete":
        return scan_view(row, details=True)
    result = row["result"]
    if row["state"] != "review" or result["quality"]["version"] != RUBRIC:
        raise HTTPException(409, "This scan has no current rubric to approve.")
    possible = {choice["id"] for choice in result["quality"]["criteria"]
                if choice["relevance"] == "not_applicable"}
    expected = sorted(set(body.expected))
    if not set(expected).issubset(possible):
        raise HTTPException(422, "Only excluded criteria can be marked as expected capabilities.")
    updated = {**result, "quality": finalize(result["quality"], expected, body.note.strip())}
    with workspace_write(owner, request.cookies[config.COOKIE]) as tx:
        changed = tx.run("""
            MATCH (s:SFScan {owner: $owner, id: $id})
            SET s.lock = coalesce(s.lock, 0) + 1
            WITH s WHERE s.state = 'review'
            SET s.state = 'complete', s.result = $result, s.updated = $now
            RETURN s AS node
            """, owner=owner, id=scan_id, result=encode(updated), now=now()).single()
    return scan_view(entity(changed) if changed else lookup(owner, scan_id), details=True)


@app.delete("/api/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: str, request: Request):
    owner = owner_of(request)
    with workspace_write(owner, request.cookies[config.COOKIE]) as tx:
        scan = tx.run("""
            MATCH (s:SFScan {owner: $owner, id: $id})
            SET s.lock = coalesce(s.lock, 0) + 1 RETURN s.id
            """, owner=owner, id=scan_id).single()
        if scan:
            remove_graph(tx, scan_id)
            tx.run("MATCH (s:SFScan {owner: $owner, id: $id}) DELETE s", owner=owner, id=scan_id).consume()
    return Response(status_code=204)


class TrailQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1500)
    path: str | None = Field(default=None, max_length=400)
    line: int | None = Field(default=None, ge=1, le=1_000_000)
    ai: bool = False


def reserve_assistant(owner, token, voice):
    timestamp = now()
    with workspace_write(owner, token) as tx:
        row = tx.run("""
            MATCH (w:SFWorkspace {owner: $owner}), (store:SFStore {id: 'skillforge'})
            SET store.assistantVersion = coalesce(store.assistantVersion, 0) + 1
            WITH w, store, [at IN coalesce(w.assistantCalls, []) WHERE at > $cutoff] AS ownerCalls,
                 [at IN coalesce(store.assistantCalls, []) WHERE at > $cutoff] AS serviceCalls
            WHERE size(ownerCalls) < $ownerLimit AND size(serviceCalls) < 40
            SET w.assistantCalls = ownerCalls + $now, store.assistantCalls = serviceCalls + $now
            RETURN w.owner
            """, owner=owner, cutoff=timestamp - 60, ownerLimit=6 if voice else 12, now=timestamp).single()
        if not row:
            raise HTTPException(429, "The repository assistant is busy. Try again in a minute.")


@app.get("/api/scans/{scan_id}/knowledge")
def knowledge_status(scan_id: str, request: Request):
    state = graph_status(read_owner(owner_of(request), scan_id), scan_id)
    if state is None:
        raise HTTPException(404, "This scan is unavailable in your workspace.")
    return state


@app.get("/api/scans/{scan_id}/knowledge/preview")
def knowledge_preview(scan_id: str, request: Request):
    owner = owner_of(request)
    owner = read_owner(owner, scan_id)
    state = graph_status(owner, scan_id)
    if state is None:
        raise HTTPException(404, "This scan is unavailable in your workspace.")
    if not state["revision"]:
        raise HTTPException(409, "The knowledge graph is still being prepared.")
    return trail(owner, scan_id, "")


@app.post("/api/scans/{scan_id}/knowledge/ask")
async def ask_knowledge(scan_id: str, body: TrailQuestion, request: Request):
    owner = await asyncio.to_thread(owner_of, request)
    graph_owner = read_owner(owner, scan_id)
    state = await asyncio.to_thread(graph_status, graph_owner, scan_id)
    if state is None:
        raise HTTPException(404, "This scan is unavailable in your workspace.")
    if not state["revision"]:
        raise HTTPException(409, "A knowledge graph is unavailable for this scan. Import the repository again.")
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Enter a question about this repository.")
    path = body.path.strip() if body.path else None
    if path and (any(part in {"", ".", ".."} for part in path.split("/")) or chr(92) in path):
        raise HTTPException(422, "Enter a repository-relative file path.")
    await asyncio.to_thread(reserve_assistant, owner, request.cookies[config.COOKIE], False)
    anchors, line_content = (), ""
    if scan_id != DEMO_SCAN:
        anchors, line_content = await enrich(owner, request.cookies[config.COOKIE], scan_id, state,
                                             question, path, body.line)
    graph = await asyncio.to_thread(trail, graph_owner, scan_id, question + " " + line_content, path, anchors)
    answer = await select_evidence(question, graph, body.ai)
    return {**answer, "graph": graph, "source": source_href(
        state["repo"], state["revision"], path, body.line,
    ) if path else None}


@app.post("/api/transcribe")
async def transcribe_question(request: Request):
    owner = await asyncio.to_thread(owner_of, request)
    if not sarvam.enabled():
        raise HTTPException(503, "Sarvam voice input is unavailable. You can type your question.")
    media_type = request.headers.get("content-type", "").split(";", 1)[0]
    if media_type not in sarvam.AUDIO_TYPES:
        raise HTTPException(415, "This recording format is unsupported.")
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > sarvam.MAX_AUDIO:
            raise HTTPException(413, "The recording is too large.")
        audio.extend(chunk)
    if not audio:
        raise HTTPException(422, "Record a question before transcribing.")
    await asyncio.to_thread(reserve_assistant, owner, request.cookies[config.COOKIE], True)
    try:
        return {"text": await sarvam.transcribe(bytes(audio), media_type)}
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "Sarvam could not transcribe this recording. Try again or type your question.") from exc


@app.get("/api/contributions")
async def contributions(request: Request, language: str, label: str, page: int = Query(1, ge=1, le=10)):
    await asyncio.to_thread(owner_of, request)
    if language not in CONTRIBUTION_LANGUAGES or label not in CONTRIBUTION_LABELS:
        raise HTTPException(422, "Choose a supported language and issue label.")
    try:
        return await contribution_issues(language, label, page)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "GitHub issue search is temporarily unavailable.") from exc


class ContextQuestion(BaseModel):
    question: str = Field(default="", max_length=200)
    path: str | None = Field(default=None, max_length=400)
    through: date | None = None
    neo4j: bool = False


async def context_for(snapshot, body):
    if not body.question.strip() and not body.path:
        raise HTTPException(422, "Enter a question or select a finding with a file.")
    if body.path and body.path not in snapshot["preview_paths"]:
        raise HTTPException(422, "This file is outside the analyzed source sample.")
    return await explain(snapshot, body.question, body.path, body.through.isoformat() if body.through else None,
                         body.neo4j)


@app.post("/api/scans/{scan_id}/context")
async def scan_context(scan_id: str, body: ContextQuestion, request: Request):
    owner = await asyncio.to_thread(owner_of, request)
    row = await asyncio.to_thread(lookup, read_owner(owner, scan_id), scan_id)
    if row["state"] not in {"complete", "review"}:
        raise HTTPException(409, "Context is available after indexing.")
    return await context_for(row["result"], body)


@app.post("/api/sample/context")
async def sample_context(body: ContextQuestion, request: Request):
    await asyncio.to_thread(owner_of, request)
    return await context_for(compile_snapshot(SNAPSHOT), body)


@app.get("/api/scans/{scan_id}/source")
async def preview(scan_id: str, path: str, request: Request):
    owner = await asyncio.to_thread(owner_of, request)
    row = await asyncio.to_thread(lookup, read_owner(owner, scan_id), scan_id)
    result = row["result"]
    if row["state"] not in {"complete", "review"} or path not in result["preview_paths"]:
        raise HTTPException(404, "This file is outside the analyzed source sample.")
    async with client() as http:
        try:
            source = await read_source(http, row["repo"], result["revision"], path)
        except httpx.HTTPError as exc:
            raise HTTPException(502, "GitHub could not provide the selected file.") from exc
    return {"path": path, "source": source, "url": source_for(result, path)}


@app.get("/api/sample")
def sample():
    return compile_snapshot(SNAPSHOT)


@app.get("/api/sample/source")
def sample_source(path: str):
    if path not in SOURCES:
        raise HTTPException(404, "This file is outside the sample.")
    return {"path": path, "source": SOURCES[path], "url": None}


app.include_router(practice_router)
app.include_router(career_router)


if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots():
    return PlainTextResponse(f"User-agent: *\nDisallow: /api/\nSitemap: {config.ORIGIN}/sitemap.xml\n")


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap():
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{escape(config.ORIGIN)}/</loc></url>\n"
        "</urlset>\n",
        media_type="application/xml",
    )


@app.api_route("/share-card.png", methods=["GET", "HEAD"])
def share_card():
    image = DIST / "share-card.png"
    if not image.is_file():
        raise HTTPException(404, "Build the web application first.")
    return FileResponse(image, media_type="image/png")


@app.api_route("/", methods=["GET", "HEAD"])
def index():
    index_file = Path(DIST / "index.html")
    if not index_file.is_file():
        raise HTTPException(404, "Start the Vite development server or build the web application.")
    canonical = escape(config.ORIGIN + "/", quote=True)
    metadata = (
        f'<link rel="canonical" href="{canonical}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:image" content="{canonical}share-card.png">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        '<meta property="og:image:alt" content="SkillForge repository graphs and engineering scorecards">'
    )
    return HTMLResponse(index_file.read_text(encoding="utf-8").replace("<!-- public-page-urls -->", metadata, 1))
