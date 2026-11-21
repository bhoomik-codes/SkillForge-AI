"""Index public GitHub evidence and retrieve an owner-scoped decision trail."""

import asyncio
import json
import re
from textwrap import dedent
from time import monotonic

import httpx

from . import config, github
from .db import transaction
from .decision_context import STOP, words
from .demo import DEMO_PREFERENCE_PRS, DEMO_REPO

PAGE_SIZE = 50
PAGE_LIMIT = config.HISTORY_PAGE_LIMIT
RECORD_LIMIT = 24
EDGE_LIMIT = 48
MENTION = re.compile(
    r"(?<![\w./-])(?:(https://github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues|discussions)/)"
    r"|([\w.-]+/[\w.-]+)#|#)(\d{1,10})\b", re.IGNORECASE,
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+(?:(?:PR|issue)\s+)?$", re.IGNORECASE)
REGRESSION = re.compile(r"\b(?:introduced by|caused by|regression from|broke in)\s+(?:(?:PR|issue)\s+)?$", re.IGNORECASE)
DISCUSSIONS = """
query($owner:String!,$name:String!,$after:String) {
 repository(owner:$owner,name:$name) {
  discussions(first:20,after:$after,orderBy:{field:UPDATED_AT,direction:DESC}) {
   pageInfo { hasNextPage endCursor }
   nodes { number title body createdAt url author { login }
     comments(first:5) { pageInfo { hasNextPage } nodes { databaseId body createdAt url author { login } } }
   }
  }
 }
}
"""


def text(value, size):
    return value.strip()[:size] if isinstance(value, str) else ""


def numbered(item, kind, repo):
    number = item["number"]
    if type(number) is not int or number < 1:
        raise ValueError("Invalid GitHub record number")
    category = {"pr": "pull", "issue": "issues", "discussion": "discussions"}[kind]
    return {"id": f"{kind}:{number}", "kind": kind, "number": number,
            "title": text(item.get("title"), 300), "body": text(item.get("body"), 4000),
            "date": item.get("created_at") or item.get("createdAt") or "",
            "author": (item.get("user") or item.get("author") or {}).get("login") or "",
            "url": f"https://github.com/{repo}/{category}/{number}",
            "state": "merged" if item.get("merged_at") else "draft" if item.get("draft") else str(item.get("state") or "")}


def commit(item, repo):
    sha = item["sha"]
    if not github.SHA.fullmatch(sha):
        raise ValueError("Invalid GitHub commit SHA")
    info = item["commit"]
    message = text(info.get("message"), 4000)
    return {"id": "commit:" + sha, "kind": "commit", "title": (message.splitlines() or [sha[:7]])[0][:300],
            "body": message, "date": (info.get("committer") or {}).get("date") or "",
            "author": (item.get("author") or {}).get("login") or "", "sha": sha,
            "url": f"https://github.com/{repo}/commit/{sha}"}


def comment(item, parent, repo, kind="comment"):
    identifier = item.get("id") if kind != "discussion comment" else item.get("databaseId")
    if type(identifier) is not int:
        return None
    anchor = {"comment": "issuecomment", "review comment": "discussion_r",
              "discussion comment": "discussioncomment", "review": "pullrequestreview"}[kind]
    return {"id": f"{kind}:{identifier}", "kind": kind, "title": f"{kind.capitalize()} on #{parent['number']}",
            "body": text(item.get("body"), 4000), "date": item.get("created_at") or item.get("createdAt") or "",
            "author": (item.get("user") or item.get("author") or {}).get("login") or "",
            "url": f"{parent['url']}#{anchor}-{identifier}", "parent": parent["id"],
            "path": text(item.get("path"), 400)}


async def pages(http, endpoint, **filters):
    rows = []
    deadline = monotonic() + 65
    for page in range(1, PAGE_LIMIT + 1):
        try:
            async with asyncio.timeout(max(0, deadline - monotonic())):
                batch = await github.api(http, endpoint, {**filters, "per_page": PAGE_SIZE, "page": page},
                                         limit=3_000_000)
        except (github.GitHubError, httpx.HTTPError, TimeoutError, ValueError):
            return rows, False
        if not isinstance(batch, list):
            return rows, False
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows, True
    return rows, False


async def discussions(http, repo, enabled):
    if not enabled:
        return [], True
    if not config.GITHUB_TOKEN:
        return [], False
    owner, name = repo.split("/")
    nodes, cursor, comments_complete = [], None, True
    deadline = monotonic() + 65
    for _ in range(PAGE_LIMIT):
        if monotonic() >= deadline:
            return nodes, False
        try:
            async with http.stream("POST", "https://api.github.com/graphql", headers=github.headers(),
                                   json={"query": DISCUSSIONS,
                                         "variables": {"owner": owner, "name": name, "after": cursor}}) as response:
                github.check_response(response)
                data = bytearray()
                async for chunk in response.aiter_bytes(16384):
                    data.extend(chunk)
                    if len(data) > 3_000_000:
                        return nodes, False
            connection = json.loads(data)["data"]["repository"]["discussions"]
            nodes.extend(connection["nodes"])
            comments_complete &= all(not item["comments"]["pageInfo"]["hasNextPage"] for item in connection["nodes"])
            if not connection["pageInfo"]["hasNextPage"]:
                return nodes, comments_complete
            cursor = connection["pageInfo"]["endCursor"]
        except (github.GitHubError, httpx.HTTPError, KeyError, TypeError, ValueError):
            return nodes, False
    return nodes, False


def relationships(repo, records, pulls, events):
    nodes = {record["id"]: record for record in records}
    numbers = {record["number"]: record["id"] for record in records
               if record["kind"] in {"pr", "issue"}}
    edges = {}

    def link(source, target, kind, evidence, url):
        if source in nodes and target in nodes and source != target:
            edges[(source, target, kind)] = {"source": source, "target": target, "kind": kind,
                                             "evidence": evidence, "url": url}

    for record in records:
        identifier = record["id"]
        if parent := record.get("parent"):
            link(parent, identifier, "HAS_COMMENT", record["title"], record["url"])
        for field in ("title", "body"):
            content = record[field]
            for match in list(MENTION.finditer(content))[:25]:
                if (remote := match[2] or match[3]) and remote.lower() != repo:
                    continue
                number = int(match[4])
                url = (match[1] or "").lower()
                target = (f"discussion:{number}" if "/discussions/" in url else
                          f"pr:{number}" if "/pull/" in url else
                          f"issue:{number}" if "/issues/" in url else numbers.get(number))
                prefix = content[max(0, match.start() - 40):match.start()]
                kind = "REFERENCES"
                if CLOSING.search(prefix) and record["kind"] in {"pr", "commit"}:
                    kind = "DECLARES_FIX"
                elif REGRESSION.search(prefix):
                    kind = "REPORTS_REGRESSION_FROM"
                quote = content[max(0, match.start() - 45):match.end() + 45].strip()
                link(identifier, target, kind, quote, record["url"])
    for item in pulls:
        if item.get("merged_at") and (sha := item.get("merge_commit_sha")):
            pr = f"pr:{item['number']}"
            link(pr, "commit:" + sha, "MERGED_AS", "GitHub merge commit", nodes[pr]["url"])
    for event in events:
        issue = event.get("issue") or {}
        if event.get("event") != "closed" or not event.get("commit_id"):
            continue
        target = numbers.get(issue.get("number"))
        source = "commit:" + event["commit_id"]
        if target in nodes:
            link(source, target, "CLOSED", "GitHub issue close event", nodes[target]["url"])
    return list(edges.values())


ANDROID_KEY = re.compile(r'^[+-]\s*android:key="([^"]+)"')


def preference_overrides(prs, changes, repo):
    """Link verified additions and later removals of the same preference on the same branch."""
    added = {}
    edges = []
    for pr in sorted(prs, key=lambda item: item.get("merged_at") or ""):
        if not pr.get("merged_at"):
            continue
        number = pr["number"]
        for file in changes.get(number, []):
            before, after = set(), set()
            for line in file.get("patch", "").splitlines():
                if match := ANDROID_KEY.match(line):
                    (after if line[0] == "+" else before).add(match[1])
            for key in sorted(before - after):
                identity = (pr["base"]["ref"], file["filename"], key)
                if previous := added.pop(identity, None):
                    edges.append({
                        "source": f"pr:{number}", "target": f"pr:{previous}", "kind": "SUPERSEDES",
                        "evidence": f"PR #{previous} added {key} in {file['filename']}. PR #{number} removed it.",
                        "url": f"https://github.com/{repo}/pull/{number}/files",
                    })
            for key in after - before:
                added[(pr["base"]["ref"], file["filename"], key)] = number
    return edges


async def fetch_graph(http, repo, revision, info):
    endpoint = f"/repos/{repo}"
    topics = ("issues", "pullRequests", "commits", "comments", "reviewComments", "events", "discussions")
    results = await asyncio.gather(
        pages(http, endpoint + "/issues", state="all", sort="updated"),
        pages(http, endpoint + "/pulls", state="all", sort="updated"),
        pages(http, endpoint + "/commits", sha=revision),
        pages(http, endpoint + "/issues/comments", sort="updated", direction="desc"),
        pages(http, endpoint + "/pulls/comments", sort="updated", direction="desc"),
        pages(http, endpoint + "/issues/events"),
        discussions(http, repo, info.get("has_discussions")),
    )
    (issues, pulls, commits, comments, reviews, events, threads) = [result[0] for result in results]
    records = {record["id"]: record for item in issues for record in [
        numbered(item, "pr" if item.get("pull_request") else "issue", repo),
    ]}
    for item in pulls:
        item = numbered(item, "pr", repo)
        records[item["id"]] = item
    for item in commits:
        item = commit(item, repo)
        records[item["id"]] = item
    for comments_batch, kind, field in [(comments, "comment", "issue_url"), (reviews, "review comment", "pull_request_url")]:
        for item in comments_batch:
            number = str(item.get(field, "")).rsplit("/", 1)[-1]
            parent = records.get("pr:" + number) or records.get("issue:" + number)
            if parent and (record := comment(item, parent, repo, kind)):
                records[record["id"]] = record
    for item in threads:
        parent = numbered(item, "discussion", repo)
        records[parent["id"]] = parent
        for reply in item["comments"]["nodes"]:
            if record := comment(reply, parent, repo, "discussion comment"):
                records[record["id"]] = record
    if not records and not any(result[1] for result in results[:3]):
        raise github.GitHubError("GitHub history could not be indexed. Try importing the repository again.")
    nodes = list(records.values())
    edges = relationships(repo, nodes, pulls, events)
    if repo == DEMO_REPO:
        diffs = await asyncio.gather(*(pages(http, f"{endpoint}/pulls/{number}/files")
                                       for number in DEMO_PREFERENCE_PRS))
        changes = {number: result[0] for number, result in zip(DEMO_PREFERENCE_PRS, diffs, strict=True)}
        edges.extend(preference_overrides(pulls, changes, repo))
    gaps = [topic for topic, result in zip(topics, results, strict=True) if not result[1]]
    if len(edges) > 30_000:
        gaps.append("relationships")
    return nodes, edges[:30_000], gaps


def remove_graph(tx, scan_id):
    tx.run("""
        MATCH (r:SFKnowledgeRecord {scan: $scan}) DETACH DELETE r
        """, scan=scan_id).consume()


def store_graph(scan_id, lease, revision, records, edges, gaps):
    with transaction(write=True, timeout=60) as tx:
        locked = tx.run("""
            MATCH (s:SFScan {id: $scan})
            SET s.lock = coalesce(s.lock, 0) + 1
            WITH s WHERE s.lease = $lease AND s.state = 'running'
            RETURN s.id
            """, scan=scan_id, lease=lease).single()
        if not locked:
            return
        remove_graph(tx, scan_id)
        for offset in range(0, len(records), 500):
            tx.run("""
                MATCH (s:SFScan {id: $scan})
                UNWIND $records AS props
                CREATE (r:SFKnowledgeRecord) SET r = props, r.scan = $scan, r.repo = s.repo
                CREATE (s)-[:SF_HAS_EVIDENCE]->(r)
                """, scan=scan_id, records=records[offset:offset + 500]).consume()
        for offset in range(0, len(edges), 1000):
            tx.run("""
                UNWIND $edges AS edge
                MATCH (a:SFKnowledgeRecord {scan: $scan, id: edge.source}),
                      (b:SFKnowledgeRecord {scan: $scan, id: edge.target})
                CREATE (a)-[r:SF_EVIDENCE_LINK]->(b)
                SET r.kind = edge.kind, r.evidence = edge.evidence, r.url = edge.url
                """, scan=scan_id, edges=edges[offset:offset + 1000]).consume()
        tx.run("""
            MATCH (s:SFScan {id: $scan})
            SET s.knowledgeRevision = $revision, s.knowledgeRecords = $count, s.knowledgeEdges = $edges,
                s.knowledgeGaps = $gaps
            """, scan=scan_id, revision=revision, count=len(records), edges=len(edges), gaps=gaps).consume()


def graph_status(owner, scan_id):
    with transaction() as tx:
        row = tx.run("""
            MATCH (s:SFScan {owner: $owner, id: $scan})
            RETURN s.repo AS repo, s.state AS scanState, s.knowledgeRevision AS revision,
                   s.knowledgeRecords AS records, s.knowledgeEdges AS edges, s.knowledgeGaps AS gaps
            """, owner=owner, scan=scan_id).single()
    return row.data() if row else None


TRAIL_SEED_QUERY = """
            MATCH (:SFScan {owner: $owner, id: $scan})-[:SF_HAS_EVIDENCE]->(r)
            WITH r, reduce(score = 0, term IN $terms |
                 score + CASE WHEN toLower(r.title) CONTAINS term THEN 3
                    WHEN toLower(r.body) CONTAINS term THEN 1 ELSE 0 END) +
                 CASE WHEN r.number IN $numbers OR r.id IN $anchors THEN 25 ELSE 0 END +
                 CASE WHEN any(p IN $paths WHERE toLower(coalesce(r.path, '')) = p
                          OR toLower(r.body) CONTAINS p) THEN 10 ELSE 0 END +
                 CASE WHEN $overview AND r.kind IN ['pr', 'issue', 'discussion'] THEN
                     1 + COUNT { (r)-[:SF_EVIDENCE_LINK]-() } ELSE 0 END AS score
            WHERE score > 0
            RETURN properties(r) AS node ORDER BY score DESC, r.date DESC, r.id LIMIT 5
            """

TRAIL_LINK_QUERY = """
                MATCH (r:SFKnowledgeRecord {scan: $scan})-[link:SF_EVIDENCE_LINK]-
                      (related:SFKnowledgeRecord {scan: $scan})
                WHERE r.id IN $frontier
                RETURN properties(related) AS node, startNode(link).id AS source, endNode(link).id AS target,
                       properties(link) AS link
                ORDER BY CASE link.kind WHEN 'SUPERSEDES' THEN 0 WHEN 'CLOSED' THEN 1 WHEN 'DECLARES_FIX' THEN 1
                         WHEN 'REPORTS_REGRESSION_FROM' THEN 2 WHEN 'CROSS_REFERENCED' THEN 3
                         WHEN 'REFERENCES' THEN 4 ELSE 5 END,
                         related.date DESC LIMIT $limit
                """


def trail(owner, scan_id, question, path=None, anchors=()):
    terms = sorted(words(question) - STOP)[:20]
    numbers = [int(match[4]) for match in MENTION.finditer(question)][:10]
    path_terms = [path.lower(), path.rsplit("/", 1)[-1].lower()] if path else []
    with transaction() as tx:
        seeds = tx.run(TRAIL_SEED_QUERY, owner=owner, scan=scan_id, terms=terms, numbers=numbers, anchors=list(anchors),
                       paths=path_terms, overview=not question).value("node")
        nodes = {node["id"]: node for node in seeds}
        seen_edges = {}
        frontier = list(nodes)
        traversals = 0
        for _ in range(4):
            if not frontier or len(nodes) >= RECORD_LIMIT:
                break
            rows = tx.run(TRAIL_LINK_QUERY, scan=scan_id, frontier=frontier, limit=EDGE_LIMIT).data()
            traversals += 1
            frontier = []
            for row in rows:
                node = row["node"]
                if node["id"] not in nodes and len(nodes) < RECORD_LIMIT:
                    nodes[node["id"]] = node
                    frontier.append(node["id"])
                edge = {"source": row["source"], "target": row["target"], **row["link"]}
                seen_edges[(edge["source"], edge["target"], edge["kind"])] = edge
    edges = [edge for edge in seen_edges.values() if edge["source"] in nodes and edge["target"] in nodes]
    queries = [{"label": "Find relevant records", "cypher": dedent(TRAIL_SEED_QUERY).strip(), "runs": 1}]
    if traversals:
        queries.append({"label": "Expand linked evidence", "cypher": dedent(TRAIL_LINK_QUERY).strip(), "runs": traversals})
    return {"nodes": list(nodes.values()), "edges": edges[:EDGE_LIMIT], "queries": queries}
