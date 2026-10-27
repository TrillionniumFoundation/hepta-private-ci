"""Curate receipts and archive every raw attempt with executable inputs."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import tarfile

from .protocol import sha, write


RECEIPTS = {
    "development-001": ["PROTOCOL.json", "FROZEN.json", "MODEL.json", "READOUT_FIT.json", "CRITIC_SELECTION.json", "ENCODER_DOMAIN_PROOF.json"],
    "preflight-001": ["RESULT.json"],
    "qualification-001": ["RESULT.json", "QUALIFICATION_SEAL.json"],
    "audit-003": ["RESULT.json"],
    "binding-check-001": ["RESULT.json"],
    "bound-execution-001": ["RESULT.json"],
    "acceptance-development-001": ["RESULT.json", "PROTOCOL.json"],
    "acceptance-head-development-001": ["RESULT.json", "PROTOCOL.json", "SELECTED_MODEL.json"],
    "acceptance-calibration-001": ["RESULT.json", "PROTOCOL.json", "FROZEN_CALIBRATOR.json", "CALIBRATOR.json"],
    "acceptance-refinement-002": ["RESULT.json", "PROTOCOL.json", "SELECTOR.json", "FROZEN_SELECTOR.json"],
    "acceptance-calibration-002": ["RESULT.json", "PROTOCOL.json", "FROZEN_CALIBRATOR.json", "CALIBRATOR.json", "SOURCE_MANIFEST.json"],
    "admission-preflight-001": ["RESULT.json"],
    "admission-qualification-001": ["FAILED.json", "FAILED.log"],
    "admission-qualification-002": ["RESULT.json", "PROTOCOL.json", "QUALIFICATION_SEAL.json"],
    "admission-audit-001": ["RESULT.json"],
    "admission-diagnosis-001": ["RESULT.json", "SOURCE_SCOPE_ADDENDUM.json"],
    "admission-promotion-denial-001": ["RESULT.json", "PROMOTION_DECISION.json"],
}


def curate(workspace, source):
    raw, evidence = workspace / "native_semantic_20261027", source / "evidence"
    log = (workspace / "native_semantic_tests_002.log").read_text()
    if "Ran 4 tests" not in log or not log.rstrip().endswith("OK"):
        raise ValueError("The actual boundary test log did not pass")
    for name in ("preflight-001", "audit-003", "binding-check-001", "bound-execution-001",
                 "admission-preflight-001", "admission-audit-001", "admission-promotion-denial-001"):
        if not json.loads((raw / name / "RESULT.json").read_text())["passed"]:
            raise ValueError("A required behavior/audit receipt did not pass")
    copied = []
    for run, names in RECEIPTS.items():
        destination = evidence / run
        destination.mkdir(parents=True, exist_ok=True)
        for name in names:
            original, target = raw / run / name, destination / name
            shutil.copyfile(original, target)
            copied.append({"source": str(original), "curated": str(target), "sha256": sha(target)})
    natural = source.parent / "natural"
    for name in ("PEER_CONTROL.json", "PEER_ADMISSION.json"):
        shutil.copyfile(natural / "evidence" / name, evidence / name)
        copied.append({"source": str(natural / "evidence" / name), "curated": str(evidence / name), "sha256": sha(evidence / name)})
    for name in ("native_semantic_audit_001.log", "native_semantic_audit_002.log", "native_semantic_audit_003.log",
                 "native_semantic_tests_002.log", "native_peer_natural_001.log", "native_peer_natural_002.log"):
        shutil.copyfile(workspace / name, evidence / name)
    tests = {"boundary_unittest": {"passed": True, "tests": 4, "actual_log_sha256": sha(workspace / "native_semantic_tests_002.log")},
        "historical_original_preflight": {"episodes": 60, "kernels": 3000},
        "negative_version_binding": {"stale_versions_rejected": 8, "live_state_and_durable_bytes_unchanged": True},
        "positive_guarded_execution": {"episodes": 3, "kernels": 150, "actions_bytes_predictions_unchanged": True},
        "actual_admission_preflight": {"episodes": 3, "kernels": 150, "offline_calibration_policy_matches_actual_native_execution": True},
        "semantic_tail_promotion_denial": {"rejected": True, "live_state_and_durable_bytes_unchanged": True},
        "all_behavior_checks_precede_final_repository_formatting": True}
    write(evidence / "TESTS.json", tests)
    attempts = [
        {"run": "qualification-001", "kind": "five-arm semantic feedback qualification", "outcome": "semantic feedback gain and exact execution match pass; original semantic diagnostics fail"},
        {"run": "audit-001", "kind": "independent replay prototype", "outcome": "aborted at original Open; no actual failure response captured in this first attempt; log retained; exact loaded auditor source not separately frozen"},
        {"run": "audit-002", "kind": "independent replay prototype", "outcome": "Open returned File exists using reused temporary audit namespace; response and snapshots retained"},
        {"run": "audit-003", "kind": "independent replay with unique per-episode scratch", "outcome": "640 full actual native/media/forecast audits pass; original owner was not relaxed"},
        {"run": "acceptance-development-001", "kind": "historical public scalar/CNN selector", "outcome": "no threshold met strict semantic error and nonvacuity criteria"},
        {"run": "acceptance-head-development-001", "kind": "historical learned quality head", "outcome": "ridge10/head0.8 selected on original historical fit/validation; calibration still required"},
        {"run": "acceptance-calibration-001", "kind": "disjoint-head-source historical calibration", "outcome": "legacy-shaped gates pass; actual entropic selective coverage0 fails; explicitly retired to development"},
        {"run": "acceptance-refinement-002", "kind": "historical-only new selector", "outcome": "fixed ridge10 weights, head0.70 plus public probability0.93 selected; original failed calibration remains preserved"},
        {"run": "acceptance-calibration-002", "kind": "new disjoint-head/retired-source historical calibration", "outcome": "fitting metrics pass all declared gates; generator source pool remains historical training; not heldout qualification"},
        {"run": "admission-qualification-001", "kind": "source consumer pre-inference preparation", "outcome": "count/list manifest schema error before any model outputs or native episodes; fixed full exclusion reconstruction; zero qualification evaluations consumed"},
        {"run": "admission-qualification-002", "kind": "single actual1024-source-pair qualification", "outcome": "all legacy-shaped metrics pass; 3/424 incorrect semantic commits fail frozen extra tail gate; no retuning, expansion or repeated model qualification"},
        {"run": "admission-audit-001", "kind": "full independent1024-case actual native/media/calibration audit", "outcome": "audit passes and independently confirms failed extra semantic-tail gate"},
        {"run": "admission-diagnosis-001", "kind": "read-only failure mechanism", "outcome": "three public/audit image disagreements; calibration mean is not a conservative tail bound; no new filter"},
        {"run": "admission-promotion-denial-001", "kind": "deployment gate behavior", "outcome": "failed semantic-tail candidate refused; original owner durable state unchanged; native DENY_ALL retained"},
        {"run": "native_peer_natural_001.log", "kind": "read-only peer statistics prototype", "outcome": "finite bootstrap differed because replication cluster order was source-ID rather than merchant-string; peer tool ordering corrected, no producer output changed"},
        {"run": "native_peer_natural_002.log", "kind": "read-only natural peer audit", "outcome": "all actual media/metrics/source-cluster statistics pass; subsequent scope addendum records metadata reread asymmetry"},
    ]
    write(evidence / "ATTEMPTS.json", {"no_failed_attempt_replaced": True, "attempts": attempts})
    write(evidence / "CURATED_RECEIPTS.json", {"files": copied, "raw_root": str(raw)})
    return evidence


def package(workspace, archive):
    source = Path(__file__).resolve().parent
    evidence = curate(workspace, source)
    roots = [workspace / "native_semantic_20261027", source,
        source.parents[1] / "continuation_20261027/control", source.parents[1] / "continuation_20261027/joint",
        source.parents[1] / "v6", source.parents[1] / "repair_20261026/joint"]
    files = {path.resolve() for root in roots for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts}
    assets = workspace / "ndu-original-assets/restored"
    files.update(path.resolve() for path in (assets / "ndu-data").glob("*.gz"))
    files.update([assets / "RESTORATION.json", assets / "ndu-runs/full-002/protocol.json",
        assets / "ndu-runs/full-002/reward-observer.pt", assets / "ndu-runs/full-002/audit-observer.pt",
        workspace / "ndu-joint-continuation/development-full-001/seed-17-joint_uniform-selected.pt",
        workspace / "native_owner_build_20261027/target/debug/examples/owner_host",
        source.parent / "SOURCE_ALLOCATION.json", source.parent / "CONTROL_ADMISSION_SOURCE_ALLOCATION.json",
        source.parent / "allocate_admission_sources.py",
        source.parent / "natural/peer_control.py", source.parent / "natural/peer_admission.py"])
    allocation = json.loads((source.parent / "CONTROL_ADMISSION_SOURCE_ALLOCATION.json").read_text())
    files.update(Path(path) for path in allocation["exclusion_source_pins"])
    for pattern in ("native_semantic_*.log", "native_admission_*.log", "native_peer_natural_*.log"):
        files.update(workspace.glob(pattern))
    entries = []
    for path in sorted(files, key=str):
        if path.is_symlink():
            raise ValueError("Archive input is a symlink: " + str(path))
        entries.append({"path": str(path.relative_to(workspace)), "source": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    manifest = {"schema": "hepta.ndu.native-semantic-full-archive.v1", "original_workspace": str(workspace),
        "source_baseline_commit": "fb9281e4a7ccfc4034281ed6310adea7e50f4474",
        "scientific_source_snapshots_precede_repository_formatting": True,
        "all_raw_attempts_included": True, "files": entries, "file_count": len(entries),
        "total_uncompressed_file_bytes": sum(r["bytes"] for r in entries),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "replay_scope": "Contains actual original Linux native binary, frozen generator, observer weights, official image/label gzip, public/private inputs, actual media, durable owner state and all executed-source snapshots. Requires the repository baseline for any further workspace dependencies.",
        "relocation": "Original receipts contain absolute paths. Restore under recorded workspace or adjust paths only in a separate replay copy; preserve immutable original receipts.",
        "qualification_outcome": "The additional semantic-tail gate fails and candidate promotion is refused. ECE/declared missing-OOD gates alone do not qualify it."}
    index = archive.with_suffix(archive.suffix + ".index.json")
    with index.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if archive.exists():
        raise FileExistsError("Preserve earlier archive attempts")
    with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
        info = tarfile.TarInfo("ARTIFACT_INDEX.json")
        contents = index.read_bytes()
        info.size = len(contents)
        bundle.addfile(info, io.BytesIO(contents))
        for row in entries:
            bundle.add(row["source"], arcname=row["path"], recursive=False)
    expected = {row["path"]: row for row in entries}
    checked = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            if member.name == "ARTIFACT_INDEX.json":
                if bundle.extractfile(member).read() != index.read_bytes():
                    raise ValueError("Archived inventory changed")
                continue
            if not member.isfile() or member.name not in expected:
                raise ValueError("Unregistered archive member")
            with bundle.extractfile(member) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != expected[member.name]["sha256"] or member.size != expected[member.name]["bytes"]:
                raise ValueError("Archive readback identity differs")
            checked.add(member.name)
    if checked != set(expected):
        raise ValueError("Incomplete archive")
    receipt = {"archive": str(archive), "archive_sha256": sha(archive), "archive_bytes": archive.stat().st_size,
        "index": str(index), "index_sha256": sha(index), "file_count": len(entries),
        "uncompressed_file_bytes": manifest["total_uncompressed_file_bytes"],
        "all_members_read_back_and_sha256_verified": True, "library_persistence_confirmed": False}
    write(evidence / "ARCHIVE_RECEIPT.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    package(args.workspace.resolve(), args.archive.resolve())
