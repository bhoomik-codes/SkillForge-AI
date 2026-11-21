
import asyncio
import logging
import secrets

from .analysis import structure
from .db import encode, entity, expire_guests, now, transaction
from .demo import ensure_demo
from .github import GitHubError, get_snapshot, source_href
from .knowledge import fetch_graph, store_graph
from .scoring import quality

logger = logging.getLogger(__name__)
LEASE_SECONDS = 360


def compile_snapshot(snapshot):
    graph, parsed = structure(snapshot)
    return {
        "repo": snapshot["repo"], "branch": snapshot["branch"], "revision": snapshot["revision"],
        "description": snapshot["description"], "language": snapshot["language"], "graph": graph,
        "quality": quality(snapshot, parsed), "history": snapshot["history"],
        "history_available": snapshot["history_available"], "preview_paths": sorted(snapshot["sources"]),
        "sample": snapshot["revision"] == "sample",
    }


def claim():
    timestamp = now()
    lease = secrets.token_hex(24)
    with transaction(write=True) as tx:
        pending = tx.run("""
            RETURN EXISTS { MATCH (:SFScan {state: 'queued'}) } OR EXISTS {
                MATCH (s:SFScan {state: 'running'}) WHERE s.updated < $cutoff
            } AS pending
            """, cutoff=timestamp - LEASE_SECONDS).single()["pending"]
        if not pending:
            return None
        tx.run("""
            MATCH (store:SFStore {id: 'skillforge'})
            SET store.queueVersion = store.queueVersion + 1
            """).consume()
        tx.run("""
            MATCH (s:SFScan {state: 'running'}) WHERE s.updated < $cutoff
            WITH s ORDER BY s.updated LIMIT 100
            SET s.lock = coalesce(s.lock, 0) + 1
            WITH s WHERE s.state = 'running' AND s.updated < $cutoff
            SET s.state = 'queued', s.lease = null, s.updated = $now
            """, cutoff=timestamp - LEASE_SECONDS, now=timestamp).consume()
        row = tx.run("""
            MATCH (s:SFScan {state: 'queued'})
            WITH s ORDER BY s.created, s.id LIMIT 1
            SET s.lock = coalesce(s.lock, 0) + 1
            SET s.state = 'running', s.lease = $lease, s.updated = $now
            RETURN s AS node
            """, lease=lease, now=timestamp).single()
        return (entity(row), lease) if row else None


def finish(scan_id, lease, state, result):
    with transaction(write=True) as tx:
        tx.run("""
            MATCH (s:SFScan {id: $id})
            SET s.lock = coalesce(s.lock, 0) + 1
            WITH s WHERE s.lease = $lease AND s.state = 'running'
            SET s.state = $state, s.result = $result, s.lease = null, s.updated = $now
            """, id=scan_id, lease=lease, state=state, result=encode(result), now=now()).consume()


async def run_scans():
    last_cleanup = 0
    while True:
        try:
            if now() - last_cleanup > 60:
                await asyncio.to_thread(expire_guests)
                await asyncio.to_thread(ensure_demo)
                last_cleanup = now()
            claimed = await asyncio.to_thread(claim)
            if claimed:
                await perform(*claimed)
                continue
        except Exception as exc:  # noqa: BLE001 - Keep the queue alive and omit untrusted exception content.
            logger.error("Scan worker iteration failed (%s).", type(exc).__name__)
        await asyncio.sleep(1.25)


async def perform(scan, lease):
    async def index(http, repo, revision, info):
        async with asyncio.timeout(155):
            records, edges, gaps = await fetch_graph(http, repo, revision, info)
        await asyncio.to_thread(store_graph, scan["id"], lease, revision, records, edges, gaps)

    try:
        async with asyncio.timeout(240):
            snapshot = await get_snapshot(scan["repo"], on_revision=index)
            payload = await asyncio.to_thread(compile_snapshot, snapshot)
            if scan["options"].get("ai"):
                from .review import review
                payload["review"] = await review(snapshot, payload["quality"])
        await asyncio.to_thread(finish, scan["id"], lease, "review", payload)
    except GitHubError as exc:
        await asyncio.to_thread(finish, scan["id"], lease, "failed", {"error": str(exc), "retryAt": exc.retry_at})
    except Exception as exc:  # noqa: BLE001 - Finish the job without exposing provider or repository content.
        logger.warning("Repository scan did not complete (%s).", type(exc).__name__)
        await asyncio.to_thread(finish, scan["id"], lease, "failed", {"error": "Analysis was interrupted. Try again."})


def source_for(result, path, line=None):
    if result.get("sample"):
        return None
    return source_href(result["repo"], result["revision"], path, line)
