"""Read-only byte audit of the registered HCSN v2 candidates and predictions."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

PROTOCOL_SHA = "aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8"
SEAL_SHA = "a447b724f6459625b0e9c5e15e9dca5bbaad439af5c433391c7b34e9a9df88ee"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    with Path(path).open("rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size < 128 * 1024**2,
                "bounded regular artifact required")
        result = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "artifact changed during audit")
    return result


def check(path, expected):
    actual = digest(path)
    require(actual == expected, "artifact SHA mismatch: " + Path(path).name)
    return actual


def read(path):
    return json.loads(Path(path).read_text())


def run(root, output):
    require(not output.exists(), "audit receipt already exists")
    check(root / "FORMAL_PROTOCOL_v2.json", PROTOCOL_SHA)
    check(root / "GLOBAL_CANDIDATE_SEAL.json", SEAL_SHA)
    protocol = read(root / "FORMAL_PROTOCOL_v2.json")
    seal = read(root / "GLOBAL_CANDIDATE_SEAL.json")
    for name, expected in protocol["source_hashes"].items():
        check(root / name, expected)
    physical = protocol["physical_source"]
    check(root / "capsule/source_provenance.json", physical["capsule_source_provenance_sha256"])
    for name, expected in physical["research_source_hashes"].items():
        check(root / "capsule/src" / name, expected)
    test_root = root / "formal_v2_test"
    opened, result = read(test_root / "OPEN_RECEIPT.json"), read(test_root / "RESULT.json")
    for record in (opened, result):
        require(record["seal_sha256"] == SEAL_SHA and record["protocol_sha256"] == PROTOCOL_SHA,
                "evaluation bound a different seal or protocol")
    require(datetime.fromisoformat(seal["frozen_utc"])
            < datetime.fromisoformat(opened["test_first_generated_after_utc"]), "test preceded freeze")
    bound, measured = {r["name"]: r for r in seal["rows"]}, {r["name"]: r for r in result["rows"]}
    require(len(bound) == len(seal["rows"]) == len(measured) == len(result["rows"]) == 168,
            "duplicate or incomplete rows")
    require(set(bound) == set(measured), "roster mismatch")
    verified = []
    for name, frozen in bound.items():
        require(Path(name).name == name, "case path must be a basename")
        case_root = root / "formal_v2_training" / name
        training = read(case_root / "RESULT.json")
        observed = measured[name]
        require(observed["status"] == "EVALUATED" and observed["case"] == frozen["case"], "case identity")
        require(training["protocol_sha256"] == PROTOCOL_SHA and training["case"] == frozen["case"],
                "training identity")
        require(observed["candidate_sha256"] == frozen["candidate_sha256"] == training["candidate_sha256"],
                "candidate rebound")
        verified.append({"name": name,
                         "result": check(case_root / "RESULT.json", frozen["result_sha256"]),
                         "history": check(case_root / "HISTORY.json", training["history_sha256"]),
                         "candidate": check(case_root / "candidate.pt", frozen["candidate_sha256"]),
                         "predictions": check(test_root / (name + ".npz"), observed["predictions_sha256"])})
    data = check(test_root / "test_data.npz", result["test_artifact_sha256"])
    receipt = {"schema": "hepta.adoption-closure.independent-hcsn-v2-bytes-audit.v1",
               "observed_utc": datetime.now(timezone.utc).isoformat(), "status": "ALL_BYTES_MATCH",
               "protocol_sha256": PROTOCOL_SHA, "seal_sha256": SEAL_SHA,
               "open_receipt_sha256": digest(test_root / "OPEN_RECEIPT.json"),
               "evaluation_result_sha256": digest(test_root / "RESULT.json"),
               "test_artifact_sha256": data, "candidate_count": len(verified),
               "verified_case_artifact_count": 4 * len(verified),
               "source_files_checked": len(protocol["source_hashes"]),
               "physical_source_files_checked": len(physical["research_source_hashes"]),
               "verified_records_sha256": hashlib.sha256(json.dumps(verified, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest(),
               "audit_source_sha256": digest(__file__), "model_calls": 0, "training_updates": 0,
               "test_regenerated": False, "model_deserialized": False,
               "production_or_real_user_qualification_claimed": False}
    with output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source_root, args.output)
