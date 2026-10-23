"""Read-only, source-exact Hepta P0-P7 CI audit. Never a scientific promotion gate.

The scope of this tool is narrow: a required GitHub Actions workflow must be
successful on the *same pinned commit* as the owning PR and every explicitly
required native job must actually have executed successfully. Even eight clean
CI results do not authorize model or runtime promotion.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHEMA = "hepta.stem-ndu.p0-p7-ci-audit.v1"
REPO = "TrillionniumFoundation/hepta-private-ci"
STAGES = tuple(f"P{n}" for n in range(8))
SHA = re.compile(r"[0-9a-f]{40}\Z")
# Not a checklist the caller can delete to manufacture readiness. An external,
# independently approved evidence mechanism must establish these separately.
OPEN_SCIENCE = {
    "P0": ("actual_encoder_owner_attestation", "complete_forward_and_resource_ledger"),
    "P1": ("future_ood_equal_budget_learning", "calibrated_coverage_and_minority"),
    "P2": ("natural_source_disjoint_audio_video", "missing_and_wrong_pair_refusals"),
    "P3": ("executed_verified_multistep_reasoning", "equal_cost_strong_search_controls"),
    "P4": ("preregistered_multi_seed_ndu", "nonzero_causal_risk_effect", "matched_cost_coverage"),
    "P5": ("independent_distillation_gain", "no_old_task_regression"),
    "P6": ("three_generation_rollback", "withdrawal_and_negative_transfer"),
    "P7": ("native_windows_delete_isolation", "target_device_p95_p99_energy", "independent_finaluse"),
}


class AuditError(ValueError):
    """Invalid plan, ambiguous source status, or inaccessible evidence."""


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise AuditError(f"duplicate JSON key: {key[:64]!r}")
        out[key] = value
    return out


def read_json(path: str | Path) -> dict:
    f = Path(path)
    if f.stat().st_size > 256_000:
        raise AuditError("JSON input exceeds 256000 bytes")
    try:
        raw = json.loads(f.read_text(encoding="utf-8"),
                         object_pairs_hook=_pairs_unique,
                         parse_constant=lambda x: (_ for _ in ()).throw(
                             AuditError(f"noncanonical JSON constant: {x}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AuditError("root must be a JSON object")
    return raw


def validate_plan(plan: dict) -> None:
    if plan.get("schema") != SCHEMA or plan.get("repository") != REPO:
        raise AuditError("wrong schema or repository")
    stages = plan.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise AuditError("plan must contain exactly P0 through P7")
    for name in STAGES:
        s = stages[name]
        if not isinstance(s, dict) or set(s) != {"pr", "head_sha", "checks"}:
            raise AuditError(f"{name}: unrecognized or missing stage fields")
        if type(s["pr"]) is not int or s["pr"] <= 0:
            raise AuditError(f"{name}: invalid PR number")
        if type(s["head_sha"]) is not str or not SHA.fullmatch(s["head_sha"]):
            raise AuditError(f"{name}: invalid pinned 40-char source SHA")
        checks = s["checks"]
        if not isinstance(checks, list) or not checks:
            raise AuditError(f"{name}: empty CI requirements")
        seen = set()
        for c in checks:
            if (not isinstance(c, dict) or set(c) != {"workflow", "jobs"}
                    or not isinstance(c["workflow"], str)
                    or not 1 <= len(c["workflow"]) <= 128
                    or c["workflow"] in seen
                    or not isinstance(c["jobs"], list) or not c["jobs"]
                    or any(type(j) is not str or not 1 <= len(j) <= 256
                           for j in c["jobs"])
                    or len(c["jobs"]) != len(set(c["jobs"]))):
                raise AuditError(f"{name}: duplicate or malformed CI requirement")
            seen.add(c["workflow"])
        if "blocking-ci" not in seen:
            raise AuditError(f"{name}: full blocking-ci cannot be omitted")


class GithubClient:
    """Bounded read-only GitHub REST; the token is never printed."""

    def __init__(self, token: str | None = None):
        self.token = token

    def get(self, path: str) -> dict:
        if not path.startswith(f"/repos/{REPO}/"):
            raise AuditError("off-repository REST route")
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "hepta-source-exact-readiness-v1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request("https://api.github.com" + path, headers=headers)
        try:
            with urlopen(req, timeout=20) as response:
                blob = response.read(4_000_001)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise AuditError(f"GitHub REST unavailable: {type(exc).__name__}") from exc
        if len(blob) > 4_000_000:
            raise AuditError("GitHub REST reply exceeds bounded 4MB")
        try:
            data = json.loads(blob, object_pairs_hook=_pairs_unique)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise AuditError(f"GitHub REST invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AuditError("GitHub REST response was not an object")
        return data


def _complete_listing(obj: dict, key: str) -> list:
    items = obj.get(key)
    count = obj.get("total_count")
    if (not isinstance(items, list) or type(count) is not int
            or count != len(items) or count > 100):
        # A partial listing must never qualify a source; pagination needs an
        # independently reviewed larger-scoped implementation first.
        raise AuditError(f"incomplete or unbounded GitHub {key} page")
    return items


def _latest_run(runs: list, name: str, sha: str) -> dict | None:
    matching = [r for r in runs if isinstance(r, dict)
                and r.get("name") == name and r.get("head_sha") == sha
                and r.get("event") == "pull_request"]
    if not matching:
        return None
    return max(matching,
               key=lambda r: (str(r.get("run_started_at") or r.get("updated_at")
                                  or r.get("created_at") or ""),
                              int(r.get("run_attempt") or 0),
                              int(r.get("id") or 0)))


def check_stage(name: str, spec: dict, get: Callable[[str], dict]) -> dict:
    """Fail-closed on source drift, skipped CI jobs and incomplete evidence."""
    reasons: list[str] = []
    sha, pr_number = spec["head_sha"], spec["pr"]
    prefix = f"/repos/{REPO}"
    try:
        pr = get(f"{prefix}/pulls/{pr_number}")
        if pr.get("head", {}).get("sha") != sha:
            reasons.append("PR head SHA drift; prior results are inadmissible")
        if pr.get("state") != "open":
            reasons.append("source PR is not open; reassess merge source")
        runs = _complete_listing(get(
            f"{prefix}/actions/runs?head_sha={sha}&per_page=100"), "workflow_runs")
        for requirement in spec["checks"]:
            label = requirement["workflow"]
            run = _latest_run(runs, label, sha)
            if run is None:
                reasons.append(f"missing exact-SHA workflow: {label}")
                continue
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                reasons.append(f"workflow not successful: {label} "
                               f"({run.get('status')}/{run.get('conclusion')})")
                continue
            ident = run.get("id")
            if type(ident) is not int or ident <= 0:
                reasons.append(f"malformed workflow run ID: {label}")
                continue
            jobs = _complete_listing(get(
                f"{prefix}/actions/runs/{ident}/jobs?per_page=100"), "jobs")
            for requested in requirement["jobs"]:
                matches = [j for j in jobs if isinstance(j, dict)
                           and j.get("name") == requested]
                if len(matches) != 1 or matches[0].get("status") != "completed" \
                        or matches[0].get("conclusion") != "success":
                    reasons.append(f"required native job not actually passed: "
                                   f"{label} / {requested}")
        # Eliminate a PR-head time-of-check/time-of-use race.
        pr_after = get(f"{prefix}/pulls/{pr_number}")
        if pr_after.get("head", {}).get("sha") != sha:
            reasons.append("PR head changed during audit")
    except (AuditError, TypeError, AttributeError, KeyError, ValueError) as exc:
        reasons.append(f"unverifiable GitHub record: {type(exc).__name__}: {exc}")

    return {"stage": name, "pr": pr_number, "source_sha": sha,
            "ci_preflight": "PASS" if not reasons else "BLOCKED",
            "ci_blockers": reasons,
            "scientific_and_authority_blockers": list(OPEN_SCIENCE[name]),
            "stage_qualified": False}


def audit(plan: dict, get: Callable[[str], dict]) -> dict:
    validate_plan(plan)
    results = [check_stage(s, plan["stages"][s], get) for s in STAGES]
    return {"schema": SCHEMA, "repository": REPO,
            "source": "read-only GitHub exact-SHA CI observations",
            "ci_preflight_count": sum(r["ci_preflight"] == "PASS" for r in results),
            "stages": results, "all_blockers_closed": False,
            "model_promotion_authorized": False,
            "authority": "SHADOW_ONLY/DENY_ALL/HOLD_NO_GO",
            "non_claim": "Even clean CI cannot certify independent scientific "
                         "outcomes, native isolation, real target hardware or FinalUse."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-ci-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = read_json(args.plan)
        report = audit(plan, GithubClient(os.environ.get("GITHUB_TOKEN")).get)
    except (AuditError, OSError) as exc:
        print(f"FAIL_CLOSED: {exc}", file=sys.stderr)
        return 2
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    print(f"HOLD_NO_GO: {report['ci_preflight_count']}/8 CI preflights ready; "
          "science and authorization remain unqualified")
    if args.require_ci_ready and report["ci_preflight_count"] != 8:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
