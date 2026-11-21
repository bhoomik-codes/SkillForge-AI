
# Running SkillForge

## Windows and macOS launchers

Double-click [Run-SkillForge.bat](../Run-SkillForge.bat) on Windows or [Run-SkillForge.command](../Run-SkillForge.command) on macOS. The launcher checks Node.js and npm, uses uv to prepare Python 3.12 and the locked API dependencies, and installs the locked web dependencies when needed. The first run may require internet access. It rebuilds the website, serves it with the API at a single loopback URL, and opens the browser after verifying the API, database and web build. Keep the terminal open while using the app and press Ctrl+C to stop it.

The launcher tries port 8765 first and then checks the next 19 ports. In PowerShell, run `.\Run-SkillForge.bat`; in macOS Terminal run `./Run-SkillForge.command`. Both accept `--port 8765` to require a specific port, `--no-browser` to print the URL only, `--check` to verify startup with a temporary database and stop, and `--reinstall` to repair web dependencies. If a download or file copy removed the macOS executable permission, restore it with `chmod +x Run-SkillForge.command`.

Start Docker before launching unless you have a development Neo4j instance. The launcher starts Neo4j on a loopback port and saves data in a Docker volume dedicated to this checkout. To use an existing development instance, copy `.env.example` to `.env.local` and set the Neo4j settings. The `--check` option always starts a disposable local container. If you use GitHub sign-in, pin the port and register the callback printed by the launcher. Practice submissions need a compatible isolated evaluator.

## Local development

Use Node 22.12 or later, Python 3.12 and uv. Install the locked frontend and backend dependencies from their respective directories. Start the API and web app in separate terminals.

Start a development Neo4j instance before starting the API. For example, run this in a separate terminal:

```sh
docker run --rm -p 127.0.0.1:7687:7687 -e NEO4J_AUTH=none neo4j:5.26.27-community
```

From `services`:

```sh
uv sync --locked
uv run --locked uvicorn skillforge.main:app --host 127.0.0.1 --port 8765 --no-access-log
```

From `apps/web`:

```sh
npm ci
npm run dev
```

