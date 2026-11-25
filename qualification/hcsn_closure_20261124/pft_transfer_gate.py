"""Read-only PFT artifact handoff to the existing E6 paired-learning owners.

Model declarations use hepta.experimental-model.v1. Hashes bind local bytes;
they do not authenticate people or permit adoption. The HCSN family still needs
an original paired_cold loader. The pinned #7029 retention checker is executed
unchanged, without training, native E6 execution, or consent fabrication.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


OWNER_COMMIT = "8a04316f6362db52b7946a48f151744f50a99fba"
MODEL_SCHEMA = "hepta.experimental-model.v1"
FAMILIES = ("synthetic_frozen_readout", "hepta-hcsn-pft-readout-v1")
OWNER_BLOBS = {
    "__init__.py": "6deac8e2e9f77ca207467a8911356e206a416554",
    "adoption.py": "e027263f8dd0ab493921c0bc0c632f1d323ba6c5",
    "data.py": "1f32cb00fb815ced989580a31dd8d39424d3e1e8",
    "coding_sft.py": "cde0de276c9a567e92ff8c623b2d1382d40f4c2d",
    "paired_cold.py": "3a615b70c099ef4026b284d987ad374eae95c0c2",
    "paired_freeze.py": "c8b958731a823e06a4020e516e647a8174b9775f",
    "paired_source.py": "ddb3177467ea02b30a10cb97232778b00bf01770",
    "paired_source_fit.py": "d0adab71be56695a1c6c6a64c9b79000afdfdac8",
    "paired_source_train.py": "e09338f119a59d772b4bceaa8c90c2b87089d652",
    "prospective_exposure.py": "83ccfc35fdda7e69eaed98b25caf84854a0656a4",
    "paired_people.py": "423c95b09ee0345bd7cde5da648d9d2ed48dc6b6",
    "paired_observation.py": "b5dd39fe4686706bb4144a2118d9d643021fb7fe",
    "paired_source_dispatch.py": "0c0d40ab9c552a26f97ceba1810e90d934716e0e",
    "paired_source_gate.py": "d5abea864e4429108c1543b0c1214b8e4c518963",
    "paired_intake.py": "fdcfac001285cc055aa713b34db13db5ac9690d7",
    "chat_protocol.py": "2f5cd7e2a650f6321e4ff20bf46f22e8a04ccfa2",
}


def identity(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def bound_file(root, relative):
    path = Path(relative)
    require(
        not path.is_absolute() and ".." not in path.parts and path.parts,
        "artifact path must remain inside its root",
    )
    current = Path(root)
    for part in path.parts:
        current = current / part
        require(not current.is_symlink(), "artifact symlink is not immutable")
    require(current.is_file(), "missing artifact: " + str(relative))
    return current


def descriptor(root, relative, role):
    raw = bound_file(root, relative).read_bytes()
    return dict(
        role=role,
        path=str(relative),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def make_handoff(
    root,
    parent_checkpoint,
    candidate_checkpoint,
    features,
    runtime,
    *,
    family="synthetic_frozen_readout",
):
    """Return declarations for the original freeze SPEC; no freeze is claimed."""
    require(family in FAMILIES, "unsupported declared family")
    parent_file = descriptor(root, parent_checkpoint, "base")
    child_file = descriptor(root, candidate_checkpoint, "weights")
    feature_file = descriptor(root, features, "features")
    require(parent_file["sha256"] != child_file["sha256"], "unchanged checkpoint")
    runtime = {**runtime, "feature_sha256": feature_file["sha256"]}
    parent = dict(
        schema=MODEL_SCHEMA,
        family=family,
        parent=None,
        runtime=runtime,
        files=[parent_file, feature_file],
    )
    child = dict(
        schema=MODEL_SCHEMA,
        family=family,
        parent=identity(parent),
        runtime=dict(runtime),
        files=[parent_file, child_file, feature_file],
    )
    return {"parent": parent, "candidate": child}


def audit_handoff(root, pair, expected_digest, expected_parent, expected_feature):
    """Detect altered artifacts or coordinates against separately retained hashes."""
    require(identity(pair) == expected_digest, "handoff changed after binding")
    parent, child = pair["parent"], pair["candidate"]
    require(
        identity(parent) == expected_parent and child["parent"] == expected_parent,
        "candidate parent differs from the bound parent",
    )
    require(
        parent["family"] == child["family"]
        and child["family"] in FAMILIES
        and parent["runtime"] == child["runtime"],
        "model family/runtime mismatch",
    )
    require(
        parent["runtime"]["feature_sha256"] == expected_feature,
        "feature coordinates differ from the bound feature",
    )
    for model in (parent, child):
        require(model["schema"] == MODEL_SCHEMA, "unsupported model declaration")
        seen = set()
        for item in model["files"]:
            require(item["path"] not in seen, "duplicate artifact path")
            seen.add(item["path"])
            require(
                descriptor(root, item["path"], item["role"]) == item,
                "artifact bytes changed: " + item["path"],
            )
        feature_files = [f for f in model["files"] if f["role"] == "features"]
        require(
            len(feature_files) == 1 and feature_files[0]["sha256"] == expected_feature,
            "feature artifact is not bound to runtime",
        )
    base = [f for f in parent["files"] if f["role"] == "base"]
    weights = [f for f in child["files"] if f["role"] == "weights"]
    require(
        len(base) == len(weights) == 1 and base[0]["sha256"] != weights[0]["sha256"],
        "one changed candidate checkpoint is required",
    )
    require(
        [f for f in child["files"] if f["role"] == "base"] == base,
        "candidate base artifact differs",
    )
    return dict(
        status="ARTIFACTS_VERIFIED",
        parent_sha256=expected_parent,
        candidate_sha256=identity(child),
        feature_sha256=expected_feature,
        handoff_sha256=expected_digest,
        loader_status="ORIGINAL_LOADER_REQUIRED",
        stages={
            "provenance": "ORIGINAL_SOURCE_OWNER_REQUIRED",
            "freeze": "ORIGINAL_PRE_ARRIVAL_FREEZE_REQUIRED",
            "retention": "ORIGINAL_COLD_RETENTION_REQUIRED",
            "adoption": "NATIVE_E6_ORIGINALS_REQUIRED",
            "restart": "NATIVE_E6_COLD_ORIGINALS_REQUIRED",
        },
        next_entrypoint="cell_experiments.paired_freeze.freeze",
        unresolved=[
            "declared family loader in original paired_cold owner",
            "authorized source training and original cold retention",
            "original A/B enrollment and post-freeze arrival",
            "native E6 adoption, restart, fresh task and FinalUse",
        ],
    )


def reject_future_contradictions(record, freeze, arrival):
    """Reject contradictions in original schemas; this never admits a future task."""
    require(
        record["schema"] == "hepta.cell-experiments.record.v1",
        "original record schema required",
    )
    require(
        record["origin_kind"] == "authorized_agent_run"
        and record["exposure"] == "unexposed"
        and record["split"] == "confirmation"
        and record["authorization"]["training_allowed"] is False
        and record["authorization"]["evaluation_allowed"] is True,
        "synthetic, exposed or training-permitted data cannot establish real B",
    )
    require(
        freeze["schema"] == "hepta.paired-intake.freeze-observation.v1"
        and arrival["schema"] == "hepta.paired-intake.first-observation.v1",
        "original source observations required",
    )
    for key in ("study_sha256", "freeze_sha256"):
        require(arrival[key] == freeze[key], "arrival belongs to another " + key)
    require(
        type(freeze["sequence"]) is int
        and type(arrival["sequence"]) is int
        and 0 < freeze["sequence"] < arrival["sequence"] < 2**63,
        "B arrival does not follow the original freeze",
    )
    require(arrival["record_sha256"] == identity(record), "arrival record changed")
    return dict(
        status="ORIGINAL_INTAKE_REQUIRED",
        next_entrypoint="cell_experiments.paired_intake.admit",
        reason="structural checks do not authenticate people, consent or arrival",
    )


def audit_original_retention(reference_root, operation, expected_candidate=None):
    """Run the unchanged #7029 read-only checker on retained operation originals."""
    reference_root, operation = Path(reference_root), Path(operation)
    source_dir = reference_root / "scripts/cell_experiments"
    mismatches = []
    for name, expected in OWNER_BLOBS.items():
        path = source_dir / name
        raw = path.read_bytes() if path.is_file() else b""
        actual = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        if actual != expected:
            mismatches.append(name)
    if mismatches:
        return dict(
            status="CHECKER_SOURCE_UNAVAILABLE",
            owner_commit=OWNER_COMMIT,
            mismatched_or_missing=mismatches,
        )
    needed = (
        "FROZEN.json",
        "COMPLETED.json",
        "OWNER.json",
        "RETENTION.json",
        "cold-retention/parent.json",
        "cold-retention/candidate.json",
    )
    missing = [name for name in needed if not (operation / name).is_file()]
    if missing:
        return dict(
            status="ORIGINALS_MISSING", owner_commit=OWNER_COMMIT, missing=missing
        )
    try:
        completed = json.loads((operation / "COMPLETED.json").read_text())
        candidate = completed["candidate_sha256"]
    except (ValueError, KeyError, OSError) as error:
        return dict(
            status="ORIGINALS_INVALID", owner_commit=OWNER_COMMIT, reason=str(error)
        )
    if expected_candidate is not None and candidate != expected_candidate:
        return dict(
            status="CANDIDATE_MISMATCH",
            observed_candidate=candidate,
            expected_candidate=expected_candidate,
        )
    code = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from cell_experiments import paired_source_dispatch
