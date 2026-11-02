"""Independent actual Git-blob membership and evaluation expense ledger."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root, base):
    checks, failures = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(label)

    run = base/"control/results/run001"
    gate = json.loads((run/"evaluation/BEFORE_TEST_GATE.json").read_text())
    publication = base/"publication/VALUE_PUBLICATION.json"
    published = json.loads(publication.read_text())
    check(sha(publication) == gate["publication_sha256"], "actual publication receipt bytes used by TEST gate")
    check(all(published[k] == gate[k] for k in ("local_head", "remote_head")), "same exact source/candidate publication")
    check(published["all_stage_root_trees_exact"] and published["ref_readback_matches"] and not published["value_test_opened_at_publication"], "root external readback and pre-TEST publication scope")
    head = gate["local_head"]
    entries = subprocess.check_output(["git", "ls-tree", "-rz", head], cwd=root).split(b"\0")
    committed = {r.split(b"\t", 1)[1].decode(): r.split(b"\t", 1)[0].split()[2].decode() for r in entries if r}
    check(subprocess.check_output(["git", "rev-parse", head+"^{tree}"], cwd=root, text=True).strip() == published["remote_root_tree"], "actual local Git tree equals externally read remote root tree")
    plan = json.loads((run/"PLAN.json").read_text())
    candidates = json.loads((run/"CANDIDATES.json").read_text())
    required = {run/"PLAN.json", run/"CANDIDATES.json"}
    required.update(root/name for name in plan["source_sha256"])
    for name, metadata in plan["packets"].items():
        check(sha(run/name) == metadata["sha256"], "TRAIN/VAL input packet bytes")
        required.add(run/name)
    core_run = root/plan["models_directory"]
    required.update((core_run/"PLAN.json", core_run/"CANDIDATES.json"))
    core_plan = json.loads((core_run/"PLAN.json").read_text())
    required.update(root/name for name in core_plan["source_sha256"])
    required.update(core_run/name for name in core_plan["input_sha256"])
    for item in candidates["models"]:
        directory = run/item["directory"]
        required.update(directory/name for name in item["files"])
        metadata = json.loads((directory/"CANDIDATE.json").read_text())
        core = root/metadata["model_directory"]
        required.update(core/name for name in ("TRAIN.json", "weights.pt", "NORMALIZATION.npz"))
    bindings = []
    for path in sorted(required):
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        name = str(path.relative_to(root))
        check(committed.get(name) == blob, "actual published original source/input/model/reader Git blob")
        bindings.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob})
    stages = []
    for path, expected in ((base/"joint_core/receipts/content_evaluation001", False), (base/"joint_core/receipts/content_evaluation002", True), (base/"control/receipts/evaluation001", True)):
        receipt = json.loads((path/"RECEIPT.json").read_text())
        check(receipt["task_success"] is expected and receipt["complete_task_cpu_coverage"] and receipt["source_unchanged_through_collection"], "retained actual evaluation outcome and complete CPU envelope")
        check(sha(path/"SUPERVISION.json") == receipt["supervision_sha256"], "actual evaluation supervision bytes")
        command = receipt["command"]
        if path.parent.parent.name == "joint_core":
            check("experiments.hcsn_v13_followup_20261102.joint_core.operations.evaluate_content" in command and "--out" in command and command[command.index("--out")+1].endswith(path.name), "actual static evaluation module and output")
        else:
            check("experiments.hcsn_v13_followup_20261102.control.campaign" in command and "evaluate" in command, "actual dynamic evaluation command")
        if expected:
            check(receipt["enclosing_supervisor_exit_code"] == 0, "successful actual evaluation exit")
        else:
            check("Current byte is not its published Git blob: recovered/v3/experiments/hcsn_free_boundary_v1/datasets.py" in (path/"stderr.log").read_text(), "retained fail-closed original dependency publication failure")
        stages.append({"directory": str(path.relative_to(root)), "task_success": expected, "cpu_seconds": receipt["complete_supervisor_wait4"]["cpu_seconds"]})
    check(json.loads((base/"joint_core/results/content_evaluation002/RESULT.json").read_text())["condition_records"] == 96, "static completed condition count")
    check(json.loads((run/"evaluation/SUMMARY.json").read_text())["executions"] == 1944, "dynamic completed episode count")
    return {"checks": checks, "all_checks_passed": not failures, "failed_examples": failures, "published_git_files": len(bindings), "bindings": bindings, "stages": stages, "disjoint_evaluation_cpu_seconds": sum(s["cpu_seconds"] for s in stages), "scope": "Independent local Git-object computation against the exact externally verified equivalent remote tree; no independent network readback; failed/successful outer evaluation envelopes counted once"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.base.resolve())
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "bindings"}))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
