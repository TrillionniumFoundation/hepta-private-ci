"""Audit frozen files and existing outputs without training or rerunning models."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent.parent


def read(path):
    return json.loads(path.read_text())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def checked_files(base, inventory):
    for name, expected in inventory.items():
        data = (base / name).read_bytes()
        assert len(data) == expected["bytes"], name
        assert digest(data) == expected["sha256"], name
        if "git_blob_sha1" in expected:
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert git_blob == expected["git_blob_sha1"] == expected["expected_git_blob_sha1"], name


def audit():
    freeze = read(ROOT / "FREEZE.json")
    assert digest((ROOT / "FREEZE.json").read_bytes()) == "01c4327b3f950b821861bb5ed54c592aa385e277260b9ab203059e765b0c8244"
    checked_files(ROOT, freeze["files"])
    checked_files(ROOT.parent, freeze["source_inventory"])
    source = read(ROOT / "SOURCE.json")
    checked_files(REPOSITORY, source["materialized_base_files"])
    held = ROOT / "evidence/independent-held-v1"
    checked_files(held, source["independent_held_copy_files"])
    raw = (held / "independent_held_requests.jsonl").read_bytes()
    assert digest(raw) == freeze["independent_held_sha256"]
    rows = [json.loads(line) for line in raw.splitlines()]
    requests = [json.loads(line) for line in (held / "results/serving_requests.jsonl").read_text().splitlines()]
    assert len(rows) == len(requests) == 180
    assert len({row["utterance"] for row in rows}) == 180
    assert all(set(row) == {"utterance", "series_name", "date"} for row in requests)
    assert all(left["utterance"] == right["utterance"] for left, right in zip(rows, requests, strict=True))
    summary = read(held / "results/SUMMARY.json")
    held_counts = {}
    for name, expected in summary["results"].items():
        decisions = [json.loads(line) for line in (held / "results" / (name + ".stdout.jsonl")).read_text().splitlines()]
        assert len(decisions) == len(rows)
        assert not any("error" in row for row in decisions)
        known = [(gold, result) for gold, result in zip(rows, decisions, strict=True) if gold["expected_operation"]]
        ood = [(gold, result) for gold, result in zip(rows, decisions, strict=True) if gold["expected_operation"] is None]
        correct = sum(result["accepted_intent"] == gold["expected_operation"] for gold, result in known)
        wrong = sum(result["accepted_intent"] not in (None, gold["expected_operation"]) for gold, result in known)
        false_accept = sum(result["accepted_intent"] is not None for _, result in ood)
        counts = {"correct": correct, "known_wrong": wrong, "known_rejected": len(known) - correct - wrong,
                  "ood_false_accept": false_accept, "gate_pass": correct >= 96 and false_accept <= 3}
        assert len(known) == 120 and len(ood) == 60
        assert all(expected[key] == value for key, value in counts.items()), name
        held_counts[name] = counts
    adaptive = read(ROOT / "evidence/oracle-adaptive-v1.1/RESULTS.json")
    assert adaptive["protocol_sha256"] == digest((ROOT / "ADAPTIVE_PROTOCOL.json").read_bytes())
    receipt_totals = []
    for run in ("oracle-adaptive", "oracle-adaptive-v1.1"):
        directory = ROOT / "evidence" / run
        receipts = [read(path) for path in sorted(directory.glob("receipt-*.json"))]
        assert len(receipts) == 14
        active = identity(read(directory / "checkpoint-00.json"))
        for receipt in receipts:
            candidate = read(directory / receipt["candidate_file"])
            assert receipt["before_sha256"] == active
            assert receipt["candidate_sha256"] == identity(candidate)
            if receipt["accepted"]:
                active = identity(candidate)
                assert receipt["metrics"]["old_exact"] == receipt["metrics"]["old_total"] == 48
            assert receipt["active_sha256_after"] == active
        assert identity(read(directory / "FINAL_STATE.json")) == active
        receipt_totals.append({"run": run, "candidates": len(receipts),
            "accepted": sum(row["accepted"] for row in receipts),
            "candidate_evaluation_primitive_calls": sum(row["evaluation_primitive_calls"] for row in receipts),
            "accepted_migration_bytes": sum(row["migration_bytes"] for row in receipts)})
    final = adaptive["final"]
    assert final["state_sha256"] == active
    assert final["metrics"] == adaptive["static_same_program_baseline"]["metrics"]
    assert final["metrics"]["old_exact"] == 48 and final["metrics"]["new_exact"] == 24
    delivery = ROOT / "DELIVERY_MANIFEST.json"
    if delivery.exists():
        manifest = read(delivery)
        checked_files(ROOT, manifest["files"])
        current = {str(path.relative_to(ROOT)) for path in ROOT.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts and path != delivery}
        assert current == set(manifest["files"]), "delivery file inventory drift"
    return {"schema": "memory-cell-v6.evidence-audit.v1", "freeze_verified": True,
            "base_git_blobs_verified": len(source["materialized_base_files"]),
            "held_files_verified": len(source["independent_held_copy_files"]),
            "models_or_training_rerun": False, "held_counts": held_counts,
            "mutation_receipts": receipt_totals, "delivery_manifest_verified": delivery.exists()}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
