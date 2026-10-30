"""Read-only run audit and deterministic compact preservation of original bytes.

No model, media or target is generated here. Invalid/partial evidence is still
preserved with an explicit failed audit; unsafe paths are never followed.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import tarfile

from ..contract import (CostEvent, DecisionEvent, DeliveredOutcome, GenerationState,
                        JointGenerationProfile, validate_episode)


SCHEMA = "hepta.joint-generation.compact-archive.v2"
MEDIA = {"text": "text.txt", "image": "image.png", "audio": "audio.wav", "video": "video.gif"}
JSON_NAMES = {"RESULT.json", "RESULTS.json", "RESULTS.partial.json", "PROFILE.json",
              "EXECUTED_PROTOCOL.json", "SUMMARY.json", "PROTOCOL.json", "ALLOCATION.json",
              "SOURCE_RECEIPT.json", "PROCESS_RECEIPT.json", "RECEIPT.json",
              "BUILD_RECEIPT.json", "LOCK_IDENTITY_CHECK.json"}
TEXT_NAMES = {"process.log", "environment.txt", "runtime.txt", "stdout.log", "stderr.log"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    hasher, size = hashlib.sha256(), 0
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
            size += len(block)
    return {"sha256": hasher.hexdigest(), "bytes": size}


def safe_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Path escapes the supplied run root")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlinks are not admissible evidence paths")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError("Expected an existing regular file within the run root")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Non-regular evidence path")
    return path


def inventory(root):
    files, errors = {}, []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            if (Path(directory) / name).is_symlink():
                errors.append({"path": str((Path(directory) / name).relative_to(root)),
                               "error": "Rejected symlink directory; contents not accessed"})
                dirs.remove(name)
        for name in sorted(names):
            relative = str((Path(directory) / name).relative_to(root))
            try:
                files[relative] = file_identity(safe_file(root, relative))
            except (ValueError, OSError) as exc:
                errors.append({"path": relative, "error": type(exc).__name__ + ": " + str(exc)})
    return dict(sorted(files.items())), errors


def read_json(path):
    def nonfinite(value):
        raise ValueError("Nonfinite JSON number: " + value)
    return json.loads(Path(path).read_bytes(), parse_constant=nonfinite)


def phase(relative):
    parts = Path(relative).parts
    if "training" in parts:
        return "distillation_training" if "distillation" in parts else "training"
    if "development" in parts or "evaluation" in parts:
        return "evaluation"
    if "distillation" in parts and ("teacher" in parts or "student" in parts):
        return "distillation_evaluation"
    return "diagnostic"


def audit_trajectory(root, relative):
    path = safe_file(root, relative)
    data = read_json(path)
    profile = JointGenerationProfile.from_dict(data["profile"])
    if profile.digest != data["profile_sha256"]:
        raise ValueError("Trajectory profile digest differs")
    states = []
    for raw in data["state_chain"]:
        value = dict(raw)
        for key in ("modality_state_sha256", "committed_artifact_sha256", "generation_steps", "media_positions"):
            value[key] = tuple(tuple(pair) for pair in value[key])
        states.append(GenerationState(**value))
    events = []
    for raw in data["events"]:
        value = dict(raw)
        value["costs"] = tuple(CostEvent(**item) for item in value["costs"])
        value["joint_action_probabilities"] = tuple(tuple(pair) for pair in value["joint_action_probabilities"])
        events.append(DecisionEvent(**value))
    value = dict(data["outcome"])
    value["costs"] = tuple(CostEvent(**item) for item in value["costs"])
    value["artifact_sha256"] = tuple(tuple(pair) for pair in value["artifact_sha256"])
    outcome = DeliveredOutcome(**value)
    measured = validate_episode(profile, tuple(states), tuple(events), outcome)
    if (not math.isclose(measured, data["net_return"], rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(sum(c.amount for c in outcome.costs), data["actual_cost"], rel_tol=1e-12, abs_tol=1e-12)
            or data["source_id"] != outcome.source_cluster_id
            or data["parameter_snapshot_sha256"] != states[0].parameter_snapshot_sha256
            or data["policy_snapshot_sha256"] != states[0].policy_snapshot_sha256):
        raise ValueError("Trajectory summaries differ from the validated event chain")
    failed = data["failure"] is not None
    if failed != (outcome.terminal_kind != "delivered"):
        raise ValueError("Failure flag and terminal kind disagree")
    if not failed and set(dict(outcome.artifact_sha256)) != set(MEDIA):
        raise ValueError("Successful delivery must contain all four actual outputs")
    artifacts = []
    for modality, expected in outcome.artifact_sha256:
        artifact_relative = str((path.parent / "outputs" / MEDIA[modality]).relative_to(root))
        actual = file_identity(safe_file(root, artifact_relative))
        if actual["sha256"] != expected:
            raise ValueError("Actual output bytes differ from the delivered receipt: " + artifact_relative)
        artifacts.append({"path": artifact_relative, "modality": modality, **actual})
    return {"path": relative, "phase": phase(relative), "profile_sha256": profile.digest,
            "source_id": data["source_id"], "sample_id": outcome.sample_id,
            "failure": data["failure"], "terminal_kind": outcome.terminal_kind,
            "utility": outcome.delivered_utility, "net_return": measured,
            "actual_cost": data["actual_cost"], "events": len(events), "artifacts": artifacts,
            "chain_and_actual_artifacts_validated": True}


def selected(relative):
    path = Path(relative)
    if "pretrained" in path.parts:
        return False
    return (path.name in JSON_NAMES | TEXT_NAMES or path.suffix == ".pt"
            or path.name.endswith(("_FREEZE.json", ".pt.manifest.json", "_observer.npz"))
            or path.name in {"OBSERVER_FREEZE.json", "OBSERVER_V2_FREEZE.json"})


def write_json(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if str(path).endswith(".gz"):
        data = gzip.compress(data, compresslevel=9, mtime=0)
    with Path(path).open("xb") as handle:
        handle.write(data)


def audit_receipts(root, files):
    checks = {"process_receipt_present": False, "source_receipt_present": False,
              "checkpoint_files_verified": 0, "observer_checkpoints_verified": 0}
    errors = []
    for relative in files:
        name = Path(relative).name
        try:
            if relative == "PROCESS_RECEIPT.json":
                record = read_json(safe_file(root, relative))
                log = safe_file(root, "process.log")
                if record["process_log_sha256"] != file_identity(log)["sha256"]:
                    raise ValueError("Process log differs from its original meter receipt")
                checks.update(process_receipt_present=True, process_exit_code=record["exit_code"],
                              process_timed_out=record["timed_out"], child_reaped=record["child_reaped"])
            elif relative == "SOURCE_RECEIPT.json":
                record = read_json(safe_file(root, relative))
                if record["before"] != record["after"] or record["source_bytes_unchanged"] is not True:
                    raise ValueError("Study changed its source bytes during execution")
                for boundary in ("before", "after"):
                    raw = json.dumps(record[boundary]["files"], sort_keys=True, separators=(",", ":")).encode()
                    if sha(raw) != record[boundary]["sha256"]:
                        raise ValueError("Source receipt file inventory digest differs")
                checks["source_receipt_present"] = True
            elif Path(name).suffix == ".pt" and selected(relative):
                sidecar = read_json(safe_file(root, relative + ".manifest.json"))
                if (sidecar["file_sha256"] != files[relative]["sha256"]
                        or sidecar["file_bytes"] != files[relative]["bytes"]):
                    raise ValueError("Checkpoint file differs from its original sidecar")
                checks["checkpoint_files_verified"] += 1
            elif name == "OBSERVER_V2_FREEZE.json":
                freeze = read_json(safe_file(root, relative))
                for kind, item in freeze["selected"].items():
                    filename = item["checkpoint_file"]
                    if filename != kind + "_observer.npz":
                        raise ValueError("Observer checkpoint name is not an allowed local file")
                    target = str(Path(relative).parent / filename)
                    if file_identity(safe_file(root, target))["sha256"] != item["checkpoint_sha256"]:
                        raise ValueError("Observer checkpoint differs from its frozen digest")
                    checks["observer_checkpoints_verified"] += 1
        except (ValueError, KeyError, TypeError, OSError) as exc:
            errors.append({"path": relative, "error": type(exc).__name__ + ": " + str(exc)})
    for field in ("process_receipt_present", "source_receipt_present"):
        if not checks[field]:
            errors.append({"path": ".", "error": "Missing or invalid " + field})
    return checks, errors


def archive_run(run, output):
    supplied = Path(run)
    if supplied.is_symlink() or not supplied.is_dir():
        raise ValueError("A real meter-wrapper directory is required")
    root, output = supplied.resolve(), Path(output).absolute()
    if output.exists() or output.resolve().is_relative_to(root):
        raise ValueError("A new compact directory outside the source run is required")
    files, errors = inventory(root)
    checks, receipt_errors = audit_receipts(root, files)
    errors.extend(receipt_errors)
    trajectories = []
    trajectory_paths = [p for p in files if Path(p).name == "TRAJECTORY.json"]
    for relative in trajectory_paths:
        try:
            trajectories.append(audit_trajectory(root, relative))
        except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
            errors.append({"path": relative, "error": type(exc).__name__ + ": " + str(exc)})
    if "run/PROFILE.json" in files:
        try:
            profile = JointGenerationProfile.from_dict(read_json(safe_file(root, "run/PROFILE.json")))
            if any(row["profile_sha256"] != profile.digest for row in trajectories):
                raise ValueError("Actual trajectory differs from the study's frozen profile")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            errors.append({"path": "run/PROFILE.json", "error": type(exc).__name__ + ": " + str(exc)})
    if "run/RESULTS.json" in files and "run/EXECUTED_PROTOCOL.json" in files:
        try:
            result = read_json(safe_file(root, "run/RESULTS.json"))
            if result.get("schema") == "hepta.joint-generation.controller-v2.development.v1":
                protocol = read_json(safe_file(root, "run/EXECUTED_PROTOCOL.json"))
                expected = {"training": len(protocol["arms"]) * protocol["joint_updates"] * protocol["joint_batch"],
                            "evaluation": len(protocol["arms"]) * protocol["development_sources"] * protocol["evaluation_draws_per_source"],
                            "distillation_training": protocol["distillation_rounds"] * protocol["distillation_sources_per_round"],
                            "distillation_evaluation": 2 * protocol["development_sources"] * protocol["evaluation_draws_per_source"]}
                actual = Counter(row["phase"] for row in trajectories)
                if any(actual[key] != value for key, value in expected.items()):
                    raise ValueError("Actual trajectory counts differ from the complete executed protocol")
                checks["completed_controller_episode_counts_verified"] = expected
        except (ValueError, KeyError, TypeError, OSError) as exc:
            errors.append({"path": "run/RESULTS.json", "error": type(exc).__name__ + ": " + str(exc)})
    output.mkdir(parents=True, exist_ok=False)
    preserved = []
    # Preserve every raw trajectory in one shared compression stream. Tar member
    # bytes are original bytes; deterministic headers contain no host identities.
    if trajectory_paths:
        target = output / "TRAJECTORIES.tar.gz"
        with target.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for relative in trajectory_paths:
                        payload = safe_file(root, relative).read_bytes()
                        if {"sha256": sha(payload), "bytes": len(payload)} != files[relative]:
                            errors.append({"path": relative, "error": "Trajectory changed while being archived"})
                        info = tarfile.TarInfo(relative)
                        info.size, info.mtime, info.mode = len(payload), 0, 0o644
                        archive.addfile(info, io.BytesIO(payload))
                        preserved.append({"source_path": relative, "source_sha256": sha(payload),
                                          "source_bytes": len(payload), "stored_path": target.name,
                                          "archive_member": relative, "encoding": "tar_member_original_bytes"})
    for relative in files:
        if not selected(relative):
            continue
        payload = safe_file(root, relative).read_bytes()
        original = {"sha256": sha(payload), "bytes": len(payload)}
        if original != files[relative]:
            errors.append({"path": relative, "error": "Input changed while being archived"})
        compress = Path(relative).suffix in {".json", ".txt", ".log"}
        stored_relative = "original/" + relative + (".gz" if compress else "")
        target = output / stored_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        stored = gzip.compress(payload, compresslevel=9, mtime=0) if compress else payload
        with target.open("xb") as handle:
            handle.write(stored)
        preserved.append({"source_path": relative, "source_sha256": original["sha256"],
                          "source_bytes": original["bytes"], "stored_path": stored_relative,
                          "stored_sha256": sha(stored), "stored_bytes": len(stored),
                          "encoding": "gzip_original_bytes" if compress else "original_bytes"})
    after, after_errors = inventory(root)
    errors.extend(after_errors)
    unchanged = files == after
    if not unchanged:
        errors.append({"path": ".", "error": "Run inventory changed during read-only audit"})
    counts = dict(Counter(item["phase"] for item in trajectories))
    audit = {"schema": SCHEMA + ".audit", "trajectory_files_found": len(trajectory_paths),
             "trajectory_chains_verified": len(trajectories), "counts_by_phase": counts,
             "failures": sum(item["failure"] is not None for item in trajectories),
             "actual_output_files_verified": sum(len(item["artifacts"]) for item in trajectories),
             "profile_sha256_values": sorted({item["profile_sha256"] for item in trajectories}),
             "source_files_unchanged_during_archive": unchanged, "receipt_checks": checks,
             "errors": errors, "integrity_passed": not errors,
             "process_completed_successfully": checks.get("process_exit_code") == 0
                                                 and not checks.get("process_timed_out", True),
             "scientific_qualification": False, "fresh_media_opened_by_audit": False,
             "scope": "Actual recorded chains and file identities; not semantic correctness or model efficacy"}
    write_json(output / "TRAJECTORY_AUDIT.json.gz", trajectories)
    write_json(output / "INPUT_MANIFEST.json.gz", {"schema": SCHEMA + ".input", "files": files,
                                                  "unsafe_or_unreadable_paths": after_errors})
    write_json(output / "AUDIT.json", audit)
    stored_files, stored_errors = inventory(output)
    if stored_errors:
        raise ValueError("Compact output contains an unsafe file")
    manifest = {"schema": SCHEMA, "audit": audit, "preserved_originals": preserved,
                "stored_files": stored_files, "input_files": len(files),
                "input_bytes": sum(item["bytes"] for item in files.values()),
                "input_manifest_sha256": stored_files["INPUT_MANIFEST.json.gz"]["sha256"],
                "media_and_pretrained_weights": "Omitted from compact archive; retained in original full artifact",
                "original_bytes_rewritten": False}
    write_json(output / "MANIFEST.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = archive_run(args.run, args.output)
    print(json.dumps({"integrity_passed": report["audit"]["integrity_passed"],
                      "input_files": report["input_files"],
                      "verified_trajectories": report["audit"]["trajectory_chains_verified"],
                      "verified_outputs": report["audit"]["actual_output_files_verified"],
                      "stored_bytes": sum(v["bytes"] for v in report["stored_files"].values()),
                      "errors": len(report["audit"]["errors"])}, sort_keys=True))
    return int(not report["audit"]["integrity_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
