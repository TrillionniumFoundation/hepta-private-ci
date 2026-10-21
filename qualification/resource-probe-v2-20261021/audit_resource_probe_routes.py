"""Static event-filter audit for the exact five-file resource-only child.

This is a conservative filter analysis, not a GitHub scheduler emulator. Job
conditions, permissions and workflow source selection remain reviewable raw data.
"""

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "resource-probe-v2-work"
OUT = ROOT / "runner-prep/resource-probe-v2-review"
BASE = "81d9fcb36bddfcc6dc914f87697c642824273cc1"
OWNER = "codex/memory-cell-evidence-20261008"
CHILD = "agents/memory-resource-probe-v2-20261021"
SCOUTS = (
    ".github/workflows/hepta-memory-bf16-host-scout.yml",
    ".github/workflows/hepta-memory-bf16-hosted-scout.yml",
)
CHANGED = [
    *SCOUTS,
    "scripts/memory_cell/strong_rag_cpu_scout.py",
    "scripts/memory_cell/strong_rag_resource_snapshot.py",
    "scripts/memory_cell/test_strong_rag_cpu_scout.py",
]


def git(*args):
    return subprocess.check_output(["git", "-C", str(WORK), *args])


def match(pattern, value):
    # All patterns encountered in this snapshot use only these glob operators.
    if re.search(r"[\[\]{}+()\\]", pattern):
        raise ValueError(f"unsupported pattern needs manual review: {pattern!r}")
    token, index = "", 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            token += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            token += ".*"
            index += 2
        else:
            token += {"*": "[^/]*", "?": "[^/]"}.get(
                pattern[index], re.escape(pattern[index])
            )
            index += 1
    return re.fullmatch(token, value) is not None


def selected(value, includes=None, excludes=None):
    accepted = includes is None
    for pattern in includes or []:
        negative = pattern.startswith("!")
        if match(pattern[1:] if negative else pattern, value):
            accepted = not negative
    return accepted and not any(match(p, value) for p in excludes or [])


def filters(document, event, branch, activity):
    configured = document.get("on", {})
    if isinstance(configured, str):
        configured = {configured: {}}
    if isinstance(configured, list):
        configured = dict.fromkeys(configured, {})
    if event not in configured:
        return False, "event absent"
    rule = configured[event] or {}
    if event == "push" and any(key in rule for key in ("tags", "tags-ignore")):
        if not any(key in rule for key in ("branches", "branches-ignore")):
            return False, "tag-only workflow excludes a branch push"
    if event.startswith("pull_request"):
        activities = rule.get("types", ["opened", "synchronize", "reopened"])
        if activity not in activities:
            return False, "activity excluded"
    if not selected(branch, rule.get("branches"), rule.get("branches-ignore")):
        return False, "branch excluded"
    matches = [
        path
        for path in CHANGED
        if selected(path, rule.get("paths"), rule.get("paths-ignore"))
    ]
    if not matches:
        return False, "five-file change excluded by paths"
    return True, matches


def main():
    OUT.mkdir(exist_ok=True)
    paths = (
        git("ls-tree", "-r", "--name-only", BASE, ".github/workflows")
        .decode()
        .splitlines()
    )
    paths = [p for p in paths if p.endswith((".yml", ".yaml"))]
    unchanged = []
    for path in SCOUTS:
        before = yaml.load(git("show", f"{BASE}:{path}"), Loader=yaml.BaseLoader)
        after = yaml.load((WORK / path).read_bytes(), Loader=yaml.BaseLoader)
        normalized = copy.deepcopy(after)
        job = next(iter(normalized["jobs"].values()))
        if path == SCOUTS[0]:
            job["steps"] = [
                step
                for step in job["steps"]
                if step.get("name")
                != "Retain the exact read-only resource collector source"
            ]
        else:
            for step in job["steps"]:
                if "run" in step:
                    step["run"] = step["run"].replace(
                        "cp scripts/memory_cell/strong_rag_resource_snapshot.py "
                        "/tmp/memory-bf16-host-census/source/\n",
                        "",
                    )
        assert normalized == before, path
        unchanged.append(
            {"path": path, "all_fields_except_exact_source_retention_equal": True}
        )
    scenarios = [
        ("owner_push", "push", OWNER, None),
        ("child_push", "push", CHILD, None),
        ("child_pr_opened_to_owner", "pull_request", OWNER, "opened"),
        ("child_pr_sync_to_owner", "pull_request", OWNER, "synchronize"),
        ("child_pr_target_opened_to_owner", "pull_request_target", OWNER, "opened"),
        (
            "owner_pr_sync_to_main_at_this_snapshot",
            "pull_request",
            "main",
            "synchronize",
        ),
        (
            "owner_pr_target_sync_to_main_at_this_snapshot",
            "pull_request_target",
            "main",
            "synchronize",
        ),
    ]
    rows, affected = [], set()
    for path in paths:
        raw = (WORK / path).read_bytes()
        document = yaml.load(raw, Loader=yaml.BaseLoader)
        scenarios_out = {}
        for name, event, branch, activity in scenarios:
            passed, reason = filters(document, event, branch, activity)
            scenarios_out[name] = {"event_filters_match": passed, "reason": reason}
            if passed:
                affected.add(path)
        rows.append(
            {
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "event_filters": document.get("on"),
                "scenarios": scenarios_out,
            }
        )
    model = ".github/workflows/hepta-memory-strong-rag.yml"
    original_model = next(row for row in rows if row["path"] == model)
    assert not original_model["scenarios"]["owner_push"]["event_filters_match"]
    for path in sorted(affected | {model}):
        destination = OUT / "workflow-source" / Path(path).name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes((WORK / path).read_bytes())
    for path in SCOUTS:
        destination = OUT / "original-scout-source" / Path(path).name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(git("show", f"{BASE}:{path}"))
    report = {
        "schema": "hepta.resource-probe.static-workflow-filter-audit.v1",
        "base": BASE,
        "source_head": git("rev-parse", "HEAD").decode().strip(),
        "owner_branch": OWNER,
        "child_branch": CHILD,
        "exact_changed_paths": CHANGED,
        "parsed_workflows": len(rows),
        "scheduling_and_existing_steps_unchanged": unchanged,
        "owner_push_scout_matrix_jobs": 9,
        "model_workflow_owner_push_filters_match": False,
        "scope": (
            "Exact owner/child source snapshot event-filter analysis only. "
            "Does not execute job conditions or predict checks from another base/merge "
            "tree, repository policy, workflow_run chains, or prior queued jobs. The "
            "existing PR-to-main scenarios are reference analyses of this snapshot; "
            "GitHub's then-current merge and base workflow sources require recheck."
        ),
        "affected_source_files": sorted(affected | {model}),
        "workflows": rows,
    }
    (OUT / "STATIC_WORKFLOW_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "parsed_workflows": len(rows),
                "affected_source_files": len(affected | {model}),
                "scenarios": {
                    name: [
                        row["path"]
                        for row in rows
                        if row["scenarios"][name]["event_filters_match"]
                    ]
                    for name, *_ in scenarios
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