p=Path(sys.argv[2]); c=json.loads((p/'COMPLETED.json').read_text())
try:
    digest=paired_source_dispatch.verify_originals(p/'RETENTION.json',c['study_sha256'],c['freeze_sha256'])
except Exception as error:
    print(json.dumps(dict(status='ORIGINAL_CHECKER_REJECTED',error_type=type(error).__name__,reason=str(error))))
    sys.exit(2)
print(json.dumps(dict(status='ORIGINAL_RETENTION_CHECK_PASSED',retention_sha256=digest)))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            code,
            str(reference_root / "scripts"),
            str(operation),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        observed = json.loads(result.stdout)
        require(result.returncode in (0, 2), "checker did not terminate normally")
    except (ValueError, TypeError):
        observed = dict(status="CHECKER_EXECUTION_FAILED", stderr=result.stderr[-4096:])
    return {
        **observed,
        "owner_commit": OWNER_COMMIT,
        "candidate_sha256": candidate,
        "source_scope": completed["scope"],
        "freeze_sha256": completed["freeze_sha256"],
        "returncode": result.returncode,
        "checker": "cell_experiments.paired_source_dispatch.verify_originals",
        "remaining_owner": "paired_intake.admit and native E6 lifecycle",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("handoff")
    for field in ("root", "pair", "digest", "parent", "feature"):
        check.add_argument(field)
    original = commands.add_parser("original-retention")
    original.add_argument("reference_root")
    original.add_argument("operation")
    original.add_argument("--candidate")
    args = parser.parse_args()
    if args.command == "handoff":
        result = audit_handoff(
            args.root,
            json.loads(Path(args.pair).read_text()),
            args.digest,
            args.parent,
            args.feature,
        )
    else:
        result = audit_original_retention(
            args.reference_root, args.operation, args.candidate
        )
    print(
        json.dumps(
            result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
    )
    if result["status"] not in (
        "ARTIFACTS_VERIFIED",
        "ORIGINAL_RETENTION_CHECK_PASSED",
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
