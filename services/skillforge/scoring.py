
"""Versioned scoring for bounded, inert repository snapshots."""

import re
from collections import Counter
from dataclasses import dataclass

from .github import source_href, test_path

RUBRIC = "project-aware-v1"
SCALE = 1000

LABELS = {
    "features": "Feature correctness", "code": "Code quality", "architecture": "Architecture",
    "tests": "Testing and reliability", "performance": "Performance", "dependencies": "Dependency hygiene",
    "docs": "Documentation", "ui": "UI and accessibility", "state": "State management",
    "api": "API design", "auth": "Authentication and authorization", "storage": "Persistence",
    "security": "Security", "network": "External network handling", "payments": "Payments",
    "cli": "Command-line interface", "ml": "Model evaluation",
}
OPTIONAL = ("ui", "state", "api", "auth", "storage", "security", "network", "payments", "cli", "ml")
WEIGHTS = {
    "Reader app": {"features": 250, "code": 200, "ui": 150, "state": 100, "performance": 100, "tests": 100,
                   "architecture": 100},
    "Frontend app": {"features": 220, "code": 170, "ui": 145, "state": 90, "tests": 120, "performance": 90,
                     "architecture": 100, "dependencies": 40, "docs": 25},
    "Backend SaaS": {"features": 200, "api": 150, "auth": 150, "storage": 125, "security": 125, "tests": 100,
                     "performance": 75, "architecture": 75},
    "Backend API": {"features": 175, "api": 160, "code": 135, "security": 110, "tests": 135, "architecture": 95,
                    "performance": 75, "dependencies": 70, "docs": 45},
    "Full-stack app": {"features": 160, "code": 115, "ui": 110, "api": 110, "security": 90, "tests": 125,
                       "architecture": 100, "performance": 75, "dependencies": 65, "docs": 50},
    "CLI": {"features": 210, "code": 165, "cli": 150, "tests": 150, "architecture": 105, "performance": 70,
            "dependencies": 75, "docs": 75},
    "ML or data project": {"features": 170, "code": 130, "ml": 180, "tests": 140, "architecture": 100,
                           "performance": 100, "dependencies": 100, "docs": 80},
    "General software": {"features": 175, "code": 200, "tests": 160, "architecture": 155,
                         "performance": 105, "dependencies": 105, "docs": 100},
}
EXTRA = {"ui": 130, "state": 80, "api": 140, "auth": 150, "storage": 125, "security": 125,
         "network": 75, "payments": 125, "cli": 140, "ml": 150}
