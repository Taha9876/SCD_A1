#!/usr/bin/env python3
"""Submission lint. It is a lint, not a grader.

Every check here corresponds to an automatic deduction in the assignment's
section 5.3. A clean run does not make the submission good; a dirty run nearly
guarantees a bad mark.

    python scripts/check_submission.py
    python scripts/check_submission.py --only manifests   # just the k8s checks

Exits 1 if any check fails. Run it before every push.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"


@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""
    # -N marks from section 5.3, so the output says what it is worth.
    penalty: int = 0


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "", penalty: int = 0) -> None:
        self.results.append(Result(name, passed, detail, penalty))

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if not r.passed]

    def render(self) -> int:
        for r in self.results:
            mark = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
            cost = f" {YELLOW}(-{r.penalty} marks){RESET}" if (r.penalty and not r.passed) else ""
            print(f"  [{mark}] {r.name}{cost}")
            if r.detail:
                for line in r.detail.splitlines():
                    print(f"         {DIM}{line}{RESET}")

        total = len(self.results)
        failed = len(self.failures)
        at_risk = sum(r.penalty for r in self.failures)
        print()
        if failed == 0:
            print(f"{GREEN}All {total} checks passed.{RESET}")
            print(f"{DIM}This is a lint, not a grader. It says nothing about "
                  f"whether the engineering is good.{RESET}")
            return 0
        print(f"{RED}{failed} of {total} checks failed.{RESET}")
        if at_risk:
            print(f"{YELLOW}Automatic deductions at risk: -{at_risk} marks.{RESET}")
        return 1


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def tracked_files() -> list[Path]:
    """Files Git knows about. The filesystem may hold untracked junk that is
    irrelevant to what gets submitted."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ROOT / line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Secrets -- the expensive ones (-20, -15)
# ---------------------------------------------------------------------------

#: Shapes of real credentials. Deliberately specific: a pattern that matches
#: the word "key" would fire on every comment in the repository and the check
#: would be ignored within a week.
SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"gsk_[A-Za-z0-9]{40,}", "Groq API key"),
    (r"sk-[A-Za-z0-9]{32,}", "OpenAI-style API key"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"github_pat_[A-Za-z0-9_]{50,}", "GitHub fine-grained PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
]

PLACEHOLDER_HINTS = (
    "REPLACE_ME", "PLACEHOLDER", "change-me", "changeme", "your-key-here",
    "not-a-real", "example", "test-key", "dummy",
)


def check_secrets(report: Report) -> None:
    text_suffixes = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json", ".md",
        ".toml", ".ini", ".cfg", ".sh", ".env", ".conf", ".html", ".css", "",
    }
    hits: list[str] = []
    for path in tracked_files():
        if path.suffix not in text_suffixes or not path.is_file():
            continue
        if path.name == "check_submission.py":
            continue  # this file contains the patterns themselves
        content = read(path)
        for pattern, label in SECRET_PATTERNS:
            for match in re.finditer(pattern, content):
                snippet = match.group(0)
                if any(hint.lower() in snippet.lower() for hint in PLACEHOLDER_HINTS):
                    continue
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}: {label} ({snippet[:12]}...)")

    report.add(
        "no credential-shaped strings in tracked files",
        not hits,
        "\n".join(hits) or "",
        penalty=20,
    )


def check_env_not_tracked(report: Report) -> None:
    tracked = {p.name for p in tracked_files()}
    bad = [n for n in tracked if n == ".env" or (n.startswith(".env.") and n != ".env.example")]
    report.add(
        ".env is not tracked by Git",
        not bad,
        f"tracked: {', '.join(sorted(bad))}" if bad else "",
        penalty=20,
    )

    gitignore = read(ROOT / ".gitignore")
    report.add(
        ".env is listed in .gitignore",
        bool(re.search(r"^\.env\s*$", gitignore, re.MULTILINE)),
        "" if ".env" in gitignore else "add a bare `.env` line to .gitignore",
        penalty=20,
    )

    report.add(
        ".env.example is committed",
        (ROOT / ".env.example").exists(),
        "",
        penalty=5,
    )


