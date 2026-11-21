
import asyncio
import json
import re
from urllib.parse import quote, urlsplit

import httpx

from .config import GITHUB_TOKEN

NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
SHA = re.compile(r"[a-f0-9]{40}")
MAX_FILES = 72
FILE_BYTES = 64_000
MAX_TREE_BYTES = 8_000_000
EXCLUDED = {"node_modules", "vendor", "dist", "build", ".venv", "__pycache__", "generated"}
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}


class GitHubError(Exception):
    def __init__(self, message, retry_at=None):
        super().__init__(message)
        self.retry_at = retry_at


def repo_name(value):
    value = value.strip()
    if value.lower().startswith("github.com/"):
        value = "https://" + value
    if "://" in value:
        try:
            url = urlsplit(value)
            if url.scheme != "https" or url.netloc.lower() != "github.com" or url.query or url.fragment:
                raise ValueError
            value = url.path.strip("/")
        except ValueError as exc:
            raise GitHubError("Enter a public GitHub URL such as https://github.com/owner/repo.") from exc
    parts = value.removesuffix(".git").split("/")
    if len(parts) != 2 or any(not NAME.fullmatch(part) or part in {".", ".."} for part in parts):
        raise GitHubError("Enter a GitHub repository in owner/repo format.")
    return "/".join(parts).lower()


def headers(token=GITHUB_TOKEN):
    result = {"Accept": "application/vnd.github+json", "User-Agent": "SkillForge"}
    if token:
        result["Authorization"] = "Bearer " + token
    return result


def client():
    return httpx.AsyncClient(timeout=12, follow_redirects=False, limits=httpx.Limits(max_connections=8))


def check_response(response):
    if response.status_code == 429 or (
        response.status_code == 403
        and (response.headers.get("x-ratelimit-remaining") == "0" or response.headers.get("retry-after"))
    ):
        reset = response.headers.get("x-ratelimit-reset", "")
        raise GitHubError("GitHub is throttling requests. Try again after the rate limit resets.",
                          int(reset) if reset.isdecimal() else None)
    if response.status_code in (403, 404):
        raise GitHubError("This public GitHub resource could not be accessed.")
    if response.status_code != 200:
        raise GitHubError("GitHub could not complete the request. Try again shortly.")


async def api(http, path, params=None, token=GITHUB_TOKEN, limit=MAX_TREE_BYTES):
    async with http.stream("GET", "https://api.github.com" + path, params=params, headers=headers(token)) as response:
        check_response(response)
        content = bytearray()
        async for chunk in response.aiter_bytes(16384):
            content.extend(chunk)
            if len(content) > limit:
                raise GitHubError("GitHub returned more metadata than this workspace can analyze.")
    return json.loads(content)


def source_path(path):
    if not path or len(path) > 400 or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    if any(part in EXCLUDED for part in path.split("/")[:-1]):
        return False
    name = path.rsplit("/", 1)[-1].lower()
    return not name.endswith((".min.js", ".d.ts")) and any(name.endswith(ext) for ext in SOURCE_EXTENSIONS)


def test_path(path):
    parts = path.lower().split("/")
    return any(part in {"tests", "test", "__tests__", "spec"} for part in parts[:-1]) or (
        parts[-1].startswith("test_") or any(part in parts[-1] for part in (".test.", ".spec.", "_test.py"))
    )


def source_href(repo, revision, path, line=None):
    return f"https://github.com/{repo}/blob/{revision}/{quote(path, safe='/')}" + (f"#L{line}" if line else "")


async def read_source(http, repo, revision, path):
    target = f"https://raw.githubusercontent.com/{repo}/{revision}/{quote(path, safe='/')}"
    async with http.stream("GET", target, headers={"User-Agent": "SkillForge"}) as response:
        check_response(response)
        body = bytearray()
        async for chunk in response.aiter_bytes(16384):
            body.extend(chunk)
            if len(body) > FILE_BYTES:
                raise GitHubError("This file exceeds the preview size limit.")
    if b"\0" in body:
        raise GitHubError("Binary source previews are unavailable.")
    return body.decode("utf-8", errors="replace")