SYNTAX_FILTER = {"tests", "test", "__tests__", "fixtures", "examples", "samples"}
MANIFESTS = {"package.json", "pyproject.toml", "requirements.txt", "pipfile"}
LOCKS = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "uv.lock", "poetry.lock", "pipfile.lock"}
PATTERNS = {
    "ui": r"<(?:main|html|body|div|article|button|a|section|View|Text)\b|(?:ReactDOM\.)?createRoot\s*\(|\bcreateApp\s*\(",
    "state": r"\b(?:useState|useReducer|createStore|writable|createSlice)\s*\(|\blocalStorage\.(?:getItem|setItem)\(",
    "api": r"@\w+\.(?:get|post|put|patch|delete|route)\(\s*['\"]/|"
           r"\b(?:app|router|server)\.(?:get|post|put|patch|delete|route)\(\s*['\"]/|\bFastAPI\s*\(",
    "auth": r"\b(?:requireAuth|requireLogin|requirePermission|authenticate|authorize|jwt_required|verify_token|"
            r"validate_session|require_user|useAuth|verifySession|login_required|current_user|signInWithEmail)\s*\("
            r"|(?:from|import)\s+['\"](?:next-auth|passport|@auth/[^'\"]+)",
    "permissions": r"\b(?:requirePermission|hasPermission|checkPermission|requireRole|hasRole|owner_of|"
                   r"check_owner|verify_owner)\s*\(",
    "storage": r"\b(?:localStorage|sessionStorage)\.(?:getItem|setItem)\(|\b(?:indexedDB\.open|sqlite3\.connect|"
               r"create_engine|createPool|new PrismaClient|new MongoClient|createClient)\s*\(|\.objects\.(?:get|filter)\(",
    "network": r"\b(?:fetch|axios\.(?:get|post|request)|httpx\.(?:get|post|AsyncClient)|"
               r"requests\.(?:get|post|Session)|urllib\.request\.urlopen)\s*\(",
    "payments": r"\b(?:stripe\.checkout\.sessions\.create|stripe\.PaymentIntent\.create|"
                r"paypal\.orders\.create|createPaymentIntent)\s*\(",
    "cli": r"\b(?:argparse\.ArgumentParser|click\.command|typer\.Typer|new Command)\s*\(|\bprocess\.argv\b",
    "ml": r"\b(?:from|import)\s+(?:sklearn|torch|tensorflow|keras|xgboost)\b|\bmodel\.(?:fit|train)\s*\(",
    "assertions": r"\b(?:assert\b|assertEqual\s*\(|expect\s*\(|pytest\.raises\s*\(|assert\.\w+\s*\()",
    "handling": r"\b(?:try\s*[:{]|except\s+|catch\s*\(|\.catch\s*\(|response\.ok\b|raise_for_status\s*\()",
    "accessibility": r"\baria-(?:label|labelledby|describedby)\s*=|<(?:main|nav|label|button)\b",
    "validation": r"\b(?:BaseModel|z\.object|Joi\.object|safeParse|validate_request|validateRequest)\s*[\(\.:]",
    "resource_bounds": r"\b(?:limit|page_size|pageSize|timeout|AbortController|cache)\b",
    "input_bounds": r"\b(?:choices\s*=|required\s*=|add_argument\s*\(|\.option\s*\()",
    "evaluation": r"\b(?:train_test_split|cross_val_score|classification_report|evaluate|f1_score)\s*\(",
    "webhook_validation": r"\b(?:constructEvent|verifyWebhook|verify_webhook)\s*\(",
    "state_defaults": r"\b(?:useState|useReducer|createSlice|writable)\s*\(",
    "blocking": r"\b(?:readFileSync|writeFileSync|execFileSync|time\.sleep)\s*\(",
    "markers": r"^\s*(?:#|//)\s*(?:FIXME|HACK)\b",
}
COMPILED = {key: re.compile(value, re.MULTILINE) for key, value in PATTERNS.items()}
FEATURES = {
    "Book catalogue": r"\b(?:bookCatalog(?:ue)?|bookLibrary|listBooks|bookshelf)\b",
    "Search and filtering": r"\b(?:searchBooks|searchQuery|filterBooks|filterResults)\b",
    "Bookmarks": r"\b(?:bookmarks?|addBookmark|removeBookmark)\b",
    "Reading progress": r"\b(?:readingProgress|lastReadPage|saveProgress)\b",
    "Offline reading": r"\b(?:offlineReading|offlineCache|serviceWorker\.register)\b",
}
PRIVATE_KEY = re.compile(r"-----BEGIN ((?:RSA |EC |OPENSSH )?PRIVATE KEY)-----\s+"
                         r"(?:[A-Za-z0-9+/=]{48,}\s+){2,}-----END \1-----")


@dataclass(frozen=True)
class Check:
    title: str
    result: int | None
    detail: str
    evidence: tuple[str, int] | None = None
    severity: str | None = None


def first_hit(sources, expression):
    for path, code in sorted(sources.items()):
        if match := expression.search(code):
            return path, code.count("\n", 0, match.start()) + 1
    return None


def first_file(paths):
    return (min(paths), 1) if paths else None


def assess(title, evidence, detail):
    return Check(title, 100 if evidence else None, detail, evidence)