def check_env_history(report: Report) -> None:
    """A secret removed in the latest commit is still in the history, and the
    deduction is for the history."""
    try:
        out = subprocess.run(
            ["git", "log", "--all", "--pretty=format:%H", "--name-only", "--diff-filter=A"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        report.add("git history contains no .env", True, "git unavailable; skipped")
        return

    offenders = sorted({
        line.strip()
        for line in out.splitlines()
        if line.strip()
        and (
            Path(line.strip()).name == ".env"
            or (Path(line.strip()).name.startswith(".env.")
                and Path(line.strip()).name != ".env.example")
        )
    })
    report.add(
        "git history never contained a .env",
        not offenders,
        ("found in history: " + ", ".join(offenders) +
         "\nRotate the credential and write an incident note; removing the file "
         "from HEAD is not enough.") if offenders else "",
        penalty=20,
    )


# ---------------------------------------------------------------------------
# Image pinning (-8) and :latest deploys (-8)
# ---------------------------------------------------------------------------

def check_image_pinning(report: Report) -> None:
    compose_files = [ROOT / "compose.yaml", ROOT / "compose.prod.yaml"]
    unpinned: list[str] = []
    for path in compose_files:
        if not path.exists():
            continue
        for lineno, line in enumerate(read(path).splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("image:"):
                continue
            ref = stripped.split("image:", 1)[1].strip().strip('"').strip("'")
            if "${" in ref:
                continue  # a variable, checked separately below
            name = ref.rsplit("/", 1)[-1]
            if ":" not in name:
                unpinned.append(f"{path.name}:{lineno} {ref} has no tag")
            elif name.endswith(":latest"):
                unpinned.append(f"{path.name}:{lineno} {ref} uses :latest")
    report.add(
        "every Compose image is pinned to an explicit tag",
        not unpinned,
        "\n".join(unpinned),
        penalty=8,
    )

    dockerfiles = list(ROOT.glob("*/Dockerfile"))
    unpinned_bases: list[str] = []
    for path in dockerfiles:
        for lineno, line in enumerate(read(path).splitlines(), 1):
            if not line.strip().upper().startswith("FROM "):
                continue
            ref = line.split(None, 1)[1].split(" AS ")[0].split(" as ")[0].strip()
            if ref.startswith("$"):
                continue
            name = ref.rsplit("/", 1)[-1]
            if ":" not in name and "@" not in name:
                rel = path.relative_to(ROOT)
                unpinned_bases.append(f"{rel}:{lineno} {ref} has no tag or digest")
    report.add(
        "every Dockerfile base image is pinned",
        not unpinned_bases,
        "\n".join(unpinned_bases),
        penalty=8,
    )


def check_no_latest_deploy(report: Report) -> None:
    """:latest may be PUSHED. It may never be DEPLOYED."""
    offenders: list[str] = []

    prod = ROOT / "compose.prod.yaml"
    if prod.exists():
        for lineno, line in enumerate(read(prod).splitlines(), 1):
            if ":latest" in line and not line.strip().startswith("#"):
                offenders.append(f"compose.prod.yaml:{lineno} {line.strip()}")

    for path in sorted((ROOT / "k8s").rglob("*.yaml")):
        for lineno, line in enumerate(read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"(image:|newTag:).*\blatest\b", stripped):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} {stripped}")

    # In the workflows, :latest is fine in a build-push step and not in a
    # deploy step, so only flag it near a kubectl/kustomize deploy line.
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        lines = read(path).splitlines()
        for lineno, line in enumerate(lines, 1):
            if not re.search(r"(kubectl (apply|set image)|kustomize edit set image)", line):
                continue
            window = " ".join(lines[max(0, lineno - 3): lineno + 3])
            if ":latest" in window:
                offenders.append(
                    f"{path.relative_to(ROOT)}:{lineno} :latest near a deploy command"
                )

    report.add(
        ":latest is never deployed (pushing it is fine)",
        not offenders,
        "\n".join(offenders),
        penalty=8,
    )


# ---------------------------------------------------------------------------
# localhost for service-to-service (-8)
# ---------------------------------------------------------------------------

def check_no_localhost_service_calls(report: Report) -> None:
    """localhost inside a container is that container.

    Healthchecks and probes legitimately use localhost -- they are talking to
    the same process. Service-to-service must use a service name.
    """
    offenders: list[str] = []
    checked = [
        *sorted((ROOT / "k8s").rglob("*.yaml")),
        ROOT / "compose.yaml",
        ROOT / "compose.prod.yaml",
        ROOT / "frontend" / "nginx.conf",
    ]
    # Keys that name another service, as opposed to a self-check.
    service_keys = re.compile(
        r"(DATABASE_URL|REDIS_URL|BACKEND_ORIGIN|API_BASE_URL|LLM_BASE_URL"
        r"|OLLAMA_BASE_URL|proxy_pass)",
        re.IGNORECASE,
    )
    for path in checked:
        if not path.exists():
            continue
        for lineno, line in enumerate(read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not service_keys.search(stripped):
                continue
            if re.search(r"(localhost|127\.0\.0\.1)", stripped):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} {stripped[:90]}")
    report.add(
        "no localhost in service-to-service configuration",
        not offenders,
        "\n".join(offenders),
        penalty=8,
    )


# ---------------------------------------------------------------------------
# Network segmentation (-8), published DB ports (-8)
# ---------------------------------------------------------------------------

def check_network_segmentation(report: Report) -> None:
    compose = read(ROOT / "compose.yaml")
    report.add(
        "compose.yaml declares an internal: true network",
        bool(re.search(r"^\s*internal:\s*true\s*$", compose, re.MULTILINE)),
        "the frontend must have no route to the database",
        penalty=8,
    )

    # The frontend must not be attached to the internal network. Parsed
    # structurally rather than by regex, because indentation matters here.
    try:
        import yaml  # optional dependency

        data = yaml.safe_load(compose) or {}
        services = data.get("services", {})
        frontend_networks = services.get("frontend", {}).get("networks", []) or []
        report.add(
            "frontend is not attached to the internal network",
            "internal" not in frontend_networks,
            f"frontend networks: {frontend_networks}",
            penalty=8,
        )
        backend_networks = services.get("backend", {}).get("networks", []) or []
        report.add(
            "backend bridges both networks",
            {"edge", "internal"} <= set(backend_networks),
            f"backend networks: {backend_networks}",
            penalty=4,
        )
        for name in ("database", "cache"):
            nets = services.get(name, {}).get("networks", []) or []
            report.add(
                f"{name} is on the internal network only",
                nets == ["internal"],
                f"{name} networks: {nets}",
                penalty=8,
            )
    except ImportError:
        report.add("compose service networks parsed", True, "pyyaml absent; skipped")


def check_no_published_db_ports_in_prod(report: Report) -> None:
    prod = ROOT / "compose.prod.yaml"
    if not prod.exists():
        report.add("compose.prod.yaml exists", False, "required", penalty=5)
        return

    try:
        import yaml

        data = yaml.safe_load(read(prod)) or {}
        services = data.get("services", {})
        offenders = [
            name
            for name in ("database", "cache")
            if services.get(name, {}).get("ports")
        ]
        report.add(
            "compose.prod.yaml publishes no database or cache port",
            not offenders,
            f"published: {', '.join(offenders)}" if offenders else "",
            penalty=8,
        )
        has_build = [name for name, svc in services.items() if "build" in (svc or {})]
        report.add(
            "compose.prod.yaml contains no build: key",
            not has_build,
            f"services with build: {', '.join(has_build)}" if has_build else "",
            penalty=4,
        )
        uses_tag_var = "IMAGE_TAG" in read(prod)
        report.add(
            "compose.prod.yaml uses image: ${IMAGE_TAG}",
            uses_tag_var,
            "",
            penalty=4,
        )
    except ImportError:
        report.add("compose.prod.yaml parsed", True, "pyyaml absent; skipped")


def check_no_nodeport_on_data_services(report: Report) -> None:
    offenders: list[str] = []
    try:
        import yaml

        for path in sorted((ROOT / "k8s").rglob("*.yaml")):
            for doc in yaml.safe_load_all(read(path)):
                if not isinstance(doc, dict) or doc.get("kind") != "Service":
                    continue
                name = doc.get("metadata", {}).get("name", "?")
                svc_type = doc.get("spec", {}).get("type", "ClusterIP")
                is_data = any(k in name for k in ("postgres", "redis", "database", "cache"))
                if is_data and svc_type in ("NodePort", "LoadBalancer"):
                    offenders.append(f"{path.relative_to(ROOT)}: {name} is {svc_type}")
    except ImportError:
        report.add("k8s Service types checked", True, "pyyaml absent; skipped")
        return
    report.add(
        "no NodePort or LoadBalancer on a data service",
        not offenders,
        "\n".join(offenders),
        penalty=8,
    )


# ---------------------------------------------------------------------------
# Postgres as a StatefulSet with a PVC (-8)
# ---------------------------------------------------------------------------

def check_postgres_statefulset(report: Report) -> None:
    try:
        import yaml
    except ImportError:
        report.add("Postgres is a StatefulSet with a PVC", True, "pyyaml absent; skipped")
        return

    found_sts = False
    has_vct = False
    bad_deployment = False
    for path in sorted((ROOT / "k8s").rglob("*.yaml")):
        for doc in yaml.safe_load_all(read(path)):
            if not isinstance(doc, dict):
                continue
            name = doc.get("metadata", {}).get("name", "")
            if "postgres" not in name:
                continue
            if doc.get("kind") == "StatefulSet":
                found_sts = True
                has_vct = bool(doc.get("spec", {}).get("volumeClaimTemplates"))
            if doc.get("kind") == "Deployment":
                bad_deployment = True

    report.add("Postgres is a StatefulSet, not a Deployment", found_sts and not bad_deployment,
               "a Deployment for a database is a marked error", penalty=8)
    report.add("the Postgres StatefulSet has volumeClaimTemplates", has_vct,
               "without a PVC, deleting the pod deletes every complaint", penalty=8)


# ---------------------------------------------------------------------------
# Kubernetes hygiene: probes, requests, namespace, placeholders
# ---------------------------------------------------------------------------

def check_k8s_manifest_hygiene(report: Report) -> None:
    try:
        import yaml
    except ImportError:
        report.add("k8s manifest hygiene", True, "pyyaml absent; skipped")
        return

    missing_requests: list[str] = []
    default_namespace: list[str] = []
    workloads = 0
    backend_probes: dict[str, bool] = {}

    for path in sorted((ROOT / "k8s").rglob("*.yaml")):
        for doc in yaml.safe_load_all(read(path)):
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            if kind not in ("Deployment", "StatefulSet", "Job", "DaemonSet"):
                continue
            workloads += 1
            name = doc.get("metadata", {}).get("name", "?")
            ns = doc.get("metadata", {}).get("namespace")
            if ns in (None, "default"):
                default_namespace.append(f"{kind}/{name} in {ns or '<unset>'}")

            containers = (
                doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            )
            for container in containers:
                requests = (container.get("resources") or {}).get("requests") or {}
                limits = (container.get("resources") or {}).get("limits") or {}
                if "cpu" not in requests or "memory" not in requests:
                    missing_requests.append(f"{kind}/{name}/{container.get('name')}: requests")
                if "cpu" not in limits or "memory" not in limits:
                    missing_requests.append(f"{kind}/{name}/{container.get('name')}: limits")
                if name == "backend":
                    for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
                        backend_probes[probe] = probe in container

    report.add("every workload sets a namespace other than default", not default_namespace,
               "\n".join(default_namespace), penalty=2)
    report.add("every container sets resource requests and limits", not missing_requests,
               "\n".join(missing_requests) +
               ("\nWithout requests.cpu the HPA reports <unknown>/60% forever."
                if missing_requests else ""),
               penalty=2)
    report.add("the backend declares all three probes",
               len(backend_probes) == 3 and all(backend_probes.values()),
               f"found: {sorted(k for k, v in backend_probes.items() if v)}", penalty=4)

    secret_text = read(ROOT / "k8s" / "base" / "secret.yaml")
    has_placeholder = any(hint in secret_text for hint in PLACEHOLDER_HINTS)
    report.add("the committed Secret holds placeholders only", has_placeholder,
               "base64 is encoding, not encryption", penalty=15)


def check_probe_semantics(report: Report) -> None:
    """/health must not touch the database.

    A liveness probe that depends on Postgres turns a database blip into a
    restart loop across every backend pod at once.
    """
    health_route = read(ROOT / "backend" / "app" / "routes" / "health.py")
    health_body = ""
    match = re.search(r"async def health\(.*?\n(.*?)(?=\n@router|\nasync def |\Z)",
                      health_route, re.DOTALL)
    if match:
        health_body = match.group(1)
    touches_db = bool(re.search(r"(repo|session|execute|ping\(\))", health_body))
    report.add("/health does not touch the database", not touches_db,
               health_body.strip()[:200] if touches_db else "", penalty=3)

    ready_uses_both = "repo.ping" in health_route and "cache.ping" in health_route
    report.add("/ready checks both Postgres and Redis", ready_uses_both, "", penalty=3)


# ---------------------------------------------------------------------------
# CI/CD: needs: gating, least privilege, pinned actions
# ---------------------------------------------------------------------------

def check_workflow_gating(report: Report) -> None:
    try:
        import yaml
    except ImportError:
        report.add("publishing jobs are gated by needs:", True, "pyyaml absent; skipped")
        return

    ungated: list[str] = []
    unparseable: list[str] = []
    missing_permissions: list[str] = []
    unpinned_actions: list[str] = []

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        raw = read(path)
        # `on:` parses as the boolean True in YAML 1.1, so read the doc as-is
        # and look up either key.
        try:
            doc = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            # A workflow that does not parse never runs at all, which is a
            # worse failure than anything else this function checks for.
            unparseable.append(f"{path.name}: {exc}")
            continue
        jobs = doc.get("jobs", {}) or {}
        has_top_permissions = "permissions" in doc

        for job_name, job in jobs.items():
            job = job or {}
            body = yaml.safe_dump(job)
            publishes = bool(re.search(r"(push:\s*true|kubectl apply|rollout status|gh release)", body))
            if publishes and not job.get("needs"):
                ungated.append(f"{path.name}: job '{job_name}' publishes or deploys with no needs:")
            if not has_top_permissions and "permissions" not in job:
                missing_permissions.append(f"{path.name}: job '{job_name}' has no permissions block")

        for match in re.finditer(r"uses:\s*([^\s]+)", raw):
            ref = match.group(1)
            if ref.startswith("./"):
                continue
            if "@" not in ref:
                unpinned_actions.append(f"{path.name}: {ref} is not pinned")

    # A workflow that does not parse never runs at all, which is a worse
    # failure than anything else this function checks for.
    report.add("every workflow file is valid YAML", not unparseable,
               "\n".join(unparseable), penalty=8)
    report.add("every publishing or deploying job is gated by needs:", not ungated,
               "\n".join(ungated) +
               ("\nWithout needs: you publish artifacts from code you already "
                "know is broken." if ungated else ""),
               penalty=8)
    report.add("every workflow declares a permissions block", not missing_permissions,
               "\n".join(missing_permissions), penalty=2)
    report.add("every action is pinned to at least a major version", not unpinned_actions,
               "\n".join(unpinned_actions), penalty=2)


# ---------------------------------------------------------------------------
# Required files
# ---------------------------------------------------------------------------

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    ".gitignore",
    ".env.example",
    "compose.yaml",
    "compose.prod.yaml",
    "backend/Dockerfile",
    "backend/.dockerignore",
    "frontend/Dockerfile",
    "frontend/.dockerignore",
    "backend/alembic.ini",
    "load/k6-script.js",
    "docs/ENGINEERING-NOTES.md",
    "docs/RUNBOOK.md",
    "docs/AI-USAGE.md",
    "docs/TRIAGE.md",
    "docs/adr/0001-provider-interface.md",
    "docs/adr/0002-frontend-runtime-config.md",
    "docs/adr/0003-deploy-by-sha.md",
    "docs/adr/0004-pii-and-data-governance.md",
    ".github/workflows/ci.yml",
    ".github/workflows/cd.yml",
    ".github/workflows/release.yml",
]


def check_required_files(report: Report) -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    report.add("all required files are present", not missing,
               "missing: " + ", ".join(missing) if missing else "", penalty=5)

    migrations = list((ROOT / "backend" / "alembic" / "versions").glob("*.py"))
    report.add("at least one Alembic migration exists", bool(migrations),
               "no CREATE TABLE in startup code means a migration must exist", penalty=4)


def check_no_ddl_in_startup(report: Report) -> None:
    """create_all in application startup is a marked error."""
    offenders: list[str] = []
    # Match a CALL -- `create_all(` -- not the bare word, which appears in
    # models.py's docstring explaining that it is deliberately never called
    # here. A check that fires on its own documentation gets ignored.
    call = re.compile(r"create_all\s*\(")
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        for lineno, line in enumerate(read(path).splitlines(), 1):
            if call.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} calls create_all")
    report.add("no schema DDL in application startup code", not offenders,
               "\n".join(offenders), penalty=4)