Open [the local workspace](http://localhost:5173/). The shared Futon demo, public URL import, decision and code graphs, practice catalog and portfolio plan work without GitHub sign-in. The judge needs a separate service. The API connects to local Neo4j on port 7687 by default and hosts the scan worker. To serve a compiled web build directly from the API, run `npm run build` and set `APP_ORIGIN=http://127.0.0.1:8765` before starting the API.

For optional integrations, copy `.env.example` to an ignored `.env` at the repo root. From `services`, add `--env-file ../.env` to the `uv run` arguments.

## Staging deployment

The [Render Blueprint](../render.yaml) deploys the web service and connects to your existing Neo4j instance. On the SkillForge service, set `NEO4J_URI` to your Aura `neo4j+s://` URI and supply `NEO4J_USERNAME`, `NEO4J_PASSWORD` and `NEO4J_DATABASE` in Render's Environment tab. Render supplies the public HTTPS origin. For a manually created service, use the root Dockerfile's default command and set the health check path to `/api/health`. The default command initializes the SkillForge schema on Render and starts the scan worker.

For other production deployments:

1. Build the root Dockerfile. Serve the API and static web app at one HTTPS origin. Set `APP_ORIGIN` to that URL and use Neo4j over TLS. Apply a request size cap and per-IP limits for session creation and imports.
2. Run `python -m skillforge.migrate` with a credential that can create constraints and indexes. Use a separate runtime account where supported. Production startup checks the schema revision.
3. Deploy a worker using the same image and `python -m skillforge.worker` as its command. Start with one worker to limit shared GitHub quota. Scale after measuring queue age, throttling and upstream calls. Set `SCAN_WORKER_ENABLED=false` on the API when deploying a separate worker.
4. Configure separate GitHub OAuth credentials and the callback `/api/auth/github/callback` using the staging origin. The picker lists public repos owned by the connected account, and the service discards the OAuth token after profile lookup. An optional separate read-only API token raises public scan quotas.
5. Configure the judge on its own isolated Linux worker before enabling assessed submissions. Require private networking or authenticated TLS for the API-to-judge link. Keep cloud credentials, data volumes and database routes away from the evaluator host. Pre-pull vetted Python and Node images by digest and install an isolated container runtime such as gVisor. Use `python -m uvicorn skillforge.judge:app` on the judge host, with the Docker CLI available and a high-entropy service token. Pin its images with `JUDGE_PYTHON_IMAGE` and `JUDGE_JAVASCRIPT_IMAGE`. Point the web API at the judge using `JUDGE_URL` and the same `JUDGE_TOKEN`. Keep the judge service off public ingress.
6. If enabling optional Gemini findings, configure a supported model and a server-side key. A scan sends its bounded source excerpts only when the user opts in. The adaptive score remains based on measured checks. Deploy the API and evaluator with the same problem catalog version.
7. Verify GitHub OAuth, live scans, source references, durable recovery, Neo4j restore, provider timeouts, and the evaluator's limits and isolation before public rollout. Use separate staging data and values. Rebuild from an earlier image to roll back code only when the running schema supports it.

## Current release boundary

The implementation covers public GitHub import and opt-in connected selection, bounded static structure analysis for JavaScript, TypeScript and Python, adaptive repository scoring, practice scoring and portfolio planning. See [adaptive scoring](SCORING.md) for score interpretation and limits. Dynamic dispatch is outside static code graph coverage. The decision graph covers the public GitHub history indexed for that scan and shows incomplete source streams. The editor drafts stay in tab memory.

Neo4j stores the scan snapshot and its durable decision graph. Private repository access, Google and email sign-in, resume extraction, the full legacy career simulation suite, and legacy data migrations remain follow-up work. Keep the inherited inventory as a roadmap and confirm environment and provider choices before enabling those features.

## Judges’ demo

1. Start SkillForge. The worker prepares the shared, read-only GitHub import of `https://github.com/AppFuton/Futon`. Wait for **Stored in Neo4j** in **Ask why** and confirm it opens immediately in a private browser window before judging.
2. Select **Trace the migration fix**. Follow issue #127, the fix in PR #138 and the reference to PR #137. Open **View executed Neo4j queries** to show the recorded Cypher.
3. Select **Find an overridden decision** for PR #112 and PR #146. Then select **Try an unanswered question** to show the evidence boundary.
4. Set `SARVAM_API_KEY` before starting the app to demonstrate **Dictate with Sarvam**. Dictate, stop, review the transcript, and press **Ask**. Set `GEMINI_API_KEY` and `GEMINI_MODEL` to demonstrate model-assisted evidence selection after consent. Add a `GITHUB_API_TOKEN` authorized for public Discussions to include those in the graph.

To show the persisted graph in Neo4j Browser, run:

```cypher
MATCH (s:SFScan {repo: 'appfuton/futon'})
WHERE s.knowledgeRevision IS NOT NULL
WITH s ORDER BY s.created DESC LIMIT 1
MATCH (s)-[:SF_HAS_EVIDENCE]->(a:SFKnowledgeRecord)-[link:SF_EVIDENCE_LINK]->(b:SFKnowledgeRecord)
WHERE a.number IN [112, 127, 137, 138, 146] OR b.number IN [112, 127, 137, 138, 146]
RETURN a, link, b LIMIT 60
```

The import is a snapshot. A new import refreshes GitHub history. Owner deletion removes the scan and its evidence. Sarvam receives a short audio clip and returns editable text. The backend keeps the recording in memory for the request.

## Service tests

Start a disposable Neo4j instance bound to loopback port 17687, then run the API suite. The tests create and remove synthetic SkillForge data on that instance.

```sh
docker run --rm -p 127.0.0.1:17687:7687 -e NEO4J_AUTH=none neo4j:5.26.27-community
```

From `services`, run `uv run --locked python -m unittest discover -s ../tests -v` after Neo4j starts.

## Operational checks

Use `GET /api/health` for API liveness and current database connectivity. Monitor the oldest queued scan, failed scans by rate limits or provider outages, evaluator availability, and Neo4j backups. Keep access-log redaction at the reverse proxy and exclude HTTP bodies, cookies, credentials, and callback query values from logs.
