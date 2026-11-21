"""Enrich a stored trail with GitHub evidence scoped to a question's file and issue numbers."""

import asyncio
import re

import httpx

from . import github
from .db import workspace_write
from .knowledge import MENTION, comment, commit, numbered, relationships


async def get(http, path, params=None):
    try:
        return await github.api(http, path, params, limit=2_000_000)
    except (github.GitHubError, httpx.HTTPError, ValueError):
        return None


async def file_records(http, repo, revision, path, line):
    base = "/repos/" + repo
    commits, source = await asyncio.gather(
        get(http, base + "/commits", {"sha": revision, "path": path, "per_page": 8}),
        read_line(http, repo, revision, path, line) if line else asyncio.sleep(0, result=""),
    )
    if not isinstance(commits, list) or not commits:
        return [], [], ""
    file_id = "file:" + path
    file_url = github.source_href(repo, revision, path)
    nodes = [{"id": file_id, "kind": "file", "title": path, "body": "", "path": path,
              "date": "", "author": "", "url": file_url}]
    edges = []
    changes = [commit(item, repo) for item in commits[:8]]
    pr_lists = await asyncio.gather(*(get(http, base + "/commits/" + item["sha"] + "/pulls", {"per_page": 5})
                                     for item in changes[:4]))
    nodes.extend(changes)
    for item in changes:
        edges.append(edge(item["id"], file_id, "CHANGES_FILE", f"GitHub file history for {path}", item["url"]))
    for item, pulls in zip(changes[:4], pr_lists, strict=True):
        for pull in pulls or []:
            # GitHub may report pull requests in forks too. Only index this repository.
            if (((pull.get("base") or {}).get("repo") or {}).get("full_name") or "").lower() != repo:
                continue
            pr = numbered(pull, "pr", repo)
            nodes.append(pr)
            edges.append(edge(item["id"], pr["id"], "ASSOCIATED_WITH", "GitHub commit association", pr["url"]))
    return nodes, edges, source


async def read_line(http, repo, revision, path, line):
    try:
        rows = (await github.read_source(http, repo, revision, path)).splitlines()
        return rows[line - 1].strip()[:240] if line <= len(rows) else ""
    except (github.GitHubError, httpx.HTTPError):
        return ""


def edge(source, target, kind, evidence, url):
    return {"source": source, "target": target, "kind": kind, "evidence": evidence, "url": url}


async def timeline_records(http, repo, number):
    base = "/repos/" + repo + "/issues/"
    issue, timeline = await asyncio.gather(
        get(http, base + str(number)), get(http, base + str(number) + "/timeline", {"per_page": 50}),
    )
    if not issue or not isinstance(timeline, list):
        return [], []
    main = numbered(issue, "pr" if issue.get("pull_request") else "issue", repo)
    nodes, edges = [main], []
    for event in timeline:
        if (main["kind"] == "pr" and event.get("event") == "reviewed" and event.get("body")
                and (record := comment(event, main, repo, "review"))):
            nodes.append(record)
        if event.get("event") == "cross-referenced":
            source = (event.get("source") or {}).get("issue") or {}
            url = source.get("repository_url", "").lower()
            if url != "https://api.github.com/repos/" + repo:
                continue
            record = numbered(source, "pr" if source.get("pull_request") else "issue", repo)
            nodes.append(record)
            edges.append(edge(record["id"], main["id"], "CROSS_REFERENCED",
                              "GitHub recorded this cross-reference in the timeline", main["url"]))
        if event.get("event") == "closed" and re.fullmatch(r"[a-f0-9]{40}", event.get("commit_id") or ""):
            sha = event["commit_id"]
            href = event.get("commit_url") or ""
            if href.lower() != f"https://api.github.com/repos/{repo}/commits/{sha}":
                continue
            detail = await get(http, "/repos/" + repo + "/commits/" + sha)
            if detail:
                record = commit(detail, repo)
                nodes.append(record)
                edges.append(edge(record["id"], main["id"], "CLOSED", "GitHub issue close event", main["url"]))
    return nodes, edges


def save_anchors(owner, token, scan, revision, records, edges):
    with workspace_write(owner, token) as tx:
        locked = tx.run("""
            MATCH (s:SFScan {owner: $owner, id: $scan})
            SET s.lock = coalesce(s.lock, 0) + 1
            WITH s WHERE s.knowledgeRevision = $revision
            RETURN s.repo AS repo
            """, owner=owner, scan=scan, revision=revision).single()
        if not locked:
            return
        tx.run("""
            MATCH (s:SFScan {owner: $owner, id: $scan})
            UNWIND $records AS props
            MERGE (r:SFKnowledgeRecord {scan: $scan, id: props.id})
            ON CREATE SET r += props, r.repo = s.repo
            MERGE (s)-[:SF_HAS_EVIDENCE]->(r)
            """, owner=owner, scan=scan, records=records).consume()
        tx.run("""
            UNWIND $edges AS edge
            MATCH (a:SFKnowledgeRecord {scan: $scan, id: edge.source}),
                  (b:SFKnowledgeRecord {scan: $scan, id: edge.target})
            MERGE (a)-[r:SF_EVIDENCE_LINK {kind: edge.kind}]->(b)
            ON CREATE SET r.evidence = edge.evidence, r.url = edge.url
            """, scan=scan, edges=edges).consume()
        tx.run("""
            MATCH (s:SFScan {id: $scan})
            SET s.knowledgeRecords = COUNT { (s)-[:SF_HAS_EVIDENCE]->() },
                s.knowledgeEdges = COUNT {
                    MATCH (s)-[:SF_HAS_EVIDENCE]->()-[:SF_EVIDENCE_LINK]->()
                }
            """, scan=scan).consume()


async def enrich(owner, token, scan, state, question, path, line):
    repo, revision = state["repo"], state["revision"]
    numbers = list(dict.fromkeys(
        int(match[4]) for match in MENTION.finditer(question)
        if (match[2] or match[3] or repo).lower() == repo and "/discussions/" not in (match[1] or "")
    ))[:3]
    if not numbers and not path:
        return [], ""
    try:
        async with asyncio.timeout(15), github.client() as http:
            info = await get(http, "/repos/" + repo)
            if not info or info.get("private") or info.get("visibility") != "public":
                return [], ""
            results = await asyncio.gather(*(timeline_records(http, repo, number) for number in numbers),
                                           file_records(http, repo, revision, path, line) if path
                                           else asyncio.sleep(0, result=([], [], "")))
    except (TimeoutError, TypeError, ValueError, KeyError):
        return [], ""
    files, file_edges, source = results[-1]
    records = {node["id"]: node for node in files}
    edges = list(file_edges)
    for nodes, links in results[:-1]:
        records.update((node["id"], node) for node in nodes)
        edges.extend(links)
    if records:
        edges.extend(relationships(repo, list(records.values()), [], []))
        await asyncio.to_thread(save_anchors, owner, token, scan, revision, list(records.values()), edges)
    return [files[0]["id"]] if files else [], source
