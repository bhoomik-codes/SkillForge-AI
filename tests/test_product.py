
import asyncio
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

# The product suite uses a dedicated local Neo4j instance with authentication disabled.
os.environ["NEO4J_URI"] = "bolt://127.0.0.1:17687"
os.environ["NEO4J_DATABASE"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = ""
os.environ["APP_ENV"] = "test"
os.environ["SCAN_WORKER_ENABLED"] = "false"
os.environ["JUDGE_URL"] = ""
os.environ["JUDGE_TOKEN"] = ""

from skillforge import config, knowledge, sarvam, trail_answer
from skillforge.db import close, now, provision, session, transaction
from skillforge.decision_context import explain
from skillforge.judge import matches
from skillforge.main import app
from skillforge.migrate import migrate
from skillforge.problem_scoring import assess_submission, best_assessments, developer_index, next_problem
from skillforge.problems import PROBLEMS
from skillforge.sample import SNAPSHOT
from skillforge.scanning import LEASE_SECONDS, claim, compile_snapshot, finish, perform
from skillforge.scoring import finalize

ORIGIN = {"Origin": config.ORIGIN}


def repo_fixture(source, description="", truncated=False):
    return {**SNAPSHOT, "repo": "tester/project", "revision": "b" * 40, "description": description,
            "sources": source, "paths": set(source) | {"README.md", "package.json", "package-lock.json"},
            "eligible": len(source), "total_files": len(source) + 3, "truncated": truncated}


READER = repo_fixture({"reader.tsx": """export function Reader() {
const [readingProgress, setProgress] = useState(0);
localStorage.setItem('bookmark', String(readingProgress));
return <main><button onClick={() => setProgress(1)}>Go to bookmark</button></main>;
}"""}, "An offline ebook reader")


def setUpModule():
    migrate()
    with transaction() as tx:
        count = tx.run("MATCH (n) WHERE n:SFWorkspace OR n:SFSession OR n:SFScan OR n:SFAttempt OR n:SFProfile "
                       "RETURN count(n) AS count").single()["count"]
    if count:
        raise RuntimeError("Start a fresh disposable Neo4j instance on port 17687 before running this suite.")


def tearDownModule():
    try:
        with transaction(write=True) as tx:
            tx.run("MATCH (n) WHERE n:SFWorkspace OR n:SFSession OR n:SFScan OR n:SFAttempt OR n:SFProfile "
                   "DELETE n").consume()
    finally:
        close()


class GraphAndScoreTests(unittest.TestCase):
    def test_static_sample_has_function_and_package_edges(self):
        payload = compile_snapshot(SNAPSHOT)
        edges = {(row["source"], row["target"], row["kind"]) for row in payload["graph"]["edges"]}
        self.assertIn(("src/dispatch.ts", "package:zustand", "imports package"), edges)
        self.assertIn(("src/dispatch.ts::dispatch", "src/planner.ts::rankStops", "calls · inferred"), edges)
        self.assertTrue(payload["quality"]["rankable"])
        self.assertEqual(payload["quality"], compile_snapshot(SNAPSHOT)["quality"])

    def test_alias_edges_are_pinned_to_the_import_and_call_sites(self):
        sources = {"src/app.ts": "import { greet as hello } from '@/greet';\nexport function run(){hello();}\n",
                   "src/greet.ts": "export function greet() { return 'hi' }\n"}
        snapshot = {**SNAPSHOT, "sources": sources, "paths": set(sources), "eligible": 2,
                    "aliases": {"tsconfig.json": {"base": ".", "paths": {"@/*": ["src/*"]}}}}
        payload = compile_snapshot(snapshot)
        edges = {(row["kind"], row["source"], row["target"], row["line"]) for row in payload["graph"]["edges"]}
        self.assertIn(("imports file", "src/app.ts", "src/greet.ts", 1), edges)
        self.assertIn(("calls · inferred", "src/app.ts::run", "src/greet.ts::greet", 2), edges)
        self.assertFalse(compile_snapshot({**snapshot, "eligible": 20})["quality"]["rankable"])

    def test_later_commit_can_override_a_named_setting_without_referencing_the_old_commit(self):
        rows = [
            {"id": "commit-old", "kind": "commit", "date": "2026-09-20",
             "title": "Set RETRY_LIMIT to 5", "body": "Set RETRY_LIMIT to 5 to reduce transient failures."},
            {"id": "commit-new", "kind": "commit", "date": "2026-10-20",
             "title": "Lower RETRY_LIMIT to 3", "body": "Lower RETRY_LIMIT to 3 to avoid long request delays."},
        ]
        snapshot = {**compile_snapshot(SNAPSHOT), "history": rows}
        query = "Why lower RETRY_LIMIT?"
        answer = asyncio.run(explain(snapshot, query, None, None))
        self.assertIn("avoid long request delays", answer["answer"])
        old = next(item for item in answer["evidence"] if item["record"]["id"] == "commit-old")
        self.assertEqual(old["supersededBy"][0]["basis"], "Later recorded change to RETRY_LIMIT from 5 to 3")

    def test_boolean_answers_cannot_be_replaced_with_integers(self):
        self.assertTrue(matches([True, 4.0], [True, 4]))
        self.assertFalse(matches([1, 4], [True, 4]))

    def test_offline_reader_excludes_account_concepts_but_detects_storage(self):
        report = compile_snapshot(READER)["quality"]
        criteria = {item["id"]: item for item in report["criteria"]}
        self.assertEqual(report["archetype"], "Reader app")
        self.assertEqual(report["scale"], 1000)
        self.assertEqual(criteria["auth"]["relevance"], "not_applicable")
        self.assertEqual(criteria["storage"]["relevance"], "applicable")
        self.assertEqual(criteria["storage"]["evidence"]["line"], 3)
        self.assertIn("Reading progress", [item["name"] for item in report["features"]])
        claimed = finalize(report, expected=["auth"])
        self.assertEqual(report["score"], claimed["score"])
        self.assertLess(claimed["evaluationCoverage"], report["evaluationCoverage"])
        self.assertFalse(claimed["rankable"])
        self.assertEqual(next(item["relevance"] for item in claimed["criteria"] if item["id"] == "auth"), "uncertain")

    def test_backend_saas_keeps_auth_and_permissions_distinct(self):
        source = {"server.py": """from fastapi import FastAPI
app = FastAPI()
db = create_engine('sqlite://')

@app.get('/account')
def account():
    return require_user()
"""}
        report = compile_snapshot(repo_fixture(source))["quality"]
        self.assertEqual(report["archetype"], "Backend SaaS")
        auth = next(item for item in report["criteria"] if item["id"] == "auth")
        self.assertEqual(auth["checks"][0]["line"], 7)
        self.assertIsNone(auth["checks"][1]["rate"])

    def test_normalization_excludes_unmeasured_and_unrelated_weights(self):
        def criterion(key, weight, rate, relevance="applicable", severity=None):
            return {"id": key, "name": key, "relevance": relevance, "proposedWeight": weight,
                    "checks": [] if relevance != "applicable" else [
                        {"id": key, "dimension": key, "rate": rate, "severity": severity},
                    ]}

        report = {"archetype": "Fixture", "coverage": {"analyzed": 8, "percent": 100, "truncated": False},
                  "criteria": [criterion("a", 400, 100), criterion("b", 400, 70),
                               criterion("excluded", 200, None, "not_applicable")]}
        normalized = finalize(report)
        self.assertEqual(normalized["score"], 850)
        self.assertEqual(normalized["grade"], "A")
        self.assertEqual(normalized["evaluationCoverage"], 100)
        report["criteria"].append(criterion("critical", 25, 0, severity="critical"))
        self.assertEqual(finalize(report)["score"], 699)
        report["criteria"][1]["checks"][0]["rate"] = None
        self.assertLess(finalize(report)["evaluationCoverage"], 70)
        self.assertFalse(finalize(report)["rankable"])

    def test_assessments_and_developer_index_use_separate_scales(self):
        results = [{"category": category, "status": outcome} for category, outcome in [
            ("Example", "passed"), ("Functional", "passed"), ("Edge case", "passed"),
            ("Boundary case", "wrong_answer"), ("Large input", "time_limit"),
        ]]
        partial = assess_submission(results, "python", "def solve(data):\n    return data\n")
        self.assertEqual(partial["points"], 58)
        self.assertEqual(partial["measured"], 85)
        self.assertIsNone(partial["criteria"][-1]["points"])
        high = {**partial, "normalized": 900}
        rows = [{"problem": "load-monitor", "result": {"assessment": score}} for score in [partial, high]]
        best = best_assessments(rows)
        self.assertEqual(len(best), 1)
        self.assertEqual(developer_index(800, best)["index"], 840)
        self.assertIsNone(developer_index(800, {})["index"])
        self.assertIsNone(developer_index(None, best)["index"])
        first_three = dict.fromkeys(["warehouse-reconciliation", "earliest-duplicate", "load-monitor"], high)
        self.assertEqual(next_problem(first_three, PROBLEMS)["difficulty"], "Intermediate")


class WorkspaceTests(unittest.TestCase):
    def test_production_headers_apply_to_success_and_rejected_requests(self):
        with TestClient(app) as client, patch.object(config, "PRODUCTION", True):
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            rejected = client.post("/api/scans", json={"repository": "owner/repo"})
            self.assertEqual(rejected.status_code, 403)
            for response in (health, rejected):
                self.assertEqual(response.headers["strict-transport-security"], "max-age=63072000; includeSubDomains")
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertEqual(response.headers["cross-origin-resource-policy"], "same-origin")
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIn("default-src 'none'", response.headers["content-security-policy"])

    def test_public_metadata_matches_the_configured_origin(self):
        origin = "https://skillforge.example"
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / "index.html").write_text("<html><head><!-- public-page-urls --></head></html>", encoding="utf-8")
            card = config.ROOT / "apps" / "web" / "public" / "share-card.png"
            (dist / "share-card.png").write_bytes(card.read_bytes())
            with TestClient(app) as client, patch.object(config, "ORIGIN", origin), patch("skillforge.main.DIST", dist):
                html = client.get("/").text
                self.assertIn(f'<link rel="canonical" href="{origin}/">', html)
                self.assertIn(f'<meta property="og:image" content="{origin}/share-card.png">', html)
                self.assertIn(f"Sitemap: {origin}/sitemap.xml", client.get("/robots.txt").text)
                self.assertIn(f"<loc>{origin}/</loc>", client.get("/sitemap.xml").text)
                self.assertTrue(client.get("/share-card.png").content.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(client.head("/robots.txt").status_code, 200)

    def test_scan_publishes_a_score_only_after_rubric_approval(self):
        with TestClient(app) as owner, TestClient(app) as other:
            owner.get("/api/session").raise_for_status()
            other.get("/api/session").raise_for_status()
            job = owner.post("/api/scans", json={"repository": "tester/project"}, headers=ORIGIN).json()
            with patch("skillforge.scanning.get_snapshot", return_value=READER):
                asyncio.run(perform(*claim()))
            route = "/api/scans/" + job["id"]
            draft = owner.get(route).json()
            self.assertEqual(draft["state"], "review")
            self.assertNotIn("summary", draft)
            self.assertIsNone(draft["result"]["quality"]["score"])
            self.assertNotIn("checks", draft["result"]["quality"]["criteria"][0])
            self.assertEqual(other.post(route + "/rubric", json={}, headers=ORIGIN).status_code, 404)
            self.assertEqual(owner.post(route + "/rubric", json={"expected": ["storage"]},
                                        headers=ORIGIN).status_code, 422)
            complete = owner.post(route + "/rubric", json={"expected": ["auth"], "note": "Expect sync"},
                                  headers=ORIGIN).json()
            self.assertEqual(complete["state"], "complete")
            self.assertEqual(complete["summary"]["scale"], 1000)
            self.assertFalse(complete["summary"]["rankable"])
            self.assertEqual(complete["result"]["quality"]["review"]["note"], "Expect sync")

    def test_queue_is_origin_and_owner_scoped(self):
        with TestClient(app) as owner, TestClient(app) as other:
            owner.get("/api/session").raise_for_status()
            other.get("/api/session").raise_for_status()
            self.assertEqual(owner.post("/api/scans", json={"repository": "owner/repo"}).status_code, 403)
            self.assertEqual(owner.post("/api/scans", json={"repository": "https://example.org/a/b"},
                                        headers=ORIGIN).status_code, 422)
            payload = {"repository": "github.com/owner/repo"}
            job = owner.post("/api/scans", json=payload, headers=ORIGIN)
            self.assertEqual(job.status_code, 202)
            key = job.json()["id"]
            self.assertEqual(owner.post("/api/scans", json=payload, headers=ORIGIN).json()["id"], key)
            self.assertEqual(other.get("/api/scans/" + key).status_code, 404)
            self.assertEqual(other.get("/api/scans").json(), [])
            owner.delete("/api/account", headers=ORIGIN).raise_for_status()
            self.assertEqual(owner.get("/api/scans/" + key).status_code, 404)

    def test_workers_claim_once_and_stale_leases_cannot_finish(self):
        with TestClient(app) as client:
            client.get("/api/session").raise_for_status()
            job = client.post("/api/scans", json={"repository": "owner/lease"}, headers=ORIGIN)
            key = job.raise_for_status().json()["id"]
            with ThreadPoolExecutor(max_workers=2) as workers:
                claims = list(workers.map(lambda _: claim(), range(2)))
            self.assertEqual(sum(result is not None for result in claims), 1)
            first, old_lease = next(result for result in claims if result)
            self.assertEqual(first["id"], key)
            with transaction(write=True) as tx:
                tx.run("MATCH (s:SFScan {id: $id}) SET s.updated = $expired",
                       id=key, expired=now() - LEASE_SECONDS - 1).consume()
            current, lease = claim()
            self.assertEqual(current["id"], key)
            self.assertNotEqual(lease, old_lease)
            finish(key, old_lease, "failed", {"error": "stale"})
            self.assertEqual(client.get("/api/scans/" + key).json()["state"], "running")
            finish(key, lease, "failed", {"error": "current"})
            self.assertEqual(client.get("/api/scans/" + key).json()["result"], {"error": "current"})

    def test_neo4j_sessions_and_practice_attempts_survive_driver_restart(self):
        from skillforge.practice import finish_attempt, reserve_attempt

        token = provision()
        owner = session(token)["owner"]
        key = "fixture-attempt"
        reserve_attempt(owner, token, key, "warehouse-reconciliation")
        finish_attempt(owner, key, {"passed": 1, "total": 2})
        close()
        with TestClient(app) as client:
            client.cookies.set(config.COOKIE, token)
            self.assertEqual(client.get("/api/practice/attempts").raise_for_status().json()[0]["id"], key)
            self.assertEqual(client.get("/api/practice/attempts").json()[0]["passed"], 1)
            client.delete("/api/account", headers=ORIGIN).raise_for_status()
        self.assertIsNone(session(token))

    def test_public_catalog_does_not_disclose_hidden_cases(self):
        with TestClient(app) as client:
            catalog = client.get("/api/practice/problems").json()
            self.assertEqual(len(catalog), 12)
            self.assertTrue(all("hidden" not in item and "walkthrough" not in item for item in catalog))
            client.get("/api/session").raise_for_status()
            denied = client.post("/api/practice/submit", headers=ORIGIN, json={
                "problem": "warehouse-reconciliation", "language": "python", "code": "print('{}')",
            })
            self.assertEqual(denied.status_code, 503)
            self.assertEqual(client.get("/api/practice/attempts").json(), [])

    def test_actions_require_explicit_approval_and_export(self):
        with TestClient(app) as client:
            client.get("/api/session").raise_for_status()
            client.put("/api/career/target", headers=ORIGIN, json={
                "role": "Frontend developer", "hours": 7, "description": "We prefer Python and testing.",
            }).raise_for_status()
            proposed = client.post("/api/career/actions", headers=ORIGIN, json={"skill": "Python"}).json()
            key = proposed["profile"]["actions"][0]["id"]
            route = "/api/career/actions/" + key
            self.assertEqual(client.patch(route, headers=ORIGIN, json={"state": "completed"}).status_code, 409)
            client.patch(route, headers=ORIGIN, json={"state": "approved"}).raise_for_status()
            completed = client.patch(route, headers=ORIGIN, json={"state": "completed"}).json()
            self.assertIn("Python", completed["planned"])
            self.assertTrue(client.get("/api/career/report.pdf").content.startswith(b"%PDF-1.4"))

    def test_decision_context_traces_supersession_and_abstains(self):
        with TestClient(app) as client:
            client.get("/api/session").raise_for_status()
            route = "/api/sample/context"
            query = {"question": "Why sort routes by zone before dispatch?", "path": "src/planner.ts"}
            current = client.post(route, headers=ORIGIN, json=query).raise_for_status().json()
            self.assertEqual(current["confidence"], "moderate")
            self.assertIn("zone boundaries", current["answer"])
            decision = current["evidence"][0]
            self.assertEqual(decision["entities"], ["src/planner.ts"])
            self.assertEqual(decision["actors"], ["sample-maintainer"])
            self.assertIn("comment-4", {row["id"] for row in decision["related"]})
            old = next(item for item in current["evidence"] if item["record"]["id"] == "pr-8")
            self.assertEqual([row["id"] for row in old["supersededBy"]], ["pr-14"])
            earlier = client.post(route, headers=ORIGIN, json={
                **query, "question": "Why sort routes by arrival time?", "through": "2026-10-21",
            }).raise_for_status().json()
            self.assertIn("late deliveries", earlier["answer"])
            self.assertEqual(earlier["evidence"][0]["supersededBy"], [])
            unknown = client.post(route, headers=ORIGIN, json={
                "question": "Why is the retry threshold ninety?", "path": "src/planner.ts",
            }).raise_for_status().json()
            self.assertIsNone(unknown["answer"])
            self.assertEqual(unknown["confidence"], "insufficient")
            with transaction() as tx:
                before = tx.run("MATCH (q:SkillForgeQuestion) RETURN count(q)").single()[0]
            graph = client.post(route, headers=ORIGIN, json={**query, "neo4j": True}).raise_for_status().json()
            self.assertEqual(graph, {**current, "mode": "neo4j"})
            with transaction() as tx:
                self.assertEqual(tx.run("MATCH (q:SkillForgeQuestion) RETURN count(q)").single()[0], before)
            with patch("skillforge.decision_context.neo4j_paths", side_effect=ServiceUnavailable):
                fallback = client.post(route, headers=ORIGIN, json={**query, "neo4j": True}).json()
            self.assertEqual(fallback, {**current, "mode": "fallback"})

    def test_contribution_search_and_context_require_a_workspace(self):
        with TestClient(app) as owner, TestClient(app) as other:
            discovery = "/api/contributions?language=Python&label=good%20first%20issue"
            self.assertEqual(owner.get(discovery).status_code, 401)
            owner.get("/api/session").raise_for_status()
            other.get("/api/session").raise_for_status()
            payload = {"items": [{"repo": "example/project", "number": 12}], "partial": True, "more": False}
            with patch("skillforge.main.contribution_issues", return_value=payload) as github:
                self.assertEqual(owner.get(discovery).raise_for_status().json(), payload)
                github.assert_awaited_once_with("Python", "good first issue", 1)
                self.assertEqual(owner.get(discovery.replace("Python", "unsupported")).status_code, 422)
            result = owner.post("/api/scans", json={"repository": "example/project"}, headers=ORIGIN)
            route = f"/api/scans/{result.raise_for_status().json()['id']}/context"
            self.assertEqual(other.post(route, json={"question": "Why?"}, headers=ORIGIN).status_code, 404)
            self.assertEqual(owner.post(route, json={"question": "Why?"}, headers=ORIGIN).status_code, 409)
            owner.delete(route.removesuffix("/context"), headers=ORIGIN).raise_for_status()

    def test_contribution_roadmap_progress_and_public_activity_are_owner_scoped(self):
        route = "/api/career/contribution-roadmap"
        token = provision("github:93844", "fixture-contributor")
        with TestClient(app) as owner, TestClient(app) as other:
            owner.cookies.set(config.COOKIE, token)
            other.get("/api/session").raise_for_status()
            initial = owner.get(route).raise_for_status().json()
            self.assertEqual(len(initial["projects"]), 3)
            project = initial["projects"][0]
            task = project["tasks"][0]
            changed = owner.put(route, headers=ORIGIN, json={
                "project": project["id"], "task": task["id"], "completed": True,
            }).raise_for_status().json()
            self.assertEqual(changed["selected"], project["id"])
            self.assertEqual(changed["projects"][0]["completed"], [task["id"]])
            self.assertEqual(changed["steps"][0]["title"], project["tasks"][1]["title"])
            self.assertEqual(owner.get(route).json(), changed)
            self.assertIsNone(other.get(route).json()["selected"])
            self.assertEqual(other.post(route + "/github", headers=ORIGIN).status_code, 403)

            citation = {"repo": "example/project", "kind": "merged pull request", "title": "Improve project docs",
                        "draft": False, "date": "2026-11-20T00:00:00Z", "url": "https://github.com/example/project/pull/3"}
            with patch("skillforge.career.contribution_activity", return_value={"items": [citation], "partial": False}) as fetch:
                refreshed = owner.post(route + "/github", headers=ORIGIN).raise_for_status().json()
                fetch.assert_awaited_once_with("fixture-contributor")
            self.assertEqual(refreshed["steps"][0]["citation"], citation)
            self.assertIsNone(other.get(route).json()["activity"])
            removed = owner.delete(route + "/github", headers=ORIGIN).raise_for_status().json()
            self.assertIsNone(removed["activity"])
            self.assertEqual(removed["projects"][0]["completed"], [task["id"]])


class KnowledgeGraphTests(unittest.TestCase):
    def test_repository_with_no_supported_source_remains_unranked(self):
        unsupported = {**READER, "sources": {}, "paths": {"app/src/test/kotlin/ReaderTest.kt"}, "eligible": 0}
        payload = compile_snapshot(unsupported)
        self.assertFalse(payload["quality"]["rankable"])
        self.assertIsNone(payload["quality"]["score"])


    def test_import_persists_and_traces_a_followup_through_neo4j(self):
        original = {"number": 8, "title": "Reader controls obscure navigation",
                    "body": "The reader controls obscure navigation."}
        first_fix = {"number": 12, "title": "Move controls to the dock", "body": "Fixes #8"}
        followup = {"number": 20, "title": "Dock contrast regression",
                    "body": "Regression from #12. The dock label is hard to read."}
        second_fix = {"number": 31, "title": "Improve dock contrast",
                      "body": "Fixes #20. We use a lighter dock label to avoid unreadable contrast."}
        repo = READER["repo"]
        nodes = [knowledge.numbered(record, kind, repo) for record, kind in [
            (original, "issue"), (first_fix, "pr"), (followup, "issue"), (second_fix, "pr"),
        ]]
        edges = knowledge.relationships(repo, nodes, [], [])

        async def load_fixture(repository, *, on_revision):
            await on_revision(None, repository, READER["revision"], {})
            return READER

        with TestClient(app) as owner, TestClient(app) as other:
            owner.get("/api/session").raise_for_status()
            other.get("/api/session").raise_for_status()
            job = owner.post("/api/scans", json={"repository": repo}, headers=ORIGIN).raise_for_status().json()
            url = "/api/scans/" + job["id"] + "/knowledge"
            self.assertIsNone(owner.get(url).json()["revision"])
            with patch("skillforge.scanning.get_snapshot", side_effect=load_fixture), patch(
                "skillforge.scanning.fetch_graph", return_value=(nodes, edges, ["discussions"]),
            ):
                asyncio.run(perform(*claim()))
            status = owner.get(url).raise_for_status().json()
            self.assertEqual((status["records"], status["edges"]), (4, 3))
            self.assertEqual(status["gaps"], ["discussions"])
            self.assertEqual(other.get(url).status_code, 404)
            preview = owner.get(url + "/preview").raise_for_status().json()
            self.assertEqual(len(preview["nodes"]), 4)
            with patch("skillforge.main.enrich", return_value=([], "")):
                answer = owner.post(url + "/ask", headers=ORIGIN, json={
                    "question": "Why was dock contrast changed in #31?",
                }).raise_for_status().json()
            self.assertEqual({node["id"] for node in answer["graph"]["nodes"]},
                             {"issue:8", "pr:12", "issue:20", "pr:31"})
            self.assertTrue(any("lighter dock label" in item["quote"] for item in answer["evidence"]))
            self.assertIn("REPORTS_REGRESSION_FROM", {edge["kind"] for edge in answer["graph"]["edges"]})
            owner.delete("/api/account", headers=ORIGIN).raise_for_status()
            with transaction() as tx:
                self.assertEqual(tx.run("MATCH (r:SFKnowledgeRecord {scan: $scan}) RETURN count(r)",
                                        scan=job["id"]).single()[0], 0)

    def test_ai_cannot_introduce_an_unretrieved_quote(self):
        question = "Why was dock contrast changed?"
        quote = "We use a lighter dock label to avoid unreadable contrast."
        graph = {"nodes": [{"id": "pr:31", "kind": "pr", "title": "Improve dock contrast", "body": quote}]}
        response = {"candidates": [{"content": {"parts": [{"text": "[99]"}]}}]}
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
        with patch.object(trail_answer, "enabled", return_value=True), patch.object(
            trail_answer.httpx, "AsyncClient", return_value=client,
        ):
            answer = asyncio.run(trail_answer.select_evidence(question, graph, True))
        self.assertEqual(answer, {"mode": "retrieved", "evidence": [{"record": "pr:31", "quote": quote}]})
        unknown = asyncio.run(trail_answer.select_evidence("Why are retries limited?", graph, False))
        self.assertEqual(unknown, {"mode": "abstained", "evidence": []})

    def test_sarvam_transcription_uses_documented_endpoint(self):
        def provider(request):
            self.assertEqual(str(request.url), "https://api.sarvam.ai/speech-to-text")
            self.assertEqual(request.headers["api-subscription-key"], "fixture")
            self.assertIn(b"saaras:v4", request.content)
            return httpx.Response(200, json={"transcript": "Why did the dock change?"})

        with TestClient(app) as client:
            client.get("/api/session").raise_for_status()
            with patch.object(config, "SARVAM_API_KEY", "fixture"), patch.object(
                sarvam.httpx, "AsyncClient", return_value=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
            ):
                result = client.post("/api/transcribe", content=b"audio fixture",
                                     headers={**ORIGIN, "Content-Type": "audio/webm"})
            self.assertEqual(result.raise_for_status().json(), {"text": "Why did the dock change?"})
