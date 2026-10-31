"""Read-only, independent audit of the preserved and resumed MAIN attempt.

No scientific module is imported, no data are generated, and no archive is
unpacked. Original failed files are hashed in a streaming tar reader. Only the
three identity files are read from the successful scope; other completed scope
archives are checked by their previously committed compressed-file hashes.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

import numpy as np

PROTOCOL_REL = "experiments/analytic_event_neuron/round3/PROTOCOL.json"


class Checks:
    def __init__(self):
        self.counts = Counter()

    def require(self, condition, group, detail):
        if not condition:
            raise AssertionError(f"{group}: {detail}")
        self.counts[group] += 1


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def safe_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and str(p) == name


def load_arrays(content):
    with np.load(io.BytesIO(content), allow_pickle=False) as source:
        return {key: source[key] for key in source.files}


def identity(contents):
    raw = load_arrays(contents["DATA.npz"])
    values = {key: value.item() if value.ndim == 0 else value for key, value in raw.items()}
    # Independently reproduces the explicitly registered logical-byte digest:
    # sorted key bytes, then ndarray storage bytes or the scalar's string bytes.
    h = hashlib.sha256()
    for key in sorted(values):
        h.update(key.encode())
        value = values[key]
        h.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    ids = values["ids"].tolist()
    return {
        "data_seed": values["seed"], "split": values["split"], "law": values["law"],
        "trajectories": len(ids), "npz_sha256": digest_bytes(contents["DATA.npz"]),
        "dataset_sha256": h.hexdigest(),
        "dataset_metadata_sha256": digest_bytes(contents["DATASET.json"]),
        "model_file_sha256": digest_bytes(contents["MODELS.json"]),
        "first_id": ids[0], "last_id": ids[-1],
        "ids_sha256": digest_bytes(json.dumps(ids, separators=(",", ":")).encode()),
    }, raw


def verify_freeze(root, repo, check):
    frozen = read_json(root / "FREEZE.json")
    check.require(frozen["protocol_sha256"] == digest_file(repo / PROTOCOL_REL),
                  "freeze", "protocol bytes")
    for group, base in (("sources_sha256", repo), ("artifacts_sha256", root)):
        for name, expected in frozen[group].items():
            check.require(safe_name(name), "freeze", f"safe relative name {name}")
            check.require(digest_file(base / name) == expected, "freeze", name)
    return frozen


def review(root, repo, descriptor_path):
    check = Checks()
    frozen = verify_freeze(root, repo, check)
    freeze_hash = digest_file(root / "FREEZE.json")
    recovery_path = root / "MAIN_OPERATIONAL_RECOVERY.json"
    recovery = read_json(recovery_path)
    resumed = read_json(root / "MAIN_RESUME1_IDENTITY.json")
    timing = read_json(root / "MAIN_RESUME1_EXECUTION.json")
    current = read_json(root / "main/RUN_INDEX.json")
    descriptors = read_json(descriptor_path)
    check.require(len(descriptors) == 1, "binding", "one failed-attempt descriptor")
    descriptor = descriptors[0]
    check.require(descriptor == recovery["archive"], "binding", "archive descriptor exact")
    check.require(len(descriptor["parts"]) == 2, "binding", "two ordered archive parts")
    chunks = []
    for part in descriptor["parts"]:
        check.require(safe_name(part["path"]), "binding", "archive part relative path")
        value = (repo / part["path"]).read_bytes()
        check.require(len(value) == part["bytes"], "binding", "part size")
        check.require(digest_bytes(value) == part["sha256"], "binding", "part SHA256")
        chunks.append(value)
    combined = b"".join(chunks)
    check.require(len(combined) == descriptor["bytes"], "binding", "combined bytes")
    check.require(digest_bytes(combined) == descriptor["sha256"], "binding", "combined SHA256")
    prefix = "operational_attempts/main_seed_1009_gaussian_attempt1/"
    wanted = {"DATA.npz", "DATASET.json", "MODELS.json", "OPERATIONAL_COMPLETED_INDEX.json",
              "OPERATIONAL_FAILURE_STATE.json", "OPERATIONAL_PRODUCER_LOG.raw"}
    retained, observed, modes, sizes = {}, {}, {}, {}
    manifest = None
    with tarfile.open(fileobj=io.BytesIO(combined), mode="r|gz") as archive:
        for member in archive:
            check.require(safe_name(member.name) and member.isfile(), "failed_archive", "safe regular member")
            check.require(member.name not in observed, "failed_archive", "unique member name")
            content = archive.extractfile(member).read()
            check.require(len(content) == member.size, "failed_archive", "member size")
            observed[member.name] = digest_bytes(content)
            sizes[member.name], modes[member.name] = member.size, member.mode
            if member.name == descriptor["member_manifest"]:
                manifest = json.loads(content)
            elif member.name.startswith(prefix) and member.name[len(prefix):] in wanted:
                retained[member.name[len(prefix):]] = content
    check.require(manifest is not None, "failed_archive", "manifest present")
    manifest_digest = observed.pop(descriptor["member_manifest"])
    check.require(set(manifest) == set(observed), "failed_archive", "manifest inventory exact")
    for name, expected in manifest.items():
        check.require(observed[name] == expected, "failed_archive", f"SHA256 {name}")
    check.require(len(observed) == descriptor["data_members"] == 43136,
                  "failed_archive", "43132 original files plus four metadata files")
    failure_state = json.loads(retained["OPERATIONAL_FAILURE_STATE.json"])
    check.require(failure_state["schema"] == "hepta.analytic-event.round3.failed-main-attempt.v1",
                  "original_inventory", "original failed-attempt schema")
    check.require(recovery["schema"] == "hepta.analytic-event.round3.main-operational-recovery.v1",
                  "original_inventory", "outer recovery receipt schema")
    original_files = failure_state["original_files"]
    check.require(len(original_files) == recovery["original_file_count"] == 43132,
                  "original_inventory", "original file count")
    for name, meta in original_files.items():
        full = prefix + name
        check.require(safe_name(name) and full in observed, "original_inventory", "original member present")
        check.require(observed[full] == meta["sha256"], "original_inventory", "original bytes SHA256")
        check.require(sizes[full] == meta["bytes"], "original_inventory", "original byte length")
        check.require(modes[full] == meta["mode"], "original_inventory", "original file mode")
    check.require(sum(m["bytes"] for m in original_files.values()) == recovery["original_file_bytes"] == 8599498,
                  "original_inventory", "all original bytes accounted")
    extras = set(observed) - {prefix + name for name in original_files}
    check.require(extras == {prefix + name for name in ("OPERATIONAL_FAILURE_STATE.json",
                  "OPERATIONAL_COMPLETED_INDEX.json", "OPERATIONAL_PRODUCER_LOG.raw", "OPERATIONAL_SEAL_SCRIPT.py")},
                  "original_inventory", "only four additional preservation metadata files")
    for name, value in recovery.items():
        if name in failure_state and name != "schema":
            check.require(value == failure_state[name], "original_inventory", f"preservation metadata {name}")

    old_index_bytes = retained["OPERATIONAL_COMPLETED_INDEX.json"]
    old_index = json.loads(old_index_bytes)
    check.require(digest_bytes(old_index_bytes) == recovery["index_sha256"], "index_prefix", "original index hash")
    check.require(not old_index["complete"] and len(old_index["scopes"]) == 12, "index_prefix", "original12")
    check.require(current["complete"] and len(current["scopes"]) == 15, "index_prefix", "current15")
    check.require(old_index["scopes"] == current["scopes"][:12], "index_prefix", "whole12-entry prefix unchanged")
    expected_names = {f"seed_{seed}_{law}" for seed in (607, 701, 809, 907, 1009)
                      for law in ("gaussian", "drift_shift", "student_t")}
    check.require({x["scope"] for x in current["scopes"]} == expected_names, "index_prefix", "registered15 unique scopes")
    for item in current["scopes"]:
        check.require(digest_file(root / item["archive"]) == item["archive_receipt"]["sha256"],
                      "completed_files", f"compressed archive {item['scope']}")
        check.require(digest_file(root / item["analysis"]) == item["analysis_sha256"],
                      "completed_files", f"analysis {item['scope']}")
        check.require(item["audit_passed"] and item["unique_trajectories"] == 384,
                      "completed_files", "completed audit and registered trajectory count")
    condensed = [{"scope": e["scope"], "archive_sha256": e["archive_receipt"]["sha256"],
                  "analysis_sha256": e["analysis_sha256"]} for e in old_index["scopes"]]
    check.require(condensed == recovery["completed_scopes"], "index_prefix", "condensed preserved prefix")
    scope = next(e for e in current["scopes"] if e["scope"] == "seed_1009_gaussian")
    restored = {}
    with tarfile.open(root / scope["archive"], "r|gz") as archive:
        for member in archive:
            if member.name in ("DATA.npz", "DATASET.json", "MODELS.json"):
                check.require(member.isfile() and member.name not in restored, "identity", "unique identity file")
                restored[member.name] = archive.extractfile(member).read()
    for name in ("DATA.npz", "DATASET.json", "MODELS.json"):
        check.require(restored[name] == retained[name], "identity", f"raw exact {name}")
    original_identity, original_arrays = identity(retained)
    resumed_identity, resumed_arrays = identity(restored)
    check.require(set(original_arrays) == set(resumed_arrays), "identity", "NPZ array inventory")
    for name, arr in original_arrays.items():
        other = resumed_arrays[name]
        check.require(arr.dtype == other.dtype and arr.shape == other.shape and arr.tobytes() == other.tobytes(),
                      "identity", f"exact array dtype/shape/storage {name}")
    for key, value in original_identity.items():
        check.require(value == resumed_identity[key] == recovery["data_identity"][key] ==
                      resumed["original"][key] == resumed["observed"][key], "identity", key)
        check.require(resumed["checks"][key] is True, "identity", f"author assertion {key}")
    ids = original_arrays["ids"].tolist()
    check.require(ids == [f"confirmation:gaussian:32001009:{i}" for i in range(384)],
                  "identity", "exact registered trajectory IDs")
    metadata = json.loads(retained["DATASET.json"])
    check.require(metadata == {"data_seed": 32001009, "dataset_digest": original_identity["dataset_sha256"],
                               "npz_sha256": original_identity["npz_sha256"]}, "identity", "dataset metadata")
    check.require(original_identity["model_file_sha256"] ==
                  frozen["artifacts_sha256"]["training/seed_1009/MODELS.json"], "identity", "frozen model exact")
    check.require(resumed["operational_recovery_sha256"] == digest_file(recovery_path), "binding", "identity to recovery")
    for doc in (recovery, timing, current, old_index):
        check.require(doc["source_commit"] == frozen["source_commit"], "binding", "scientific source commit")
    for doc in (recovery, timing):
        check.require(doc["freeze_sha256"] == freeze_hash, "binding", "global freeze digest")

    raw_log = Path(recovery["producer_log"]["original_path"]).read_bytes()
    log_record = recovery["producer_log"]
    check.require(raw_log == retained["OPERATIONAL_PRODUCER_LOG.raw"], "logs", "raw failed log exact")
    check.require(len(raw_log) == log_record["bytes"] == 8192 and digest_bytes(raw_log) == log_record["sha256"],
                  "logs", "raw log binding")
    check.require(not raw_log.endswith(b"\n") and not log_record["ends_with_newline"], "logs", "truncated final line")
    check.require(raw_log.decode().endswith(log_record["tail_verbatim"]), "logs", "verbatim recorded tail")
    check.require(b"Traceback (most recent call last):" in raw_log and raw_log[-1:] == b"^",
                  "logs", "traceback without exception-final-line")
    original_lines = [json.loads(line) for line in raw_log.splitlines() if line.startswith(b'{"phase"')]
    new_log = (root / "operational_logs/main_resume1.log").read_bytes()
    check.require(len(new_log) == timing["output_log_bytes"] and digest_bytes(new_log) == timing["output_log_sha256"],
                  "logs", "resume log binding")
    new_lines = [json.loads(line) for line in new_log.splitlines()]
    for lines, expected in ((original_lines, old_index["scopes"]), (new_lines, current["scopes"][12:])):
        check.require(len(lines) == len(expected), "logs", "successful log entry count")
        for record, entry in zip(lines, expected):
            check.require(record.pop("phase") == "main_confirmation" and record == entry,
                          "logs", "stdout and index exact")
    check.require(timing["returncode"] == 0 and timing["status"] == "exited", "costs", "recorded resume success")
    check.require(timing["command"][1:] == ["-u", "-m", "experiments.analytic_event_neuron.round3.run",
                  "--run-dir", str(root)], "costs", "same frozen CLI no selection override")
    for key in ("child_cpu_ns", "native_requests", "native_ticks", "parent_cpu_ns", "wall_ns"):
        check.require(recovery["failed_attempt_costs"][key] is None, "costs", "unknown failed-attempt cost remains null")
    for key in ("exception_class", "exception_errno", "exception_final_message"):
        check.require(recovery[key] is None, "costs", "unknown causal exception remains null")
    check.require(recovery["reported_producer_exit_code"] == 1, "costs", "parent-observed original failure")
    check.require(not recovery["included_in_utility_estimation"] and not recovery["new_independent_sample"] and
                  not resumed["new_independent_sample"] and not resumed["initial_failed_attempt_included_in_utility_estimation"],
                  "costs", "failed attempt excluded and no extra independent sample")
    check.require(not timing["initial_failed_attempt_cost_included"] and "overlaps" in timing["measurement_scope"],
                  "costs", "overlap and failure scope disclosed")
    success_ns = sum(x["scope_wall_ns_including_replay_and_archive"] for x in current["scopes"][12:])
    check.require(0 < success_ns <= timing["wall_ns"], "costs", "successful scopes nested in resumption wall")
    utc_elapsed = (datetime.fromisoformat(timing["completed_utc"]) - datetime.fromisoformat(timing["created_utc"])).total_seconds()
    check.require(abs(utc_elapsed - timing["wall_ns"] / 1e9) < 1, "costs", "UTC and monotonic timer consistent")
    check.require(datetime.fromisoformat(recovery["completed_utc"]) < datetime.fromisoformat(timing["created_utc"]),
                  "costs", "preservation completed before resumption")
    verify_freeze(root, repo, check)
    inputs = {name: digest_file(root / name) for name in ("FREEZE.json",
              "MAIN_OPERATIONAL_RECOVERY.json", "MAIN_RESUME1_IDENTITY.json", "MAIN_RESUME1_EXECUTION.json",
              "main/RUN_INDEX.json", "operational_logs/main_resume1.log")}
    return {
        "schema": "hepta.round3.independent-operational-recovery-review.v1", "passed": True,
        "created_utc": datetime.now(timezone.utc).isoformat(), "checks": sum(check.counts.values()),
        "checks_by_group": dict(check.counts), "script_sha256": digest_file(__file__), "inputs_sha256": inputs,
        "protocol_repository_path": PROTOCOL_REL, "protocol_sha256": digest_file(repo / PROTOCOL_REL),
        "external_descriptor_sha256": digest_file(descriptor_path), "source_commit": frozen["source_commit"],
        "archive": {"parts": 2, "sha256": descriptor["sha256"], "bytes": len(combined),
                    "manifest_sha256": manifest_digest, "all_member_hashes_verified": True,
                    "data_members": len(observed), "original_files": len(original_files),
                    "original_file_bytes": recovery["original_file_bytes"],
                    "original_directory_metadata_records": len(failure_state["original_directories"])},
        "identity": original_identity, "all_11_identity_fields_exact": True,
        "all_14_npz_arrays_exact": len(original_arrays) == 14, "original_12_index_entries_exact": True,
        "completed_scope_count": 15, "unique_registered_trajectories": 5760,
        "resume_wall_seconds": timing["wall_ns"] / 1e9,
        "nested_three_scope_wall_seconds": success_ns / 1e9,
        "non_scope_resume_overhead_seconds": (timing["wall_ns"] - success_ns) / 1e9,
        "resume_process_tree_cpu_seconds": timing["child_user_cpu_seconds"] + timing["child_system_cpu_seconds"],
        "failed_attempt_costs": recovery["failed_attempt_costs"],
        "scientific_data_generated_by_this_review": False, "native_calls_by_this_review": 0,
        "archives_extracted_to_disk_by_this_review": 0,
        "required_report_wording": [
            "One original MAIN process exited1 after12 completed scopes; final exception class and errno are unknown.",
            "The failure coincided with observed shared-disk exhaustion; that association does not establish its precise cause.",
            "The frozen CLI rebuilt the same registered confirmation data, IDs, and models exactly; no new independent draw or seed was introduced.",
            "The incomplete attempt is preserved and excluded from utility estimation; its unmeasured work and costs remain null, not zero.",
            "The resume process-tree wall/CPU receipts describe the resumed invocation; its wall time overlaps the three successful scope timers and must not be added to them.",
            "Archive restoration and this review generated no scientific data; this statement must not be applied to the resumed CLI's deterministic data rebuild.",
        ],
        "independent_verification_limits": [
            "Original exit1 was observed by the parent session and reported in the preservation receipt; no separate raw wait-status trace was retained.",
            "Atomic rename and archive verification before deletion are author-recorded operational events, not independently observed syscalls.",
            "All original file bytes and modes were checked against the sealed inventory; original directory modes are metadata records rather than unpacked directories.",
            "Full original native replay and successful-scope scientific audits are separate receipts; this audit hashes their archives and independently checks the recovery identities without rerunning those computations.",
        ],
        "review_invocation_notes": [
            "The first script invocation failed at its initial freeze check because the reviewer assumed a run-relative PROTOCOL.json. The protocol is repository-relative. The original script and failure receipt are preserved; the correction retains the identical frozen SHA256 requirement and no scientific work was run.",
            "The second invocation rejected the intentionally distinct schema identifiers of the outer recovery receipt and archived failed-attempt snapshot. Both schema identifiers are now asserted independently; equality remains required for all shared operational fields. The pre-correction script and failed invocation receipt are preserved.",
            "One preliminary read-only archive probe printed an uncapped member listing; subsequent probes and this script bound their output. No scientific files were written.",
            "One preliminary rg path used an unnecessary brace expression and returned exit2; the intended load_data definition was then read directly. No scientific execution occurred.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.run_dir, args.repo, args.descriptor)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"],
                      "output": str(args.output), "sha256": digest_file(args.output)}))