def inspect_project(snapshot, coverage):
    sources = {path: text for path, text in snapshot["sources"].items()
               if not test_path(path) and not set(path.lower().split("/")[:-1]) & SYNTAX_FILTER}
    traits = {name: first_hit(sources, COMPILED[name]) for name in OPTIONAL if name != "security"}
    metadata_files = snapshot.get("metadata_files", {})
    summary = " ".join([snapshot.get("description", ""), *[
        value[:6000] for path, value in sorted(metadata_files.items()) if path.lower().startswith("readme")
    ]])
    reader = bool(traits["ui"] and re.search(r"\b(?:reader|ebook|e-book|reading app|book catalogue)\b", summary, re.IGNORECASE))
    dependencies = " ".join(value[:6000] for path, value in metadata_files.items()
                            if path.rsplit("/", 1)[-1].lower() in MANIFESTS)
    if traits["ui"] and traits["api"]:
        kind = "Full-stack app"
    elif reader:
        kind = "Reader app"
    elif traits["ui"]:
        kind = "Frontend app"
    elif traits["api"]:
        kind = "Backend SaaS" if traits["auth"] and (traits["storage"] or traits["payments"]) else "Backend API"
    elif traits["cli"]:
        kind = "CLI"
    elif traits["ml"]:
        kind = "ML or data project"
    else:
        kind = "General software"

    declarations = {
        "auth": r"\b(?:authentication|authorization|login|sign[ -]in|oauth|protected routes|user accounts)\b",
        "storage": r"\b(?:local storage|indexeddb|database|persistence|postgresql|cloud sync|offline bookmarks)\b",
        "network": r"\b(?:external api|public api|api integration|remote catalogue)\b",
        "payments": r"\b(?:payments?|stripe|checkout|subscription billing)\b",
        "ui": r"\b(?:web app|frontend|responsive interface|reader app)\b",
        "api": r"\b(?:rest api|backend api|api server)\b",
        "state": r"\b(?:state management|client state|reading progress|bookmarks)\b",
        "cli": r"\b(?:command.line interface|cli tool)\b",
        "ml": r"\b(?:model training|machine learning|model evaluation)\b",
    }
    weights = WEIGHTS[kind]
    decisions = {}
    for key in OPTIONAL:
        hit = traits.get(key) if key != "security" else (
            traits["api"] or traits["auth"] or traits["payments"] or first_hit(sources, PRIVATE_KEY)
        )
        dependency_patterns = {"auth": r"\b(?:passport|next-auth|pyjwt)\b", "storage": r"\b(?:sqlalchemy|prisma|psycopg)\b",
                               "payments": r"\bstripe\b", "ml": r"\b(?:scikit-learn|torch|tensorflow)\b"}
        declared = bool(re.search(declarations.get(key, r"(?!)"), summary, re.IGNORECASE) or
                        re.search(dependency_patterns.get(key, r"(?!)"), dependencies, re.IGNORECASE))
        if hit:
            status, reason = "applicable", "The source sample includes a matching capability signal."
        elif key in weights or declared or coverage["truncated"] or coverage["percent"] < 75:
            status, reason = "uncertain", "The context suggests this criterion or source coverage cannot establish its relevance."
        else:
            status, reason = "not_applicable", "The project context and sampled source do not indicate this capability."
        decisions[key] = {"id": key, "name": LABELS[key], "relevance": status, "reason": reason,
                          "evidence": citation(snapshot, hit), "proposedWeight": weights.get(key, EXTRA[key])}
    return kind, decisions, sources


def citation(snapshot, site):
    if site is None:
        return None
    path, line = site
    return {"path": path, "line": line, "url": None if snapshot["revision"] == "sample" else
            source_href(snapshot["repo"], snapshot["revision"], path, line)}


