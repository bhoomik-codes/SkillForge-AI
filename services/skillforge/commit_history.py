"""Cache public GitHub records without storing workspace or account data."""

import asyncio

import httpx
from neo4j.exceptions import DriverError, Neo4jError

from . import github
from .db import transaction
from .scoring import PRIVATE_KEY

MAX_PATHS = 4
MAX_COMMITS = 5

READ = """
MATCH (file:SkillForgePublicHistory {key: $key})
OPTIONAL MATCH (file)-[link:HAS_COMMIT]->(commit:SkillForgePublicCommit)
WITH file, commit, link ORDER BY link.position
RETURN collect(CASE WHEN commit IS NOT NULL THEN commit {.sha, .message} END) AS commits, file.key AS key
"""
WRITE = """
MERGE (file:SkillForgePublicHistory {key: $key})
SET file.repository = $repo, file.revision = $revision, file.path = $path
WITH file
UNWIND $commits AS entry
MERGE (commit:SkillForgePublicCommit {key: entry.key})
SET commit.sha = entry.sha, commit.message = entry.message
MERGE (file)-[link:HAS_COMMIT]->(commit)
SET link.position = entry.position
"""


def query(statement, parameters, *, write=False):
    with transaction(write=write) as tx:
        result = tx.run(statement, parameters)
        if write:
            result.consume()
            return None
        row = result.single()
        return row["commits"] if row and row["key"] == parameters["key"] else None


def valid_commits(commits):
    return (isinstance(commits, list) and len(commits) <= MAX_COMMITS
            and all(isinstance(row, dict) and isinstance(row.get("sha"), str)
                    and github.SHA.fullmatch(row["sha"])
                    and isinstance(row.get("message"), str) and 0 < len(row["message"]) <= 600
                    and not PRIVATE_KEY.search(row["message"]) for row in commits))


async def file_history(git, repo, revision, path):
    key = f"{repo}:{revision}:{path}"
    try:
        commits = await asyncio.to_thread(query, READ, {"key": key})
        if valid_commits(commits):
            return {"source": "neo4j", "commits": commits}
    except (DriverError, Neo4jError):
        pass

    try:
        records = await github.api(
            git, f"/repos/{repo}/commits",
            {"sha": revision, "path": path, "per_page": MAX_COMMITS}, limit=350_000,
        )
        if not isinstance(records, list):
            raise TypeError("Invalid GitHub commit list.")
        commits = []
        for row in records[:MAX_COMMITS]:
            message = row["commit"]["message"]
            if isinstance(message, str) and not PRIVATE_KEY.search(message):
                entry = {"sha": row["sha"], "message": message.strip()[:600]}
                if valid_commits([entry]):
                    commits.append(entry)
    except (github.GitHubError, httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"source": "unavailable", "commits": []}

    try:
        await asyncio.to_thread(query, WRITE, {
            "key": key, "repo": repo, "revision": revision, "path": path,
            "commits": [{**entry, "key": f"{repo}:{entry['sha']}", "position": index}
                        for index, entry in enumerate(commits)],
        }, write=True)
    except (DriverError, Neo4jError):
        pass
    return {"source": "github", "commits": commits}


async def retrieve(snapshot, paths):
    """Called only from a consented scan after the importer confirms public visibility."""
    revision = snapshot["revision"]
    if not github.SHA.fullmatch(revision):
        return {}
    repo = snapshot["repo"]
    selected = [path for path in dict.fromkeys(paths) if path in snapshot["sources"]][:MAX_PATHS]
    async with github.client() as git:
        histories = await asyncio.gather(
            *(file_history(git, repo, revision, path) for path in selected)
        )
    return dict(zip(selected, histories, strict=True))
