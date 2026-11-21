
# Adaptive scoring

The [shared product discussion](https://chatgpt.com/share/6b0166f4-1ad4-83ee-b336-deb9ce88359f) defines the distinction between repository quality, problem-solving ability, and the combined Developer Index. The scoring rules below serve R10 and R11.

## Repository Intelligence

1. The worker reads a commit-pinned, bounded source sample and selected README and dependency manifests. Source signals identify project type and capabilities. The first rubric version covers reader apps, frontend apps, backend APIs, backend SaaS, full-stack apps, CLIs, ML and data projects, and general software. Source and dependencies can support the classification. A README claim alone can make a capability uncertain.
2. The API presents a review before publishing the numeric score. The rubric identifies applicable, not applicable, and uncertain criteria and includes source references where available. For example, an offline reader with bookmarks can be evaluated for local persistence without including account security. Repository owners can flag an excluded capability as expected or record a challenge. Such requests retain the measured criteria and leave the report unranked until reviewed or rescanned with sufficient evidence.
3. The server assigns versioned project weights. Relevant criteria can be added beyond the archetype's baseline. The 1,000-point score is the sum of measured weights multiplied by each achieved proportion, divided by the sum of their measured weights, then multiplied by 1,000 and rounded to the nearest integer. For example, 680 weighted points out of 800 measured points become 850/1,000. Not-applicable criteria are excluded. Uncertain criteria and unmeasured checks lower evaluation coverage separately.
4. Reports label measured weight, source coverage, and static confidence. A score requires at least 35% of the relevant weight measured. Rankings additionally require at least 70% evaluated weight, 75% eligible source coverage, a complete tree and no unresolved project-owner challenge. Rankings and revision deltas use the same language cohort, project archetype, rubric version and measured check weights. Older 100-point scores remain readable in separate comparison groups.
5. Grades begin at 900 for S, 800 for A, 700 for B, 600 for C and 400 for D. Scores below 400 are E. This grade summarizes the evaluated evidence. For this version a detected private-key block in sampled non-fixture source caps the score at 699. Evidence reports include the location only. The check does not establish that the key is active or detect every secret or vulnerability.

Static scores cover the signals the app can support with evidence. Repository tests, feature behavior, accessibility conformance, security enforcement and performance benchmarks remain unverified by this pipeline. An opt-in Gemini review can add contextual observations tied to matching static evidence. The provider cannot change weights, scores, relevance or ranking eligibility.

For R4 and R10, the opt-in review uses commit messages scoped to the reviewed files and pinned
revision. It retrieves them through Neo4j before the model runs, with a GitHub fallback. The model
is instructed to omit already-fixed problems and identify current defects only when the excerpt
supports them. Every visible review item must quote its cited current line. A documented decision
also needs an exact quote from an available commit for that path. The scorecard links both sources.
Versioned static checks still determine deductions from current source, so historical findings,
model output, and provider outages leave the numeric score reproducible.

## Scenario-based assessments

| Criterion | Maximum | Evidence |
| --- | ---: | --- |
| Functional correctness | 40 | Public example and hidden functional case |
| Efficiency signal | 20 | Correct output on the large case within its evaluator budget |
| Edge cases | 15 | Hidden edge and boundary cases |
| Static code quality | 10 | Syntax and bounded source-size heuristics |
| Problem-solving explanation | 15 | Unmeasured until qualitative review is available |

The UI shows the measured points and states which points remain unmeasured. The efficiency signal represents the large test and its time limit. It does not measure asymptotic complexity. The Practice page recommends work at the current difficulty and advances after at least three distinct exercises at that level earn at least 80% of the measured points. Public examples and legacy attempts do not contribute to the new problem-solving score.

The Problem-Solving score normalizes each best scored attempt to 1,000 over its measured criteria, then averages those scores across distinct exercises. The Developer Index is 60% engineering and 40% problem solving. Engineering uses the latest eligible scan for a repository owned by the connected GitHub account. GitHub ownership indicates which project can be used for the index. Individual contributions may still require portfolio evidence. The combined value is withheld when either component is missing and labeled provisional while qualitative evidence or assessment breadth is incomplete.

The API and evaluator must run the same problem catalog version. Verify the live evaluator in staging using the [operations guide](OPERATIONS.md).
