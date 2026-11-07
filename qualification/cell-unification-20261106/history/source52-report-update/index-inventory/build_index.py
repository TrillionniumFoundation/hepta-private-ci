"""Create an isolated integrity inventory from immutable prior rows and sealed additions.

This does not overwrite the formal INDEX, run native tools, or infer gate results.
The caller supplies an explicit frozen facts file and exact root-verified plans.
"""
from pathlib import Path
import argparse
import hashlib
import json


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def require(value, message):
    if not value:
        raise RuntimeError(message)


def write_new(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    require(not path.exists() or path.read_bytes() == raw, "create-only output differs: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), **pin(raw)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", required=True)
    parser.add_argument("--plan", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path("hepta-cell/qualification/cell-unification-20261106")
    prefix = "qualification/cell-unification-20261106/native-evidence/"
    previous_path = root / "history/source52-report-update/NATIVE-EVIDENCE-INDEX.json"
    previous_raw = previous_path.read_bytes()
    previous_pin = pin(previous_raw)
    require(previous_pin == {
        "bytes": 1204766,
        "sha256": "eec856c07862186f583963794cfaa951882a5a38321dc042cdfa62d3837fae8e",
        "git_blob": "e212dd0f48246ad549de13a610586e50654d6193",
    }, "prior INDEX is not the exact checkpoint5 object")
    previous = json.loads(previous_raw)
    prior_rows = previous["artifacts"]
    require(len(prior_rows) == len({r["path"] for r in prior_rows}) == 1673, "wrong prior row inventory")
    prior_leaves_path = Path("source52-index-preparation/CHECKPOINT5-NATIVE-GIT-LEAVES.json")
    prior_leaves_raw = prior_leaves_path.read_bytes()
    prior_leaves = json.loads(prior_leaves_raw)
    require(prior_leaves["checkpoint_commit"] == "e904dc657d8f511380178d32f8563175ce7bfaa8"
            and prior_leaves["report_tree"] == "01433bda50236b306199e9c0fa767583d7fd1d96",
            "wrong prior actual Git identity")
    actual = {r["path"]: r for r in prior_leaves["files"]}
    require(len(actual) == len(prior_leaves["files"]) == 1724, "wrong prior native Git count")
    historical_bindings = []
    for row in prior_rows:
        entry = actual[row["path"]]
        require(entry["mode"] == "100644" and entry["bytes"] == row["bytes"],
                "prior row size or mode differs from actual Git: " + row["path"])
        if "git_blob" in row:
            require(row["git_blob"] == entry["git_blob"], "prior row Git identity differs")
        historical_bindings.append({
            "path": row["path"],
            "historical_sha256": row["sha256"],
            "published_git_blob": entry["git_blob"],
            "published_size": entry["bytes"],
            "raw_bytes_re_read_this_inventory": False,
            "source_index_git_blob": previous_pin["git_blob"],
            "source_checkpoint": prior_leaves["checkpoint_commit"],
        })
    known_paths = {r["path"] for r in prior_rows}
    prior_extra_refs = [
        {**r, "raw_sha256_observed_this_inventory": None, "raw_bytes_re_read_this_inventory": False}
        for name, r in sorted(actual.items()) if name not in known_paths and name != "INDEX.json"
    ]
    require(len(prior_extra_refs) == 50, "unexpected prior actual paths outside old raw inventory")
    observations = []
    seals = []
    plan_pins = []
    for name in args.plan:
        plan_raw = Path(name).read_bytes()
        plan = json.loads(plan_raw)
        require(plan["file_count"] == len(plan["files"]), "plan count differs")
        require(plan["artifact_bytes"] == sum(r["bytes"] for r in plan["files"]), "plan byte sum differs")
        plan_pins.append({"path": name, **pin(plan_raw)})
        group_seen = set()
        for row in plan["files"]:
            require(row["repo_path"].startswith(prefix), "plan path is outside native evidence")
            rel = row["repo_path"][len(prefix):]
            require(rel not in known_paths and rel not in group_seen, "new path overlaps immutable prior data")
            require(row["mode"] == "100644", "unexpected artifact Git mode")
            raw = Path(row["local_path"]).read_bytes()
            require(pin(raw) == {k: row[k] for k in ("bytes", "sha256", "git_blob")},
                    "new artifact changed: " + rel)
            current = {"path": rel, **pin(raw)}
            observations.append(current)
            group_seen.add(rel)
            if rel.endswith("/ATTACHMENT-MANIFEST.json") or rel.endswith("/HANDOFF-MANIFEST.json"):
                if len(Path(rel).parts) == 2:
                    seals.append(current)
        known_paths.update(group_seen)
    require(len({r["path"] for r in observations}) == len(observations), "new plan groups overlap")
    facts_raw = Path(args.facts).read_bytes()
    facts = json.loads(facts_raw)
    identity = facts["source_identity"]
    require(identity["commit"] == "1e0910becc37383e6d17ecf861ea844fd07d8862"
            and identity["tree"] == "211f15baff19095e8c98bcea2b0ed99ca2270ade"
            and identity["changed_paths"] == 195, "facts source identity mismatch")
    require(facts["science"] == "HOLD" and facts["authority"] == "DENY_ALL", "inventory cannot grant adoption")
    project = facts["last_closed_complete_project_gate"]
    require(project["gate"] == "r28" and project["exit_code"] == 0
            and project["counts"] == {"PASS": 1564, "FAIL": 0, "TIMEOUT": 0}
            and project["reported_skipped"] == 3, "unexpected closed project gate")
    require(project["closure"] in known_paths, "closed project formal group is missing")
    observations.sort(key=lambda r: r["path"])
    all_rows = prior_rows + observations
    index = {
        "schema": "hepta.cell-unification-evidence-index.v4",
        "status": "FROZEN_INTEGRITY_INVENTORY",
        "scope": "Prior 1673 raw-hash rows retain their original values and actual checkpoint5 Git bindings. Only observed_local_artifacts were rehashed now. The 50 additional inherited Git paths have no new raw-byte claim. Gate facts have separate closed original receipts.",
        "source_identity": identity,
        "last_closed_workspace_gate": facts["last_closed_workspace_gate"],
        "last_closed_complete_project_gate": project,
        "prior_source51_r26_result": facts["prior_source51_r26_result"],
        "candidate_state": facts["candidate_state"],
        "current_workspace_snapshot": facts["current_workspace_snapshot"],
        "snapshot_basis": facts["snapshot_basis"],
        "facts_input": {"path": args.facts, **pin(facts_raw)},
        "previous_index": {
            "path": "../history/source52-report-update/NATIVE-EVIDENCE-INDEX.json",
            **previous_pin,
            "artifact_checkpoint": prior_leaves["checkpoint_commit"],
            "report_tree": prior_leaves["report_tree"],
            "artifact_count": len(prior_rows),
        },
        "prior_actual_git_leaves": {"path": str(prior_leaves_path), **pin(prior_leaves_raw)},
        "source_ledger_snapshot": facts["source_ledger_snapshot"],
        "artifacts": all_rows,
        "historical_artifact_git_bindings": historical_bindings,
        "additional_inherited_git_paths_not_in_prior_raw_inventory": prior_extra_refs,
        "observed_local_artifacts": observations,
        "verified_local_group_or_file_seals": seals,
        "addition_plans": plan_pins,
        "unmaterialized_binary_references": previous["unmaterialized_binary_references"],
        "unsealed_local_paths_not_indexed": [],
        "self_excluded": True,
        "formal_INDEX_written": False,
        "all_prior_Git_paths_retained_by_publication_plan_required": True,
        "current_raw_hash_count": len(observations),
        "historical_artifact_count": len(prior_rows),
        "artifact_count": len(all_rows),
        "inherited_additional_git_reference_count": len(prior_extra_refs),
        "unmaterialized_reference_count": len(previous["unmaterialized_binary_references"]),
        "qualification_not_inferred_from_integrity": True,
        "science": "HOLD",
        "authority": "DENY_ALL",
    }
    output = Path(args.output)
    index_pin = write_new(output / "INDEX.candidate.json", index)
    readback = {
        "schema": "hepta.root-source52-index-independent-construction.v1",
        "index": index_pin,
        "prior1673_rows_preserved_exact": index["artifacts"][:1673] == previous["artifacts"],
        "prior_actual_native_Git_paths": len(actual),
        "additional_prior_git_refs_without_new_raw_claim": len(prior_extra_refs),
        "new_raw_hashed_rows": len(observations),
        "total_raw_hash_inventory_rows": len(all_rows),
        "source52_project_r28_closed": True,
        "workspace_qualification_only_from_supplied_facts": True,
        "formal_INDEX_not_overwritten": True,
        "science": "HOLD",
        "authority": "DENY_ALL",
    }
    report_pin = write_new(output / "ROOT-CONSTRUCTION-READBACK.json", readback)
    print(json.dumps({"index": index_pin, "readback": report_pin}))


if __name__ == "__main__":
    main()
