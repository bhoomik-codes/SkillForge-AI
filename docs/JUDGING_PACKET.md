# SkillForge judging packet

## Demo story

A new engineer joins a team and can read the current code, but needs the reasoning behind it before changing it. SkillForge builds a Neo4j graph of public GitHub history, retrieves a decision trail, and cites the original records. The engineer can then find a first contribution and plan the work.

| Judge action | Evidence to show |
| --- | --- |
| Open the workspace in a private browser window | The shared AppFuton/Futon graph is already indexed and works without a GitHub login. |
| Trace the migration fix | Issue #127, PR #138 and the reference to PR #137. |
| Find an overridden decision | PR #112 introduced the chapter-update preference. PR #146 removed it and made waiting the default. Open both diffs. |
| Try an unanswered question | The assistant abstains when the repository history provides no support. |
| Open the query and the database | Show executed Cypher in the answer, then use the Neo4j Browser query in the operations guide. |

[Futon issue #127](https://github.com/AppFuton/Futon/issues/127) · [PR #138](https://github.com/AppFuton/Futon/pull/138) · [PR #137](https://github.com/AppFuton/Futon/pull/137) · [PR #112](https://github.com/AppFuton/Futon/pull/112) · [PR #146](https://github.com/AppFuton/Futon/pull/146) · [Operations guide](OPERATIONS.md#judges-demo)

## Persona use-case matrix

| Persona | Problem | Use case | Product evidence |
| --- | --- | --- | --- |
| New engineer at an Indian product startup | Can read a code path and needs its decision history | Ask about a setting or line. Locate the author and supporting PR or issue. | Source-linked decision graph and typed or dictated questions. |
| Student or first-time contributor | Needs a project and a first useful task | Find a good first issue, plan a contribution and practice with examples. | Issue browser, contribution roadmap and exercise catalog. Live execution requires a configured judge. |
| Engineering manager or tech lead | Wants decisions to outlast the people who made them | Review past tradeoffs during handover and examine repository health. | Decision evidence, history draft export and scorecards. Customer adoption remains untested. |

New use cases can query the same model of issues, PRs, commits, discussions and evidence relationships. For example, handover can ask which decisions replaced earlier ones, and onboarding can ask which PRs explain a file.

## Market fit canvas

| Area | Working hypothesis |
| --- | --- |
| User and buyer | New developers at Indian product startups with 10–100 engineers. The engineering manager sponsors team adoption. |
| Current workflow | Search GitHub and Slack, inspect Git history and ask a teammate. |
| Value to test | Reduce time spent reconstructing decisions and help new engineers ship a first meaningful change sooner. Measure time to find a cited answer, then measure time to first merged PR in a pilot. |
| Pricing hypothesis | ₹400 per developer per month. Test with engineering managers before claiming willingness to pay. |
| Market context | Nasscom estimated 5.8 million employees in the Indian technology industry for FY2025. This is workforce context. The number of target companies, eligible seats and willingness to pay remain unmeasured. |
| Alternatives | Copilot and Cody offer codebase Q&A. DeepWiki generates repository documentation. Greptile focuses on code review. Swimm offers code documentation. SkillForge's pitch is a database-backed trail for a specific historical decision, including citations and verified overrides. |
| Recruitment | Reach coding clubs and first-time open source contributors for usability feedback. Recruit five startup engineering managers separately to test buying intent. |

[Nasscom FY2025 Strategic Review press release](https://www.nasscom.in/sites/default/files/media_pdf/Nasscom%20SR%20Press%20release.pdf) · [GitHub Copilot](https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/chat-with-copilot/chat-in-ide) · [Sourcegraph Cody](https://sourcegraph.com/docs/cody) · [DeepWiki](https://docs.devin.ai/work-with-devin/deepwiki) · [Greptile documentation](https://www.greptile.com/docs) · [Swimm](https://swimm.io/)

## Three customer tests

Recruit three developers who joined a new team within the past year. Show the live Futon demo only after hearing how they handled the problem on their last team.

1. How did you find out why a particular part of the code worked the way it did? Tell me about the last time you did this.
2. How long did it take to get your first meaningful PR merged? What slowed it down?
3. After trying the demo, which onboarding task would you actually use this for? Who would decide whether your team pays?

| Interview | Assumption | Observation | Product change |
| --- | --- | --- | --- |
| 1 | Engineers regularly need historical rationale. | Pending real interview. | Pending. |
| 2 | Searching history delays a first meaningful PR. | Pending real interview. | Pending. |
| 3 | An engineering manager would sponsor team adoption. | Pending real interview. | Pending. |

## ArgosX remediation log

| Report | Status | Attachment |
| --- | --- | --- |
| Baseline | Awaiting actual report. Record the original report timestamp and score. | Pending. |
| Final | Run against the deployed revision. Record its timestamp and score. | Pending. |

| Finding | Severity | Fixed | Evidence or reason |
| --- | --- | --- | --- |
| Populate from the baseline ArgosX report. | Pending. | Pending. | Link the matching fix, final finding or documented reason. |

A passive check of the current live deployment on 22 November 2026 (IST) returned healthy status, the canonical link and Open Graph image, and HTTP 200 for robots.txt and sitemap.xml. The homepage included HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Permissions-Policy. Attach the ArgosX reports separately to document ArgosX findings and scores.

Use the original vendor reports for submission. Match each baseline finding with the final report, then count fixed findings and list any remaining findings with a reason. Keep the original scan timestamp if the baseline was late.

## Judging-day checks

- Verify the public deployment in a private window. Open the three Futon questions and confirm the expected evidence from the deployed build.
- Open the public site shortly before the judging slot and wait for the health check and seeded demo to respond. Render free web services can spin down after inactivity.
- Take the final ArgosX report from the deployed revision and keep both report files available.
- Confirm the microphone and Sarvam credentials on the device used for the demo. Typed questions use the same evidence workflow.

[Render free service behavior](https://render.com/docs/free#spinning-down-on-idle) · [ArgosX public scan](https://getargosx.com/scan)
