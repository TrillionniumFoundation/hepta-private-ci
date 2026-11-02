"""Bind evaluation to root's read-back publication and committed candidate bytes."""

import hashlib
import json
from pathlib import Path
import subprocess
from ..campaign import ROOT, read_plan, sha


def require_publication(run, receipt_path, source_head, candidate_head):
    receipt = json.loads(receipt_path.read_text())
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if (receipt.get("local_head") != head or receipt.get("remote_head") != candidate_head
            or receipt.get("all_stage_root_trees_exact") is not True
            or source_head not in (receipt.get("base_remote"), receipt.get("source_remote_head"))):
        raise RuntimeError("Actual current Git/publication identity differs")
    plan = read_plan(run)
    candidates_path = run/"CANDIDATES.json"
    candidates = json.loads(candidates_path.read_text())
    if candidates["plan_sha256"] != sha(run/"PLAN.json"):
        raise RuntimeError("Candidate/training plan identity differs")
    p = plan["protocol"]
    expected = {(task, family, seed) for task in p["tasks"] for family in p["families"] for seed in p["seeds"]}
    observed = [(m["task"], m["family"], m["seed"]) for m in candidates["models"]]
    if len(observed) != 36 or len(set(observed)) != 36 or set(observed) != expected:
        raise RuntimeError("Candidate roster is incomplete or duplicated")
    required = {ROOT/name for name in plan["source_sha256"]}
    required.update(run/name for name in plan["input_sha256"])
    required.update((run/"PLAN.json", candidates_path, Path(__file__),
                     Path(__file__).with_name("evaluate_content.py"),
                     Path(__file__).with_name("EVALUATION_PROTOCOL.json")))
    for entry in candidates["models"]:
        directory = run/entry["directory"]
        if sha(directory/"TRAIN.json") != entry["train_metadata_sha256"]:
            raise RuntimeError("Frozen training metadata differs")
        meta = json.loads((directory/"TRAIN.json").read_text())
        if (meta["weights_sha256"] != entry["weights_sha256"] or sha(directory/"weights.pt") != entry["weights_sha256"]
                or sha(directory/"NORMALIZATION.npz") != meta["normalization_sha256"]):
            raise RuntimeError("Frozen weight or normalization differs")
        required.update(directory/name for name in ("TRAIN.json", "weights.pt", "NORMALIZATION.npz"))
    paths = sorted(str(path.resolve().relative_to(ROOT)) for path in required)
    tree = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "-z", "HEAD", "--", *paths])
    committed = {}
    for entry in tree.split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            mode, kind, blob = metadata.split()
            committed[path.decode()] = (mode.decode(), kind.decode(), blob.decode())
    checked = []
    for name in paths:
        path = ROOT/name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Candidate source/input must be regular committed file")
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        if committed.get(name) not in (("100644", "blob", blob), ("100755", "blob", blob)):
            raise RuntimeError("Current byte is not its published Git blob: "+name)
        checked.append({"path": name, "git_blob": blob, "sha256": hashlib.sha256(raw).hexdigest()})
    return {"local_head": head, "remote_head": candidate_head, "source_remote_head": source_head,
            "publication_receipt_sha256": sha(receipt_path), "candidate_manifest_sha256": sha(candidates_path),
            "all_required_files_are_committed_exact_bytes": True, "checked_files": checked}
