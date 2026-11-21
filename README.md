# SkillForge

**Find out why the code works this way.** SkillForge turns public GitHub history into a Neo4j knowledge graph. Ask about a behavior, pull request, file, or line of code and inspect the issues, discussions, commits, and diffs that support the answer.

[Open the hosted workspace](https://skillforge-integrated.onrender.com/) · [Judging packet](docs/JUDGING_PACKET.md) · [Deployment and demo guide](docs/OPERATIONS.md)

## Try the Futon demo

Open the shared **AppFuton/Futon** repository. On a fresh deployment, wait for **Stored in Neo4j** while the worker prepares the demo. GitHub sign-in is optional.

| Demo prompt | What to look for |
| --- | --- |
| **Trace the migration fix** | Issue #127, the fix in PR #138, and its reference to PR #137. |
| **Find an overridden decision** | PR #112 introduced the chapter-update wait preference. PR #146 removed it and made waiting the default. The trail links both diffs. |
| **Try an unanswered question** | The assistant reports that the indexed evidence does not establish a rationale. |

Open **Inspect stored graph** to explore related records. After asking a question, expand **View executed Neo4j queries** to see the Cypher used for retrieval. The [demo walkthrough](docs/OPERATIONS.md#judges-demo) shows how to inspect the shared graph in Neo4j Browser.

## How it works

1. Paste a public GitHub URL or use the GitHub picker. The worker pins the default branch revision and indexes PRs, issues, commits, comments, and available discussions. The workspace reports history that could not be indexed within provider or coverage limits.
2. Ask a question or attach a path and line. SkillForge retrieves a multi-hop trail from Neo4j, quotes the evidence, and links each citation to GitHub. Personal imports can fetch additional evidence for a path or issue number.
3. Explore the interactive code map, adaptive scorecard, and comparable rankings. Find open source issues, prepare a contribution roadmap, or practice scenario-based coding exercises.

Neo4j also stores sessions, scan jobs, results, practice attempts, and career profiles. Static code analysis covers JavaScript, TypeScript, and Python. History retrieval and pinned source links work for other languages, including Futon's Kotlin files.

## Run locally

Install **Node.js 22.12+** and **uv**. Start Docker for the launcher's local Neo4j container, or configure a development Neo4j instance. The launcher prepares Python 3.12, builds the frontend, checks the API and database, and opens the app.

- **Windows PowerShell** — `.\Run-SkillForge.bat`
- **macOS Terminal** — `./Run-SkillForge.command`. If needed, restore execution with `chmod +x Run-SkillForge.command`.

The default port is **8765**. Both launchers accept `--port`, `--no-browser`, `--reinstall`, and `--check`. The startup check uses a disposable Neo4j container and requires Docker. See the [local setup guide](docs/OPERATIONS.md#local-development) for running the frontend and API separately.

## Configuration

Use [.env.example](.env.example) as a template for an ignored `.env`. The launchers also read overrides from `.env.local`. Set deployed values in Render's Environment tab.

| Settings | Enables |
| --- | --- |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Connect to Neo4j. Use a TLS address for hosted deployments, such as Aura's `neo4j+s://` URI. |
| `GITHUB_API_TOKEN` | Higher public indexing quota and Discussions access with an appropriately scoped token. Recommended for preparing the first shared demo. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_CALLBACK_URL` | GitHub sign-in and the public repository picker. Register the exact callback URL for your origin. |
| `SARVAM_API_KEY` | **Dictate with Sarvam** fills the question box with editable text. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional AI evidence selection and source review after consent. Quoted evidence retrieval also works without Gemini. |
| `JUDGE_URL`, `JUDGE_TOKEN` | Isolated execution and grading for practice. When the evaluator is unconfigured, the catalog and editor remain available. |
| `HISTORY_PAGE_LIMIT`, `SCAN_WORKER_ENABLED` | Import coverage and embedded worker settings. An active worker prepares the shared demo and processes new imports. |

## Deploy and verify

The [Render Blueprint](render.yaml) builds the Docker image from `main` and serves the web app and API at the same HTTPS origin. Configure the Neo4j connection and use `/api/health` as the health check. The default Render command applies the database schema at startup.

A healthy API response verifies database connectivity. To verify that the deployment includes the decision assistant, open the homepage in a private window, wait for **Stored in Neo4j**, and run the three Futon prompts. A first deployment must finish indexing before this flow is ready. If the homepage still shows an older workspace, verify the deployed commit in Render and deploy the latest `main`.

GitHub Actions runs the production frontend build, graph tests, dependency audit, backend lint, and backend tests against a disposable Neo4j instance. To run the same checks locally, see [service tests](docs/OPERATIONS.md#service-tests) and the frontend commands below.

```sh
cd apps/web
npm ci
npm run build
node --experimental-strip-types --test tests/graphView.test.mjs
npm audit --omit=dev
```

## Project documents

- [Product requirements](docs/PRD.md) and [build plan](docs/BUILD_PLAN.md)
- [Environment reference](docs/ENVIRONMENT.md) and [operations guide](docs/OPERATIONS.md)
- [Adaptive scorecard and ranking rules](docs/SCORING.md)
- [Source review and feature inventory](docs/SOURCE_INVENTORY.md)
- [Judging packet and remediation log](docs/JUDGING_PACKET.md)
- [Repository agent instructions](AGENTS.md)