async def get_snapshot(repo, *, on_revision=None):
    async with client() as http:
        info = await api(http, "/repos/" + repo, limit=128_000)
        if info.get("private") or info.get("visibility") != "public":
            raise GitHubError("This workspace accepts public GitHub repositories.")
        branch = info["default_branch"]
        commit = await api(http, f"/repos/{repo}/commits/{quote(branch, safe='')}", limit=1_500_000)
        revision = commit["sha"]
        if on_revision:
            await on_revision(http, repo, revision, info)
        tree_sha = commit["commit"]["tree"]["sha"]
        if not SHA.fullmatch(revision) or not SHA.fullmatch(tree_sha):
            raise GitHubError("GitHub returned an unsupported revision.")
        tree = await api(http, f"/repos/{repo}/git/trees/{tree_sha}", {"recursive": "1"})
        files = [
            entry for entry in tree["tree"]
            if entry.get("type") == "blob" and entry.get("mode") in {"100644", "100755"}
        ]
        paths = {entry["path"] for entry in files}
        eligible = [entry for entry in files if source_path(entry["path"])]
        small = sorted(
            (entry for entry in eligible if 0 < entry.get("size", 0) <= FILE_BYTES),
            key=lambda entry: (not test_path(entry["path"]), entry["path"].count("/"), entry["path"]),
        )
        semaphore = asyncio.Semaphore(4)

        async def fetch(entry):
            async with semaphore:
                try:
                    return entry["path"], await read_source(http, repo, revision, entry["path"])
                except (GitHubError, httpx.HTTPError):
                    return entry["path"], None

        sources = {
            path: data for path, data in await asyncio.gather(*(fetch(entry) for entry in small[:MAX_FILES]))
            if data is not None
        }
        context_names = {"readme", "readme.md", "readme.rst", "package.json", "pyproject.toml", "requirements.txt"}
        context_files = sorted(
            (entry for entry in files if entry["path"].rsplit("/", 1)[-1].lower() in context_names
             and 0 < entry.get("size", 0) <= FILE_BYTES),
            key=lambda entry: (entry["path"].count("/"), entry["path"]),
        )[:6]
        metadata_files = {
            path: data for path, data in await asyncio.gather(*(fetch(entry) for entry in context_files))
            if data is not None
        }
        configs = sorted(path for path in paths if path.rsplit("/", 1)[-1] == "tsconfig.json")[:4]
        aliases = {}
        for path in configs:
            try:
                raw_config = await read_source(http, repo, revision, path)
                compiler = json.loads(raw_config).get("compilerOptions", {})
                base = compiler.get("baseUrl", ".")
                path_map = compiler.get("paths", {})
                if isinstance(base, str) and isinstance(path_map, dict):
                    aliases[path] = {"base": base, "paths": path_map}
            except (GitHubError, httpx.HTTPError, ValueError, AttributeError):
                continue
        history, history_available = await repository_history(
            http, repo, branch, revision, commit["commit"].get("committer", {}).get("date"), files, fetch,
        )

    return {
        "repo": repo, "branch": branch, "revision": revision, "description": (info.get("description") or "")[:300],
        "language": info.get("language"), "paths": paths, "sources": sources, "eligible": len(eligible),
        "total_files": len(files), "truncated": bool(tree.get("truncated")),
        "history": sorted(history, key=lambda item: item["date"] or "", reverse=True),
        "history_available": history_available, "aliases": aliases, "metadata_files": metadata_files,
    }


async def public_repositories(login, page):
    if not NAME.fullmatch(login):
        return []
    async with client() as http:
        payload = await api(http, "/users/" + login + "/repos",
                            {"per_page": 30, "page": page, "sort": "updated", "type": "owner"}, limit=600_000)
    return [
        {"name": item["full_name"], "description": item.get("description"), "language": item.get("language")}
        for item in payload if item.get("private") is False
    ]

CONTRIBUTION_LANGUAGES = ("Python", "JavaScript", "TypeScript", "Java", "Go", "Rust", "C++", "Ruby")
CONTRIBUTION_LABELS = ("good first issue", "help wanted")


async def contribution_issues(language, label, page):
    query = (
        f'is:issue is:open is:public is:unlocked no:assignee archived:false language:"{language}" '
        f'label:"{label}"'
    )
    async with client() as http:
        result = await api(http, "/search/issues", {
            "q": query, "sort": "updated", "order": "desc", "per_page": 12, "page": page,
        }, limit=1_500_000)
    items = []
    for item in result["items"]:
        repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
        try:
            repo = repo_name(repo)
        except GitHubError:
            continue
        number = int(item["number"])
        items.append({
            "repo": repo, "number": number, "title": item["title"][:240],
            "summary": (item.get("body") or "")[:400], "updated": item.get("updated_at"),
            "url": f"https://github.com/{repo}/issues/{number}",
        })
    return {"items": items, "partial": result.get("incomplete_results", False),
            "more": page < 10 and result.get("total_count", 0) > page * 12}


