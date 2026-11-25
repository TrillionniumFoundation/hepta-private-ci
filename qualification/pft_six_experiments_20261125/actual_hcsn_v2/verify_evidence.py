"""Verify archive bytes, every candidate, and test ordering without loading Torch."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tarfile
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(root, capsule=None):
    root = Path(root)
    start = time.perf_counter()
    index_path = root / "evidence_archives/ARCHIVE_INDEX.json"
    index = json.loads(index_path.read_text())
    files, archives = {}, []
    for bundle in index["bundles"]:
        path = root / bundle["path"]
        raw = path.read_bytes()
        if len(raw) > 512000 or len(raw) != bundle["bytes"] or digest(raw) != bundle["sha256"]:
            raise ValueError("Archive byte/size identity mismatch")
        expected = {m["path"]: m for m in bundle["members"]}
        if len(expected) != len(bundle["members"]):
            raise ValueError("Duplicate member declarations")
        with tarfile.open(path, "r:xz") as archive:
            if set(archive.getnames()) != set(expected) or len(archive.getnames()) != len(expected):
                raise ValueError("Archive membership mismatch")
            for name, binding in expected.items():
                info = archive.getmember(name)
                if not info.isfile() or name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Unexpected archive member type/path")
                data = archive.extractfile(info).read()
                if len(data) != binding["bytes"] or digest(data) != binding["sha256"]:
                    raise ValueError("Member identity mismatch")
                if name in files and files[name] != data:
                    raise ValueError("Conflicting duplicate payload")
                files[name] = data
        archives.append({"path": bundle["path"], "sha256": digest(raw), "members": len(expected)})
    read = lambda name: json.loads(files[name])
    protocol = read("FORMAL_PROTOCOL_v2.json")
    protocol_sha = digest(files["FORMAL_PROTOCOL_v2.json"])
    seal = read("GLOBAL_CANDIDATE_SEAL.json")
    seal_sha = digest(files["GLOBAL_CANDIDATE_SEAL.json"])
    evaluation = read("formal_v2_test/RESULT.json")
    opened = read("formal_v2_test/OPEN_RECEIPT.json")
    receipt = read("TEST_EXECUTION.json")
    if protocol_sha != "aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8":
        raise ValueError("Unexpected registered protocol")
    if seal_sha != "a447b724f6459625b0e9c5e15e9dca5bbaad439af5c433391c7b34e9a9df88ee":
        raise ValueError("Unexpected externally committed candidate seal")
    for name, expected in protocol["source_hashes"].items():
        if digest(files[name]) != expected:
            raise ValueError("Frozen source changed")
    for obj in (seal, evaluation, opened):
        if obj["protocol_sha256"] != protocol_sha:
            raise ValueError("Phase protocol mismatch")
    if opened["seal_sha256"] != seal_sha or evaluation["seal_sha256"] != seal_sha:
        raise ValueError("Evaluation seal mismatch")
    if datetime.fromisoformat(opened["test_first_generated_after_utc"]) <= datetime.fromisoformat(seal["frozen_utc"]):
        raise ValueError("Test ordering violation")
    bound = {r["name"]: r for r in seal["rows"]}
    if len(bound) != len(seal["rows"]) or len(bound) != 168:
        raise ValueError("Incomplete or duplicated seal")
    rows = {r["name"]: r for r in evaluation["rows"]}
    if len(rows) != len(evaluation["rows"]) or set(rows) != set(bound):
        raise ValueError("Incomplete or duplicated test roster")
    for name, binding in bound.items():
        prefix = "formal_v2_training/" + name + "/"
        result_bytes = files[prefix + "RESULT.json"]
        result = json.loads(result_bytes)
        if digest(result_bytes) != binding["result_sha256"] or result["case"] != binding["case"]:
            raise ValueError("Training result mismatch")
        if digest(files[prefix + "HISTORY.json"]) != result["history_sha256"]:
            raise ValueError("Selection history mismatch")
        if binding.get("candidate_sha256") and digest(files[prefix + "candidate.pt"]) != binding["candidate_sha256"]:
            raise ValueError("Candidate weight mismatch")
        evaluated = rows[name]
        if evaluated["status"] == "EVALUATED":
            if evaluated["candidate_sha256"] != binding["candidate_sha256"]:
                raise ValueError("Evaluator candidate mismatch")
            if digest(files["formal_v2_test/" + name + ".npz"]) != evaluated["predictions_sha256"]:
                raise ValueError("Prediction byte mismatch")
    if digest(files["formal_v2_test/test_data.npz"]) != evaluation["test_artifact_sha256"]:
        raise ValueError("Saved test artifact mismatch")
    terminals = []
    for shard in range(4):
        terminal = read(f"formal_v2_training/TRAINING_TERMINALS_shard_{shard}.json")
        names = [r["case"] for r in terminal["rows"]]
        if names != protocol["execution"]["shards"][str(shard)] or terminal["protocol_sha256"] != protocol_sha:
            raise ValueError("Worker assignment mismatch")
        terminals += names
    if len(terminals) != len(set(terminals)) or set(terminals) != set(bound):
        raise ValueError("Global worker partition mismatch")
    capsule_check = {"requested": capsule is not None, "expected_sha256": index["capsule_reused_sha256"]}
    if capsule is not None:
        actual = digest(Path(capsule).read_bytes())
        if actual != index["capsule_reused_sha256"]:
            raise ValueError("Physical runtime capsule mismatch")
        capsule_check["actual_sha256"] = actual
    return {"status": "BYTE_AND_BINDING_CHECKS_PASSED", "archive_index_sha256": digest(index_path.read_bytes()),
            "archive_count": len(archives), "unique_members": len(files), "candidates": len(bound),
            "evaluated_rows": sum(r["status"] == "EVALUATED" for r in rows.values()),
            "protocol_sha256": protocol_sha, "seal_sha256": seal_sha,
            "source_git_anchor": seal["source_git_anchor"],
            "candidate_git_anchor_reported_by_orchestrator": receipt["candidate_git_anchor"],
            "capsule": capsule_check, "wall_s": time.perf_counter() - start,
            "verifier_source_sha256": digest(Path(__file__).read_bytes()),
            "scope": "raw bytes, local source and receipt bindings; no Torch deserialization or scientific retraining",
            "external_git_commit_existence_requeried": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--capsule")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = verify(args.root, args.capsule)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(text)