def check_commits_not_on_main(report: Report) -> None:
    """Direct pushes to main are -5. Only the PR merge commits belong there."""
    try:
        subprocess.run(["git", "rev-parse", "--verify", "main"], cwd=ROOT,
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        report.add("no non-merge commits pushed directly to main", True,
                   "main not found locally; verify on GitHub", penalty=0)
        return

    out = subprocess.run(
        ["git", "log", "main", "--no-merges", "--first-parent", "--pretty=%h %s"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    # The very first commit on main is unavoidable.
    direct = [line for line in out.splitlines() if line.strip()][:-1]
    report.add("no non-merge commits pushed directly to main", len(direct) == 0,
               "\n".join(direct[:10]) if direct else "", penalty=5)


GROUPS = {
    "secrets": [check_secrets, check_env_not_tracked, check_env_history],
    "images": [check_image_pinning, check_no_latest_deploy],
    "networking": [
        check_no_localhost_service_calls,
        check_network_segmentation,
        check_no_published_db_ports_in_prod,
        check_no_nodeport_on_data_services,
    ],
    "manifests": [
        check_postgres_statefulset,
        check_k8s_manifest_hygiene,
        check_no_nodeport_on_data_services,
        check_no_latest_deploy,
    ],
    "probes": [check_probe_semantics],
    "cicd": [check_workflow_gating],
    "files": [check_required_files, check_no_ddl_in_startup],
    "git": [check_commits_not_on_main],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=sorted(GROUPS),
        action="append",
        help="run only this group of checks (repeatable)",
    )
    args = parser.parse_args()

    groups = args.only or list(GROUPS)
    report = Report()

    print()
    print("CivicPulse submission lint")
    print("=" * 60)
    for group in groups:
        print(f"\n{group}:")
        start = len(report.results)
        for check in GROUPS[group]:
            check(report)
        if len(report.results) == start:
            print("  (no checks ran)")
        # Render only this group's results as we go.
        for r in report.results[start:]:
            mark = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
            cost = f" {YELLOW}(-{r.penalty} marks){RESET}" if (r.penalty and not r.passed) else ""
            print(f"  [{mark}] {r.name}{cost}")
            if r.detail and not r.passed:
                for line in r.detail.splitlines():
                    print(f"         {DIM}{line}{RESET}")

    failed = len(report.failures)
    at_risk = sum(r.penalty for r in report.failures)
    print()
    print("=" * 60)
    if failed == 0:
        print(f"{GREEN}All {len(report.results)} checks passed.{RESET}")
        print(f"{DIM}This is a lint, not a grader. A clean run says nothing about")
        print(f"whether the engineering is any good.{RESET}")
        return 0
    print(f"{RED}{failed} of {len(report.results)} checks failed.{RESET}")
    if at_risk:
        print(f"{YELLOW}Automatic deductions at risk: -{at_risk} marks.{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
