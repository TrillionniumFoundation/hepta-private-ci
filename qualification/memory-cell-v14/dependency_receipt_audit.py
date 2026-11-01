"""Post hoc audit of exact CI source-cut/read receipts, not a new experiment."""

import argparse
import json
from pathlib import Path

from structural_gate import digest, read, source_provenance


def audit(report):
    candidates = {c["artifact"]: c for c in report["candidates"]}
    if len(candidates) != len(report["candidates"]):
        raise ValueError("ambiguous candidate artifact identities")
    for candidate in candidates.values():
        if (len(candidate["source_cut"]["records"]) != 1 or candidate["fresh_initialization"] is not True
                or candidate["parent_artifact"] is not None):
            raise ValueError("candidate does not have the declared clean single-source initialization")
    modes = {"learned": 0, "fallback": 0, "refused": 0}
    for stage in report["stages"]:
        for trace in stage["traces"]:
            receipt = trace["receipt"]
            mode = receipt["mode"]
            modes[mode] += 1
            if mode == "learned":
                candidate = candidates[receipt["artifact"]]
                cut = candidate["source_cut"]["records"][0]
                actual = {"source_id": receipt["source_id"], "revision": receipt["source_revision"],
                          "body_sha256": receipt["source_body_sha256"]}
                if (actual != cut or receipt["source_version"] != candidate["source_version"]
                        or receipt["source_active"] is not True or candidate["status"] != "published"):
                    raise ValueError("learned read served an unpublished or mismatching source cut")
            elif mode == "fallback":
                if (receipt["source_active"] is not True or not receipt["source_id"].startswith("project:")
                        or receipt["fallback"] != "current_exact_project_source" or receipt["artifact"] is not None):
                    raise ValueError("fallback is not an active current-project-source read")
            elif receipt["source_active"] is not False or receipt["source_id"] != "project:amber":
                raise ValueError("an unrelated source was refused during the scoped revocation")
    return {"project_seed": report["project_seed"], "fixed_skill_seed": report["fixed_skill_seed"],
            "candidate_single_source_cuts_checked": len(candidates), "read_receipts_checked": modes,
            "all_declared_dependencies_and_read_fences_match": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite the audit")
    report = {"schema": "hepta.memory.ci-dependency-receipt-audit.v14", "source_provenance": source_provenance(args.isolation),
              "source_sha256": digest(__file__), "runs": [audit(read(p)) for p in sorted(args.isolation.glob("seed-*/RESULTS.json"))],
              "scope": "Derived after the experiment from original declared source cuts and read receipts; not a new trial, generalization sample, native authority, or weight-unlearning proof.",
              "fixed_partition_control": True, "learned_gradient_splitting_credit": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "runs": report["runs"]}))


if __name__ == "__main__":
    main()