def collect_checks(snapshot, parsed, sources):
    paths = snapshot["paths"]
    tests = {path: text for path, text in snapshot["sources"].items() if test_path(path)}
    def token(name):
        return first_hit(sources, COMPILED[name])

    first_source = first_file(sources)
    invalid = first_file([path for path in sources if not parsed[path].syntax_ok])
    dependable = Check("Source parses with the supported analyzers", 0 if invalid else (100 if first_source else None),
                       "Checks syntax in the eligible sample. This is static evidence and runtime behavior is unmeasured.",
                       invalid or first_source)
    large_file = first_file([path for path, text in sources.items() if len(text.splitlines()) > 450])
    marker = token("markers")
    blocking = token("blocking")
    test_evidence = first_hit(tests, COMPILED["assertions"])
    test_paths = [path for path in paths if test_path(path)]
    missing_tests = first_source if not test_paths and not snapshot["truncated"] else None
    workflows = first_file([path for path in paths if path.startswith(".github/workflows/")
                            and path.endswith((".yaml", ".yml"))])
    manifest = first_file([path for path in paths if path.rsplit("/", 1)[-1].lower() in MANIFESTS])
    lock = first_file([path for path in paths if path.rsplit("/", 1)[-1].lower() in LOCKS])
    docs = first_file([path for path in paths if path.lower() in {"readme", "readme.md", "readme.rst"}])
    private_key = first_hit(sources, PRIVATE_KEY)
    modularity = next(((path, line) for path in sorted(sources) for spec, _, _, line in parsed[path].imports
                       if spec.startswith(".")), None)
    return {
        "features": [dependable, assess("Failure-handling signals", token("handling"),
                                       "Looks for explicit handling in source. Feature behavior still requires runtime evidence.")],
        "code": [Check("Sampled file size", 0 if large_file else (100 if first_source else None),
                       "Review modules over 450 lines for separable responsibilities.", large_file or first_source),
                 Check("Explicit maintenance markers", 0 if marker else (100 if first_source else None),
                       "Review source lines marked FIXME or HACK.", marker or first_source)],
        "architecture": [assess("Local module separation", modularity, "Looks for boundaries between local modules."),
                         assess("Project entry documentation", docs, "A root README can document major components.")],
        "tests": [Check("Assertions in sampled tests", 100 if test_evidence else 0 if missing_tests else None,
                        "The available file tree has no recognizable test paths." if missing_tests else
                        "Checks static assertions. Pass rate and coverage require execution.", test_evidence or missing_tests),
                  assess("GitHub Actions configuration", workflows, "Workflow presence provides a reproducibility signal.")],
        "performance": [Check("Blocking I/O signals", 0 if blocking else (100 if first_source else None),
                              "Review synchronous I/O in hot paths. No runtime benchmarks were run.", blocking or first_source),
                        assess("Resource bounds", token("resource_bounds"), "Looks for bounded-work or timeout signals.")],
        "dependencies": [assess("Dependency manifest", manifest, "Looks for declared dependencies."),
                         assess("Dependency lockfile", lock, "Looks for reproducible resolution.")],
        "docs": [assess("Root README", docs, "Looks for a root entry point for setup and usage.")],
        "ui": [assess("Semantic or accessible UI markup", token("accessibility"),
                      "Checks static landmarks, control elements or labels. Accessibility conformance remains unmeasured.")],
        "state": [assess("Explicit client state", token("state_defaults"), "Looks for a defined client state mechanism.")],
        "api": [assess("Request validation", token("validation"), "Looks for a request schema or input validation."),
                assess("Request error handling", token("handling"), "Looks for explicit handling of errors.")],
        "auth": [assess("Authentication signals", token("auth"), "Checks a login or identity verification signal."),
                 assess("Authorization signals", token("permissions"),
                        "Looks for an explicit owner, role or permission check. Enforcement requires review.")],
        "storage": [assess("Persistence mechanism", token("storage"), "Checks for a local store or database mechanism."),
                    assess("Storage failure handling", token("handling"), "Checks for explicit exception handling in source.")],
        "security": [Check("Committed private-key material", 0 if private_key else None,
                           "A private-key block is present in non-fixture source. Review and rotate if active."
                           if private_key else "This scan does not establish the absence of exposed credentials.",
                           private_key, "critical" if private_key else None)],
        "network": [assess("Network error handling", token("handling"), "Checks for explicit failure handling."),
                    assess("Bounded external calls", token("resource_bounds"), "Looks for timeouts or other resource bounds.")],
        "payments": [assess("Webhook validation", token("webhook_validation"), "Looks for a signature verification mechanism.")],
        "cli": [assess("CLI input contract", token("input_bounds"), "Looks for declared command arguments or options.")],
        "ml": [assess("Model evaluation", token("evaluation"), "Looks for holdout, cross-validation or evaluation signals.")],
    }


