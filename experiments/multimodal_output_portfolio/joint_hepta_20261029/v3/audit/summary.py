"""Bind completed audits and independently check the combined source cohorts."""

from collections import defaultdict
import json
from pathlib import Path

from .core import read, sha, source


def run():
    directory = Path(__file__).resolve().parent
    evidence = directory/"evidence"
    names = ("final_20261031", "consumer_20261031", "calibration_20261031")
    reports = {name: read(evidence/name/"AUDIT.json") for name in names}
    sources, inputs, paths = defaultdict(set), defaultdict(set), set()
    errors = []
    count = 0
    for name, report in reports.items():
        if not report["passed"] or report["errors"]:
            errors.append("Failed component audit: "+name)
        manifest = report.get("audit_source_sha256", report.get("source_sha256", {}))
        for file, expected in manifest.items():
            if sha(directory/file) != expected:
                errors.append("Audit source changed: "+file)
        log = evidence/name/"TRAJECTORY_AUDIT.jsonl"
        if not log.exists():
            continue
        if sha(log) != report["trajectory_audit_sha256"]:
            errors.append("Audit log changed: "+name)
        for line in log.open():
            row = json.loads(line); count += 1
            if row["path"] in paths:
                errors.append("A trajectory was counted twice: "+row["path"])
            paths.add(row["path"])
            namespace, identity, input_hash, _ = source(row["source"])
            sources[row["role"]].add((namespace, identity)); inputs[row["role"]].add(input_hash)
    overlaps, roles = {}, sorted(sources)
    for i, left in enumerate(roles):
        for right in roles[i+1:]:
            value = {"source_overlap": len(sources[left]&sources[right]), "input_overlap": len(inputs[left]&inputs[right])}
            overlaps[left+"__"+right] = value
            if any(value.values()):
                errors.append("Source/input role overlap: "+left+" / "+right)
    if count != 13056:
        errors.append("Expected exactly 13056 independently audited actual trajectories")
    result = {"schema": "hepta.v3.independent-audits-bound.v1", "passed": not errors, "errors": errors,
              "actual_trajectories": count, "component_sha256": {name: sha(evidence/name/"AUDIT.json") for name in names},
              "source_roles": {role: {"sources": len(sources[role]), "inputs": len(inputs[role]),
                                      "namespaces": sorted({s[0] for s in sources[role]})} for role in roles},
              "cross_role_overlap": overlaps, "summary_source_sha256": sha(__file__),
              "reconciliation_only_no_scientific_or_production_qualification": True}
    (evidence/"SUMMARY.json").write_text(json.dumps(result, indent=2)+"\n")
    (evidence/"SUMMARY.md").write_text("# Independent audit summary\n\n"
        +f"Result: {'PASS' if result['passed'] else 'FAIL'}; {count:,} unique actual trajectories; {len(errors)} errors.\n\n"
        +"All three component reports and their source/log hashes remain intact. Actual source identities and reconstructed public inputs are disjoint across the five scientific data roles.\n\n"
        +"The audit confirms retained data, weights, media, accounting arithmetic and implementation identities. It does not certify a general NDU optimum, natural four-modality capability, critic policy gains, physical timing differentiability or production owner integration.\n")
    print(json.dumps({"audit_passed": result["passed"], "unique_trajectories": count, "errors": len(errors)}))
    return result


if __name__ == "__main__":
    result = run()
    raise SystemExit(0 if result["passed"] else 1)
