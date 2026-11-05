from __future__ import annotations

import ast
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import posixpath
import re
import subprocess

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent.parent
SNAP = ROOT / "snapshot-1"
AUDIT = WORK / "hepta-audit-fourth"


def identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def load(path: Path):
    return json.loads(path.read_bytes())


def main() -> None:
    registry = load(SNAP / "artifact-registry.json")
    index = load(SNAP / "deliverables/fourth-evidence-index.json")
    ledger = load(SNAP / "deliverables/current-blockers.json")
    assert registry == index["artifacts"]
    assert len(registry) == index["artifact_count"] == 884
    assert len({x["path"] for x in registry}) == len(registry)
    immutable = []
    for name in ["inputs/pre-full-fb9-report-update/current-blockers.json",
                 "../research-audit/fourth-report-post-three-repairs-review-20261105/preimages/current-blockers.json"]:
        path = AUDIT / name
        previous = load(path)
        before = {x["id"]: x for x in previous["items"]}
        now = {x["id"]: x for x in ledger["items"]}
        assert before.keys() == now.keys()
        for field in ["status", "original_exit_condition_zh", "closure_class"]:
            assert all(before[key][field] == now[key][field] for key in before), field
        immutable.append({"path": str(path), **identity(path.read_bytes()),
                          "all_23_status_exit_closure_equal": True})
    status_counts = Counter(x["closure_class"] for x in ledger["items"])
    assert status_counts == {"CLOSED_SCOPED": 8, "OPEN": 14, "SCIENTIFIC_HOLD": 1}
    targets = [row for row in registry if Path(row["path"]).suffix in {".md", ".json"}]
    wanted = {row["blob"] for row in targets}
    layout_path = AUDIT / "inputs/passive-source-evidence-repository-layout.json"
    layout = load(layout_path)
    wanted_bodies = wanted | {row["blob"] for row in layout["mappings"]}
    found = {}
    candidate_paths = subprocess.check_output(
        ["rg", "--files", "hepta-audit-fourth", "research-audit", "architecture-audit", "ci-audit"],
        cwd=WORK, text=True,
    ).splitlines()
    candidate_count = 0
    candidate_bytes = 0
    for name in candidate_paths:
        path = WORK / name
        if path.suffix not in {".json", ".md", ".txt", ".patch", ".py", ".rs"}:
            continue
        try:
            if path.stat().st_size > 16_000_000:
                continue
            body = path.read_bytes()
        except FileNotFoundError:
            continue
        candidate_count += 1
        candidate_bytes += len(body)
        sha = identity(body)["blob"]
        if sha in wanted_bodies and sha not in found:
            found[sha] = {"path": name, "kind": "existing_exact_local_body", **identity(body)}
    for cache in (WORK / "research-audit/workflow-reference-review").glob("fetched-registry-batch-*.json"):
        j = load(cache)
        for row in j["entries"]:
            b = row["body_utf8"].encode()
            sha = identity(b)["blob"]
            assert sha == row["blob"]
            if sha in wanted and sha not in found:
                dest = ROOT / "cached-bodies" / (sha + ".txt")
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(b)
                found[sha] = {"path": str(dest.relative_to(WORK)), "kind": "previously_fetched_exact_body", **identity(b)}
    verifier = AUDIT / "inputs/hepta-docs.py.txt"
    assert identity(verifier.read_bytes())["blob"] == "0d65aa4dee439e58ef124d99f4d422affdfae82f"
    pattern = None
    for node in ast.parse(verifier.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORKFLOW_REFERENCE_RE" for t in node.targets):
            pattern = ast.literal_eval(node.value.args[0])
    assert pattern
    regex = re.compile(pattern)
    tree_path = AUDIT / "inputs/cabc-tree.json"
    tree = load(tree_path)
    assert tree["truncated"] is False and tree["sha"] == "b2d7f038d6d88156bc6a4cb29c8703f69b808f29"
    paths = {row["path"]: row["sha"] for row in tree["tree"] if row["type"] == "blob"}
    cohort_path = AUDIT / "source-cohort-diff-checks.json"
    cohorts = load(cohort_path)
    for cohort in cohorts:
        for row in cohort["files"]:
            if row["status"] == "removed":
                paths.pop(row["path"], None)
            else:
                paths[row["path"]] = row["sha"]
    prefix = "qualification/r3-audit-repair-20261104/"
    planned_paths = set(paths) | {prefix + row["path"] for row in registry}
    planned_paths |= {prefix + p.name for p in (SNAP / "deliverables").iterdir()}
    extra = []
    for p in sorted((SNAP / "deliverables").iterdir()):
        if p.suffix in {".md", ".json"}:
            extra.append({"path": p.name, **identity(p.read_bytes()), "local_path": str(p)})
    scans = []
    workflow_refs = []
    missing_bodies = []
    for row in targets + extra:
        local = row.get("local_path") or found.get(row["blob"], {}).get("path")
        if local is None:
            missing_bodies.append(row)
            continue
        p = Path(local)
        if not p.is_absolute():
            p = WORK / p
        b = p.read_bytes()
        assert identity(b)["blob"] == row["blob"]
        text = b.decode()
        matches = []
        for m in regex.finditer(text):
            match = {"artifact_path": row["path"], "blob": row["blob"],
                     "line": text.count("\n", 0, m.start()) + 1,
                     "workflow_path": m.group("path"), "exists": m.group("path") in paths}
            matches.append(match)
            workflow_refs.append(match)
        scans.append({"path": row["path"], **identity(b), "local_path": str(p),
                      "workflow_references": len(matches)})
    markdown_links = []
    for p in sorted((SNAP / "deliverables").glob("*.md")):
        text = p.read_text()
        for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            raw = m.group(1).split("#", 1)[0]
            if not raw or re.match(r"^[a-z]+:", raw) or raw.startswith("//"):
                continue
            target = posixpath.normpath(prefix + raw)
            markdown_links.append({"file": p.name, "line": text.count("\n", 0, m.start()) + 1,
                                   "href": raw, "repository_target": target, "exists_in_planned_tree": target in planned_paths})
    by_path = {row["path"]: row for row in registry}
    assert len(layout["mappings"]) == 19
    for row in layout["mappings"]:
        entry = by_path[row["repository_path"]]
        assert entry["blob"] == row["blob"]
        assert row["repository_path"].endswith(".rs.source.txt")
        assert row["logical_evidence_source_path"] not in by_path
        body_identity = found[row["blob"]]
        assert body_identity["bytes"] == row["bytes"]
        assert body_identity["sha256"] == row["sha256"]
    assert not any(row["path"].endswith(".rs") for row in registry)
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Frozen six-file report/ledger/index/registry snapshot; registry .md/.json literal workflow references and three main Markdown relative links. Not a full docs gate invocation.",
        "registry_index_exact_equal": True, "registry_entries": len(registry),
        "duplicate_registry_paths": False, "immutable_ledger_comparisons": immutable,
        "closure_class_counts": dict(status_counts),
        "local_candidate_files_read": candidate_count, "local_candidate_bytes_read": candidate_bytes,
        "registry_md_json_entries": len(targets), "registry_unique_md_json_blobs": len(wanted),
        "source_cohort_map": {"path": str(cohort_path), **identity(cohort_path.read_bytes()), "cohorts": len(cohorts)},
        "verifier": {"path": str(verifier), **identity(verifier.read_bytes()), "pattern": pattern},
        "missing_bodies": missing_bodies, "scanned_files": scans,
        "workflow_references": workflow_refs,
        "missing_workflow_references": [x for x in workflow_refs if not x["exists"]],
        "main_markdown_relative_links": markdown_links,
        "missing_main_markdown_links": [x for x in markdown_links if not x["exists_in_planned_tree"]],
        "passive_source_layout": {"path": str(layout_path), **identity(layout_path.read_bytes()), "all_19_mappings_keep_blob_and_are_passive": True, "all_19_exact_body_bytes_and_sha256_verified": True, "no_registry_path_ends_rs": True},
        "limits": ["No source, registry or root deliverable was changed.", "Registry/appended source changes after the snapshot are outside this receipt.", "Historical scope strings on frozen old artifacts are not interpreted as current execution state.", "Missing original file bodies, if any, prevent a complete literal-reference scan and are explicit."],
    }
    (ROOT / "structural-reference-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["registry_entries", "registry_md_json_entries", "registry_unique_md_json_blobs", "closure_class_counts", "missing_bodies", "missing_workflow_references", "missing_main_markdown_links"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