async def repository_history(http, repo, branch, revision, cutoff, files, fetch):
    base = f"/repos/{repo}"

    async def get(path, **params):
        try:
            return await api(http, base + path, params, limit=1_500_000)
        except (GitHubError, httpx.HTTPError, ValueError):
            return None

    def github_record(item, kind, number, title, link, **extra):
        actor = (item.get("user") or item.get("author") or {}).get("login")
        return {"id": f"{kind}-{number}", "kind": kind, "label": f"{kind.upper()} #{number}",
                "title": title[:240], "body": (item.get("body") or "")[:1500],
                "date": item.get("created_at"), "actor": actor, "url": link, **extra}

    pulls, issues, commits = await asyncio.gather(
        get("/pulls", state="closed", base=branch, per_page=12),
        get("/issues", state="all", per_page=15),
        get("/commits", sha=revision, per_page=12),
    )
    history = []
    for item in pulls or []:
        number = item["number"]
        link = f"https://github.com/{repo}/pull/{number}"
        history.append(github_record(item, "pr", number, item["title"], link, merged=item.get("merged_at"),
                                     date_override=item.get("merged_at"), merge_sha=item.get("merge_commit_sha")))
    for item in issues or []:
        if "pull_request" not in item:
            number = item["number"]
            history.append(github_record(item, "issue", number, item["title"],
                                         f"https://github.com/{repo}/issues/{number}"))
    for item in commits or []:
        sha = item["sha"]
        if not SHA.fullmatch(sha):
            continue
        title, _, message = item["commit"]["message"].partition("\n")
        history.append({
            "id": f"commit-{sha}", "label": f"Commit {sha[:7]}", "kind": "commit",
            "title": title[:240], "body": message.strip()[:1500], "actor": (item.get("author") or {}).get("login"),
            "date": item["commit"]["committer"]["date"], "url": f"https://github.com/{repo}/commit/{sha}",
        })
    candidates = [row for row in history if row["kind"] == "pr" and row["merged"]
                  and (not cutoff or row["merged"] <= cutoff)][:3]
    for row in candidates:
        number = row["id"].split("-")[1]
        changed, comments = await asyncio.gather(
            get(f"/pulls/{number}/files", per_page=30), get(f"/issues/{number}/comments", per_page=4),
        )
        row["paths"] = [item["filename"] for item in changed or []]
        row["renames"] = [[item["previous_filename"], item["filename"]] for item in changed or []
                          if item.get("previous_filename")]
        for comment in comments or []:
            comment_row = github_record(comment, "comment", comment["id"], f"Discussion on {row['label']}",
                                        f"{row['url']}#issuecomment-{comment['id']}", parent=row["id"])
            history.append(comment_row)
    docs = sorted(
        (entry for entry in files if 0 < entry.get("size", 0) <= FILE_BYTES
         and re.search(r"(^|/)(adr|adrs|rfcs|decisions|design)(/|[._-])", entry["path"], re.IGNORECASE)
         and entry["path"].lower().endswith((".md", ".rst"))),
        key=lambda item: (item["path"].count("/"), item["path"]),
    )[:4]
    for path, content in await asyncio.gather(*(fetch(entry) for entry in docs)):
        if content:
            history.append({"id": "doc-" + path, "kind": "doc", "label": "Design document",
                            "title": path, "body": content[:1500], "date": None,
                            "url": source_href(repo, revision, path)})
    if cutoff:
        history = [row for row in history if
                   (row.get("merged") or row.get("date") or "") <= cutoff]
    for row in history:
        row["date"] = row.pop("date_override", None) or row["date"]
    available = bool(history) or any(batch is not None for batch in (pulls, issues, commits))
    return sorted(history, key=lambda row: row["date"] or "", reverse=True), available


async def contribution_activity(login):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login):
        raise GitHubError("The connected GitHub login could not be verified.")
    async with client() as http:
        batches = await asyncio.gather(*(
            api(http, "/search/issues", {
                "q": f"author:{login} is:public is:{kind}", "sort": "updated", "per_page": 15,
            }, limit=1_500_000)
            for kind in ("pr", "issue")
        ))
    items = []
    prefix = "https://api.github.com/repos/"
    for batch in batches:
        for item in batch["items"]:
            if not item["repository_url"].startswith(prefix) or (item.get("user") or {}).get("login", "").lower() != login.lower():
                continue
            try:
                repo = repo_name(item["repository_url"].removeprefix(prefix))
            except GitHubError:
                continue
            number = int(item["number"])
            pull = item.get("pull_request")
            state = "open" if item["state"] == "open" else "closed"
            if pull is not None and pull.get("merged_at"):
                state = "merged"
            kind = state + (" pull request" if pull is not None else " issue")
            path = "pull" if pull is not None else "issues"
            items.append({"repo": repo, "title": item["title"][:240], "kind": kind, "draft": item.get("draft", False),
                          "date": item["updated_at"], "url": f"https://github.com/{repo}/{path}/{number}"})
    return {"items": sorted(items, key=lambda item: item["date"], reverse=True),
            "partial": any(batch.get("incomplete_results") or batch["total_count"] > 15 for batch in batches)}
