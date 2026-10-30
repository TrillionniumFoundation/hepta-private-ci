"""Verify the follow-up evidence without treating failed hypotheses as passes.

This is an integrity check. Numerical and checkpoint replay tests have their
own records. No training, data download, or test-driven model change occurs.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "next"
MATRICES = {
    "sequence/results.json": (90, 600),
    "sequence/v2_reference_results.json": (15, 600),
    "sequence/full_results.json": (15, 600),
    "encoder/ag_news_baseline_results.json": (20, 300),
    "encoder/cifar10_baseline_results.json": (20, 300),
    "ablation/ag_news_results.json": (35, 300),
    "ablation/cifar10_results.json": (35, 300),
    "ridge/results.json": (105, 600),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_digest(name, digest, record):
    candidates = []
    for base in (ROOT, record.parent):
        path = (base / name).resolve()
        assert path.is_relative_to(ROOT), (record, name, "outside project")
        if path.is_file() and path not in candidates:
            candidates.append(path)
    matches = [path for path in candidates if sha(path) == digest]
    assert matches, (str(record.relative_to(ROOT)), name, "digest mismatch")
    return str(matches[0].relative_to(ROOT))


def visit(value, record, source_pairs, checkpoints):
    if isinstance(value, float):
        assert math.isfinite(value), (record, "nonfinite JSON value")
    elif isinstance(value, list):
        for child in value:
            visit(child, record, source_pairs, checkpoints)
    elif isinstance(value, dict):
        sources = value.get("source_sha256", {})
        if isinstance(sources, str):
            sources = {record.with_suffix(".py").name: sources}
        for name, digest in sources.items():
            assert isinstance(digest, str) and len(digest) == 64
            path = resolve_digest(name, digest, record)
            source_pairs.add((path, digest))
        if "checkpoint_file" in value and "checkpoint_sha256" in value:
            path = resolve_digest(value["checkpoint_file"], value["checkpoint_sha256"], record)
            checkpoints.add((path, value["checkpoint_sha256"]))
        for child in value.values():
            visit(child, record, source_pairs, checkpoints)


def verify_manifest(path):
    manifest = json.loads(path.read_text())
    for row in manifest["files"]:
        file = ROOT / row["path"]
        assert file.stat().st_size == row["bytes"], row["path"]
        assert sha(file) == row["sha256"], row["path"]
        data = file.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        assert blob == row["git_blob_sha"], row["path"]
    return len(manifest["files"])


def main(require_manifest=False):
    historical = verify_manifest(ROOT / "delivery_manifest.json")
    source_pairs, checkpoints = set(), set()
    python_files, max_lines = 0, 0
    for path in FOLDER.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        assert not any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
                       for node in ast.walk(tree)), path
        lines = len(source.splitlines())
        assert lines < 500, (path, lines)
        max_lines = max(max_lines, lines)
        python_files += 1
    json_count = 0
    for path in sorted(FOLDER.rglob("*.json")):
        if path.name in ("delivery_manifest.json", "evidence_checks.json"):
            continue
        visit(json.loads(path.read_text()), path, source_pairs, checkpoints)
        json_count += 1
    matrix_records = []
    for relative, (expected_count, updates) in MATRICES.items():
        result = json.loads((FOLDER / relative).read_text())
        assert result["complete"] is True, relative
        assert len(result["runs"]) == expected_count, relative
        identities = set()
        for row in result["runs"]:
            identity = (row.get("task", relative), row.get("kind", row.get("variant")), row["seed"])
            assert identity not in identities, (relative, identity)
            identities.add(identity)
            timing = row["timing"]
            assert timing["steps"] == updates and timing["batch_size"] == 32
            assert timing["train_examples_seen"] == updates * 32
            assert timing["warmup_optimizer_updates"] == 0
            assert timing["strong_initial_parameters"] is True
            assert timing["optimizer_signature_stable"] is True
        matrix_records.append(dict(file=relative, runs=expected_count, updates=updates))
    for relative, flag in (("full_kernel/join_results.json", "all_checks_passed"),
                           ("training_validation.json", "passed"),
                           ("sequence/checkpoint_audit.json", "passed"),
                           ("encoder/baseline_audit.json", "all_passed"),
                           ("ablation/audit_results.json", "all_passed")):
        assert json.loads((FOLDER / relative).read_text())[flag] is True, relative
    ridge_audit = json.loads((FOLDER / "ridge/audit_results.json").read_text())
    assert ridge_audit["passed"] is True and len(ridge_audit["checks"]) == 105
    independent = json.loads((FOLDER / "ridge/independent_audit.json").read_text())
    assert independent["static_passed"] is True
    assert independent["replay_pending"] is False
    assert independent["replay"]["passed"] is True
    manifest_path = FOLDER / "delivery_manifest.json"
    if require_manifest:
        assert manifest_path.exists(), "Generate the explicit final manifest first"
    manifest_count = verify_manifest(manifest_path) if manifest_path.exists() else None
    report = dict(schema="hepta.hcsn.followup.integrity.v1", integrity_passed=True,
        meaning="Integrity and recorded software validation, not scientific acceptance",
        historical_files_unchanged=historical, python_modules=python_files,
        largest_python_module_lines=max_lines, json_files_inspected=json_count,
        source_path_digest_pairs_verified=len(source_pairs),
        unique_checkpoint_path_digest_pairs_verified=len(checkpoints),
        completed_training_matrices=matrix_records,
        confirmatory_or_fixed_protocol_neural_runs=sum(row["runs"] for row in matrix_records),
        excluded_from_that_run_count="Four development trainings, two linear fits, numerical fixtures, prediction replay, timing probes",
        followup_manifest_files_verified=manifest_count,
        research_acceptance_all_passed=False,
        failed_evidence_preserved=["Original raw financial float32 tests",
            "v3 retrieval and longer memory/capacity challenges",
            "v4 per-seed memory extrapolation target",
            "v4 small-step float32 finite-difference stress checks",
            "No established financial-operator-specific quality benefit"],
        limitations=["No GPU or equal-quality scale/energy benchmark",
            "No paired multimodal or full-backbone training",
            "Rust workspace formatting/tests not run; no Rust files changed"])
    (FOLDER / "evidence_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-manifest", action="store_true")
    main(parser.parse_args().require_manifest)