def half_up(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def grade(score):
    return next((label for floor, label in [(900, "S"), (800, "A"), (700, "B"), (600, "C"), (400, "D")]
                 if score >= floor), "E") if score is not None else None


def finalize(report, expected=(), note=""):
    """Apply a user's expectation claims without reducing the scored denominator."""
    criteria = [
        {**item, "relevance": "uncertain", "reason": "The owner expects this capability. Source review is needed."}
        if item["id"] in expected and item["relevance"] == "not_applicable" else item
        for item in report["criteria"]
    ]
    applicable = [item for item in criteria if item["relevance"] == "applicable"]
    findings = [
        {**check, "weight": item["proposedWeight"] // len(item["checks"]) +
         (index < item["proposedWeight"] % len(item["checks"]))}
        for item in applicable for index, check in enumerate(item["checks"])
    ]
    assessed = [item for item in findings if item["rate"] is not None]
    active_weight = sum(item["proposedWeight"] for item in criteria if item["relevance"] != "not_applicable")
    measured = sum(item["weight"] for item in assessed)
    earned = sum(item["weight"] * item["rate"] for item in assessed)
    scoring_coverage = half_up(100 * measured, active_weight) if active_weight else 0
    severity_cap = 699 if any(item.get("severity") == "critical" for item in assessed) else None
    score = half_up(SCALE * earned, measured * 100) if scoring_coverage >= 35 and report["coverage"]["analyzed"] else None
    if score is not None and severity_cap is not None:
        score = min(score, severity_cap)
    coverage = report["coverage"]
    rankable = (score is not None and coverage["percent"] >= 75 and scoring_coverage >= 70
                and not coverage["truncated"] and not expected and not note)
    confidence = "high" if rankable and scoring_coverage >= 90 and coverage["percent"] >= 90 else (
        "moderate" if rankable else "low"
    )
    dimensions = []
    for item in applicable:
        rows = [row for row in assessed if row["dimension"] == item["name"]]
        maximum = sum(row["weight"] for row in rows)
        dimensions.append({"name": item["name"], "points": half_up(sum(row["weight"] * row["rate"] for row in rows), 100),
                           "max": maximum, "weight": item["proposedWeight"]})
    published = [
        {**item, "points": half_up(item["weight"] * item["rate"], 100) if item["rate"] is not None else None,
         "max": item["weight"], "state": "unmeasured" if item["rate"] is None else
         "review" if item["rate"] < 100 else "met"}
        for item in findings
    ]
    return {
        **report, "criteria": criteria, "score": score, "grade": grade(score), "rankable": rankable,
        "confidence": confidence, "evaluationCoverage": scoring_coverage, "severityCap": severity_cap,
        "dimensions": dimensions, "findings": published,
        "comparisonKey": report["archetype"] + "|" + ",".join(
            f"{item['id']}:{item['weight']}" for item in assessed
        ),
        "review": {"expected": list(expected), "note": note} if expected or note else None,
    }


def quality(snapshot, parsed):
    counts = Counter("Python" if path.endswith(".py") else "JavaScript / TypeScript" for path in snapshot["sources"])
    cohort = "Mixed" if len(counts) > 1 else next(iter(counts), None)
    coverage = {"analyzed": len(snapshot["sources"]), "eligible": snapshot["eligible"],
                "percent": min(100, half_up(100 * len(snapshot["sources"]), max(1, snapshot["eligible"]))),
                "total": snapshot["total_files"], "truncated": snapshot["truncated"]}
    kind, decisions, sources = inspect_project(snapshot, coverage)
    features = [
        {"name": label, "evidence": citation(snapshot, site)}
        for label, pattern in FEATURES.items() if (site := first_hit(sources, re.compile(pattern, re.IGNORECASE)))
    ]
    checks = collect_checks(snapshot, parsed, sources)
    criteria = []
    for key, name in LABELS.items():
        if key not in decisions and key not in WEIGHTS[kind]:
            continue
        item = decisions.get(key) or {"id": key, "name": name, "relevance": "applicable",
                                      "proposedWeight": WEIGHTS[kind][key], "evidence": None,
                                      "reason": "Included in the project-type rubric."}
        item["checks"] = [
            {"id": f"{key}:{index}", "title": check.title, "dimension": name, "rate": check.result,
             "detail": check.detail, "severity": check.severity,
             **(citation(snapshot, check.evidence) or {"path": None, "line": None, "url": None})}
            for index, check in enumerate(checks[key])
        ] if item["relevance"] == "applicable" else []
        criteria.append(item)
    return finalize({"version": RUBRIC, "scale": SCALE, "archetype": kind, "cohort": cohort,
                     "coverage": coverage, "criteria": criteria, "features": features})
