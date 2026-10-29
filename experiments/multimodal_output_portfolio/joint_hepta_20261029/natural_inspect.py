"""Read only the two completed, pinned natural-study Actions artifacts.

Uses the official gh CLI and Python's standard library. It never imports Torch,
executes checkpoints, trains a model, fetches source media, or opens media files.
Recorded tensor hashes are cross-checked, not recomputed without Torch; archived
checkpoint-file and whole-archive SHA-256 identities are independently checked.
"""

import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RUN = 40835309016
HEAD = "86baffaeb8b99c151b2f36fd3824242f301a1580"
PINS = {
    "generator": {"job": 123318581258, "artifact": 12880099305, "bytes": 111168834,
                  "sha256": "a837e73c23c604d0879defb2695412e4900882d3addad33fcb34461634a4f97a"},
    "observer": {"job": 123318580900, "artifact": 12880522575, "bytes": 584034372,
                 "sha256": "3198e1668ea5792a73b9215adb7688067d5a004519dbfe3c2442691cdab3a4cf"},
}
SOURCE_CACHE = {}
PRESERVED_OBSERVER_JSON = (
    "observer/OBSERVER_FREEZE.json", "observer/RESULT.json", "observer/ALLOCATION.json",
)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def stream_digest(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b""):
        result.update(block)
    return result.hexdigest()


def api(path):
    result = subprocess.run(["gh", "api", "--method", "GET", f"repos/{REPOSITORY}/{path}"],
                            capture_output=True, text=True, check=True, timeout=120)
    return json.loads(result.stdout)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


class Archive:
    def __init__(self, archive):
        self.archive = archive
        self.names = archive.namelist()
        self.json_sha256 = {}
        self.trace_hashes = []

    def member(self, suffix, optional=False):
        path = PurePosixPath(suffix)
        check(not path.is_absolute() and ".." not in path.parts, "Unsafe artifact member reference")
        matches = [name for name in self.names if name == suffix or name.endswith("/" + suffix)]
        if optional and not matches:
            return None
        check(len(matches) == 1, f"Missing or ambiguous artifact member: {suffix}")
        return matches[0]

    def json(self, suffix, optional=False, trace=False):
        name = self.member(suffix, optional)
        if name is None:
            return None
        check(self.archive.getinfo(name).file_size <= 16 * 1024 * 1024, f"Oversized JSON: {suffix}")
        value = self.archive.read(name)
        sha = hashlib.sha256(value).hexdigest()
        if trace:
            self.trace_hashes.append((suffix, sha))
        else:
            self.json_sha256[suffix] = sha
        return json.loads(value)

    def binary_identity(self, suffix, expected):
        name = self.member(suffix)
        size = self.archive.getinfo(name).file_size
        check(size <= 256 * 1024 * 1024, "Oversized archived checkpoint")
        with self.archive.open(name, "r") as stream:
            actual = stream_digest(stream)
        check(actual == expected, f"Archived checkpoint SHA mismatch: {suffix}")
        return {"file": suffix, "bytes": size, "sha256": actual}


def source_identities(identities):
    allowed = {"natural_train.py", "natural_data.py", "natural_eval.py", "natural_protocol.json", "learning.py", "media.py"}
    for name, expected in identities.items():
        check(name in allowed, "Unknown frozen source identity: " + name)
        if name not in SOURCE_CACHE:
            value = api("contents/experiments/multimodal_output_portfolio/joint_hepta_20261029/" + name + "?ref=" + HEAD)
            SOURCE_CACHE[name] = hashlib.sha256(base64.b64decode(value["content"], validate=False)).hexdigest()
        check(SOURCE_CACHE[name] == expected, "Implementation differs from frozen source commit: " + name)
    return {"source_commit": HEAD, "sha256": identities, "verified_from_commit": True}


def preserve_observer_json(archive, output):
    """Preserve only already-validated original JSON bytes, never model/media files."""
    files = []
    for name in PRESERVED_OBSERVER_JSON:
        check(archive.member(name) == name, "Unexpected exact observer archive member: " + name)
        check(archive.archive.getinfo(name).file_size <= 16 * 1024 * 1024, "Oversized preserved JSON")
        original = archive.archive.read(name)
        original_sha = hashlib.sha256(original).hexdigest()
        check(archive.json_sha256.get(name) == original_sha, "Preservation requires prior successful JSON validation")
        compressed = gzip.compress(original, compresslevel=9, mtime=0)
        check(gzip.decompress(compressed) == original, "Preservation changed original JSON bytes")
        relative = Path("preserved") / (name + ".gz")
        path = Path(output) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(compressed)
        files.append({"archive_member": name, "path": relative.as_posix(),
                      "original_bytes": len(original), "original_sha256": original_sha,
                      "stored_bytes": len(compressed), "stored_sha256": hashlib.sha256(compressed).hexdigest()})
    manifest = {"schema": "hepta.joint-natural.preserved-observer-json.v1", "source_run": RUN,
                "source_head": HEAD, "source_artifact_id": PINS["observer"]["artifact"],
                "source_artifact_sha256": PINS["observer"]["sha256"],
                "encoding": "gzip", "gzip_mtime": 0, "gzip_compression_level": 9,
                "original_bytes_preserved": True, "media_or_weights_exported": False, "files": files}
    write(Path(output) / "preserved/MANIFEST.json", manifest)
    return manifest


def allocation(archive, role):
    value = archive.json(role + "/ALLOCATION.json")
    check(value["schema"] == "hepta.joint-natural-source-allocation.v1", "Unknown allocation schema")
    body = dict(value); expected = body.pop("allocation_sha256")
    check(digest(body) == expected and digest(value["protocol"]) == value["protocol_sha256"], "Allocation/protocol digest mismatch")
    ids = [row["source_id"] for row in value["selected"]]
    check(len(ids) == len(set(ids)), "Repeated allocated source")
    for row in value["selected"]:
        if row["study_role"] == "fresh_observer_calibration":
            check(row["source_id"] not in value["excluded_source_ids"], "An old source was relabelled fresh")
        else:
            check(row["role"] == row["study_role"], "Original source role changed")
    summary = {"allocation_sha256": expected, "protocol_sha256": value["protocol_sha256"],
               "source_role_counts": dict(Counter(row["study_role"] for row in value["selected"])),
               "excluded_source_ids_count": len(value["excluded_source_ids"]),
               "candidate_window_rejections": len(value["fresh_candidate_window_rejections"]),
               "candidate_window_rejections_sha256": digest(value["fresh_candidate_window_rejections"]),
               "metadata_processing_amendment": value["metadata_processing_amendment"]}
    return value, summary


def ce(values, weights):
    maximum = max(-2 * value for value in values)
    return -(maximum + math.log(math.fsum(weight * math.exp(-2 * value - maximum)
                                        for value, weight in zip(values, weights, strict=True)))) / 2


def trace(archive, row, location, profile_sha):
    check(row["trajectory"].endswith(location), "Trajectory reference belongs to another phase")
    value = archive.json(location, trace=True)
    check(value["source_id"] == row["source"] and value["failure"] == row["failure"]
          and abs(value["net_return"] - row["return"]) < 1e-12
          and value["profile_sha256"] == profile_sha
          and value["outcome"]["artifact_sha256"] == row["artifacts"], "Physical trajectory disagrees with its result row")
    if row["failure"] is None:
        check(set(dict(row["artifacts"])) == {"image", "audio", "video", "text"}, "Successful delivery lacks a modality")
        for name in ("image.png", "audio.wav", "video.gif", "text.txt"):
            archive.member(location.removesuffix("TRAJECTORY.json") + "outputs/" + name)


def evaluation(archive, value, sources, expected_events, mode, label, profile_sha):
    rows = value["rows"]
    check(set(row["source"] for row in rows) == set(sources), "Evaluation lost a source")
    keys = {(row["source"], row["event_id"], row["draw"]) for row in rows}
    expected = {(source, event, draw) for source in sources for event in expected_events[source] for draw in range(2)}
    check(keys == expected and len(keys) == len(rows), "Missing or repeated frozen evaluation event/draw")
    counts = Counter(row["source"] for row in rows)
    weights = [1 / (len(sources) * counts[row["source"]]) for row in rows]
    check(weights == value["source_uniform_weights"], "Evaluation event counts changed source weighting")
    for row in rows:
        trace(archive, row, f"training/{mode}/{label}/{row['event_id']}-draw-{row['draw']}/TRAJECTORY.json", profile_sha)
    for key, field in (("population_ce", "return"), ("population_ce_with_audit", "net_with_audit_close")):
        check(abs(ce([row[field] for row in rows], weights) - value[key]) < 1e-12, "CE does not include the complete source-weighted law")
    failures = sum(row["failure"] is not None for row in rows)
    check(failures == value["failures"] and len(rows) == value["actual_draws"], "Evaluation failure/count summary changed")
    return {key: value[key] for key in ("sources", "actual_draws", "population_ce", "population_ce_with_audit", "mean_net", "mean_cost", "mean_utility", "failures", "semantic_qualified", "never_seen_claim")}


def generator(archive):
    plan, plan_info = allocation(archive, "generator")
    prepared = archive.json("generator/RESULT.json")
    value = archive.json("training/RESULTS.json")
    protocol = archive.json("training/PROTOCOL.json")
    profile = archive.json("training/PROFILE.json")
    check(value["schema"] == protocol["schema"] == "hepta.joint-natural-restoration-diagnostic.v1"
          and prepared["schema"] == "hepta.joint-natural-run.v1" and prepared["phase"] == "generator", "Unknown generator artifact schema")
    check(value["status"] == "completed_real_media_diagnostic", "Natural training did not complete: " + value["status"])
    check(digest(protocol) == value["protocol_sha256"] and digest(profile) == value["profile_sha256"]
          and value["allocation_sha256"] == plan_info["allocation_sha256"], "Generator protocol/allocation/profile identity changed")
    check(value["semantic_qualified"] is False and value["efficacy_qualified"] is False, "Diagnostic result makes an unsupported qualification claim")
    originals = [row for row in plan["selected"] if row["study_role"] == "generator_train"]
    order = [row["source_id"] for row in originals]
    check(len(order) == 8 and protocol["source_order"] == order and protocol["fit_sources"] == order[:4]
          and protocol["diagnostic_sources"] == order[4:] and set(value["arms"]) == {"dual", "ordinary"}, "Original eight-source inner split or arm set changed")
    expected_events = {row["source_id"]: [row["source_id"] + f"-joint-{i}" for i in range(row["retained_event_count"])] for row in originals}
    output = {"status": value["status"], "allocation": plan_info, "arms": {},
              "profile_sha256": value["profile_sha256"], "protocol_sha256": value["protocol_sha256"],
              "source_code": source_identities(value["source_code_sha256"]),
              "preparation_cpu_seconds": prepared["cpu_seconds_self_plus_completed_children"],
              **{key: value[key] for key in ("semantic_qualified", "efficacy_qualified", "never_seen_data_claim", "unique_internal_test_sources", "total_cpu_seconds", "total_wall_seconds", "media_clock", "internal_test_ce_dual_minus_ordinary", "internal_test_ce_with_audit_dual_minus_ordinary")}}
    for mode, arm in value["arms"].items():
        result = {"parameters": arm["parameters"], "initial_parameters_sha256": arm["initial_parameters_sha256"], "phases": {}}
        for phase, updates in (("pretraining", 256), ("joint", 32)):
            record = arm[phase]; entries = record["updates"]
            check(len(entries) == record["completed_updates"] == updates, "Incomplete registered natural optimizer updates")
            rows = [row for entry in entries for row in entry["episodes"]]
            check(len(rows) == record["actual_episodes"] == updates * 4, "Actual training episode count changed")
            check(all(row["source"] in protocol["fit_sources"] and row["event_id"] in expected_events[row["source"]] for row in rows), "Internal-test or unregistered event entered training")
            for index, entry in enumerate(entries):
                check(entry["update"] == index and len(entry["episodes"]) == 4, "Training update ordering/count mismatch")
                for draw, row in enumerate(entry["episodes"]):
                    trace(archive, row, f"training/{mode}/{phase}/update-{index:03d}/draw-{draw}/TRAJECTORY.json", value["profile_sha256"])
            gradients = {key: record[key] for key in record if key.startswith(("gradient_max_", "score_only_gradient_max_"))}
            check(all(math.isfinite(g) and g >= 0 for group in gradients.values() for g in group.values()), "Nonfinite/negative gradient evidence")
            result["phases"][phase] = {"updates": len(entries), "actual_episodes": len(rows),
                "failures": sum(row["failure"] is not None for row in rows),
                "first_supervised_loss": entries[0]["supervised_loss"], "last_supervised_loss": entries[-1]["supervised_loss"],
                "initial_parameters_sha256": record["initial_parameters_sha256"], "final_parameters_sha256": record["final_parameters_sha256"],
                "gradients": {key: group for key, group in gradients.items() if key.endswith("by_module") or key.startswith("score_only")},
                "nonzero_parameter_gradient_count": sum(g > 0 for g in record["gradient_max_l1_by_parameter"].values())}
        for label, sources in (("fitting_diagnostic", protocol["fit_sources"]), ("internal_test_diagnostic", protocol["diagnostic_sources"])):
            result[label] = evaluation(archive, arm[label], sources, expected_events, mode, label, value["profile_sha256"])
        manifest = archive.json(f"training/{mode}/MODEL.pt.manifest.json")
        check(manifest == arm["checkpoint"] and manifest["model_sha256"] == arm["joint"]["final_parameters_sha256"], "Final model parameter/checkpoint identities disagree")
        result["checkpoint"] = {**archive.binary_identity(f"training/{mode}/MODEL.pt", manifest["file_sha256"]),
                                "model_sha256_recorded": manifest["model_sha256"], "payload_sha256_recorded": manifest["payload_sha256"],
                                "tensor_hash_recomputed_without_torch": False, "manifest_sha256": digest(manifest)}
        output["arms"][mode] = result
    check(output["arms"]["dual"]["initial_parameters_sha256"] == output["arms"]["ordinary"]["initial_parameters_sha256"], "Unmatched initial model weights")
    check(output["arms"]["dual"]["parameters"] == output["arms"]["ordinary"]["parameters"], "Unmatched parameter counts")
    return output


def accuracy(report, rows, kind):
    labels = [row[kind + "_id"] for row in rows]; ids = [row["source_id"] for row in rows]
    predicted = report["predictions"]; counts = Counter(ids)
    check(report["labels"] == labels and report["source_ids"] == ids and len(predicted) == len(rows), "OOF rows/labels/source ordering changed")
    correct = [p == label for p, label in zip(predicted, labels, strict=True)]
    weighted = math.fsum(float(ok) / (len(counts) * counts[sid]) for ok, sid in zip(correct, ids, strict=True))
    check(abs(weighted - report["source_uniform_accuracy"]) < 1e-12 and sum(correct) == report["correct"]
          and abs(sum(correct) / len(rows) - report["event_accuracy"]) < 1e-12
          and report["events"] == len(rows) and report["sources"] == len(counts), "OOF accuracy/count disagrees with every retained source event")
    return {"source_uniform_accuracy": weighted, "event_accuracy": sum(correct) / len(rows),
            "correct": sum(correct), "events": len(rows), "sources": len(counts)}


def observer(archive):
    plan, plan_info = allocation(archive, "observer")
    value = archive.json("observer/RESULT.json")
    freeze = archive.json("observer/OBSERVER_FREEZE.json")
    check(value["schema"] == "hepta.joint-natural-run.v1" and value["phase"] == "observer"
          and freeze["schema"] == "hepta.joint-natural-observer-freeze.v1", "Unknown observer artifact schema")
    check(value["semantic_qualification"] is False and value["old_policy_or_qualification_accessed"] is False
          and freeze["generator_semantic_qualification"] is False, "Observer artifact makes an unsupported semantic/holdout claim")
    check(freeze["allocation_sha256"] == plan_info["allocation_sha256"] and freeze["protocol_sha256"] == plan_info["protocol_sha256"], "Observer freeze/allocation mismatch")
    rows = [{**event, "source_id": source["source_id"], "fold": source["fold"]}
            for source in plan["selected"] if source["study_role"] == "observer_train"
            for event in source["events"][:source["retained_event_count"]]]
    counts = Counter(row["source_id"] for row in rows)
    check(len(counts) == value["observer_training_sources"] == 64 and value["observer_training_events"] == len(rows)
          and value["optimizer_updates"] == freeze["optimizer_updates"], "Frozen observer training source/event/update coverage changed")
    source_hashes = {}
    for sid in counts:
        receipt = archive.json(f"observer/actual/prepared/observer_train/{sid}/RECEIPT.json")
        check(receipt["role"] == "observer_train" and receipt["source_id"] == sid
              and receipt["allocation_sha256"] == plan_info["allocation_sha256"]
              and len(receipt["events"]) == counts[sid], "Observer prepared source identity/count mismatch")
        source_hashes[sid] = receipt["original_sha256"]
    check(len(set(source_hashes.values())) == 64 and sorted(source_hashes.values()) == freeze["training_source_hashes"], "Observer training media hashes changed or repeat")
    result = {"status": value["status"], "allocation": plan_info, "selected": {}, "candidates": {},
              "freeze_sha256": digest(freeze), "source_code": source_identities(freeze["source_code_sha256"]),
              "training_original_source_hashes_sha256": digest(source_hashes),
              "source_weights": [{"source_id": sid, "events": count, "source_weight": 1 / len(counts), "event_weight": 1 / (len(counts) * count)} for sid, count in counts.items()],
              **{key: value[key] for key in ("development_passed", "observer_training_sources", "observer_training_events", "optimizer_updates", "semantic_qualification", "old_policy_or_qualification_accessed", "cpu_seconds_self_plus_completed_children", "wall_seconds")}}
    gates = []
    for kind in ("action", "sound"):
        classes = sorted(map(int, plan["ontology"][kind])); majorities = []
        for held in range(5):
            training = [row for row in rows if row["fold"] != held]; tc = Counter(row["source_id"] for row in training)
            mass = {label: 0. for label in classes}
            for row in training:
                mass[row[kind + "_id"]] += 1 / (len(tc) * tc[row["source_id"]])
            majorities.append(max(classes, key=lambda label: mass[label]))
        candidates = freeze["candidates"][kind]
        check([r["candidate"] for r in candidates] == plan["protocol"]["candidate_order"], "Observer candidate order changed")
        result["candidates"][kind] = []
        for candidate in candidates:
            check(sorted(f["fold"] for f in candidate["folds"]) == list(range(5)), "Incomplete OOF source folds")
            check(all(p in classes for p in candidate["out_of_fold"]["predictions"]), "Observer prediction outside the original ontology")
            check(candidate["majority_control"]["predictions"] == [majorities[row["fold"]] for row in rows], "Majority control was not fitted within each training fold")
            result["candidates"][kind].append({"candidate": candidate["candidate"], "out_of_fold": accuracy(candidate["out_of_fold"], rows, kind),
                                                "majority_control": accuracy(candidate["majority_control"], rows, kind)})
        best = max(candidates, key=lambda r: r["out_of_fold"]["source_uniform_accuracy"]); selected = freeze["selected"][kind]
        check(selected["candidate"] == best["candidate"] and selected["out_of_fold"] == best["out_of_fold"] and selected["majority_control"] == best["majority_control"], "Frozen observer selection changed")
        passed = best["out_of_fold"]["source_uniform_accuracy"] >= .6 and best["out_of_fold"]["source_uniform_accuracy"] > best["majority_control"]["source_uniform_accuracy"]
        gates.append(passed)
        check(PurePosixPath(selected["checkpoint_file"]).name == selected["checkpoint_file"], "Unsafe observer checkpoint reference")
        result["selected"][kind] = {"candidate": selected["candidate"], "adequacy_gate": passed,
            "checkpoint": archive.binary_identity("observer/" + selected["checkpoint_file"], selected["checkpoint_sha256"])}
    check(freeze["development_passed"] == value["development_passed"] == all(gates), "OOF development flag contradicts actual predictions")
    marker = archive.json("observer/CALIBRATION_CONSUMPTION_STARTED.json", optional=True)
    calibration = archive.json("observer/CALIBRATION.json", optional=True)
    fresh = [r["source_id"] for r in plan["selected"] if r["study_role"] == "fresh_observer_calibration"]
    receipts = [name for name in archive.names if "/prepared/fresh_observer_calibration/" in name and name.endswith("/RECEIPT.json")]
    if marker is not None:
        check(all(gates) and marker["allocation_sha256"] == plan_info["allocation_sha256"] and marker["observer_freeze_sha256"] == digest(freeze), "Fresh consumption was not preceded by the viable frozen observer")
    else:
        check(not receipts and calibration is None and value["fresh_calibration_media_accessed"] is False, "Fresh media used without the consumption ledger")
    if not all(gates):
        check(marker is None and value["status"] == "observer_development_gate_failed" and value["fresh_calibration_predictions"] == 0, "Failed observer gate was bypassed")
    result["fresh_consumption"] = {"marker_present": marker is not None, "prepared_receipt_count": len(receipts),
        "allocated_source_ids": fresh, "reserved_as_consumed_for_future_studies": fresh if marker else [],
        "run_media_access_flag": value["fresh_calibration_media_accessed"], "run_predictions": value["fresh_calibration_predictions"],
        "marker": marker, "calibration_file_present": calibration is not None}
    result["generation_reliability"] = {"field_present_in_run_result": "generated_output_reliability_established" in value,
        "run_result_value": value.get("generated_output_reliability_established"),
        "freeze_generator_semantic_qualification": freeze["generator_semantic_qualification"],
        "calibration_flags": None if calibration is None else {k: calibration[k] for k in ("adequate_on_original_media", "generated_output_reliability_established", "generator_semantic_qualification")},
        "absent_field_is_not_a_pass": True}
    return result


def run(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.joint-natural.read-only-evidence.v1", "source_run": RUN, "source_head": HEAD,
              "artifacts": {}, "errors": [], "training_executed": False, "new_media_requested": False,
              "archived_media_bytes_read": False, "scientific_positive_effect_required": False}
    try:
        source = api(f"actions/runs/{RUN}"); write(output / "metadata/SOURCE_RUN.json", source)
        check(source["head_sha"] == HEAD and source["run_attempt"] == 1, "Source run/head/attempt identity changed")
        for role, pin in PINS.items():
            record = {"artifact_id": pin["artifact"], "job_id": pin["job"]}; result["artifacts"][role] = record
            try:
                job = api(f"actions/jobs/{pin['job']}"); artifact = api(f"actions/artifacts/{pin['artifact']}")
                write(output / f"metadata/{role}_JOB.json", job); write(output / f"metadata/{role}_ARTIFACT.json", artifact)
                check(job["run_id"] == RUN and job["head_sha"] == HEAD and job["run_attempt"] == 1
                      and job["status"] == "completed" and job["conclusion"] == "success", f"Original {role} execution job did not complete successfully")
                check(artifact["name"] == f"joint-natural-{role}-{HEAD}" and not artifact["expired"]
                      and artifact["size_in_bytes"] == pin["bytes"] and artifact["digest"] == "sha256:" + pin["sha256"]
                      and artifact["workflow_run"]["id"] == RUN and artifact["workflow_run"]["head_sha"] == HEAD,
                      "Original artifact identity changed")
                path = output / (role + ".zip")
                with path.open("xb") as stream:
                    subprocess.run(["gh", "api", "--method", "GET", f"repos/{REPOSITORY}/actions/artifacts/{pin['artifact']}/zip"],
                                   stdout=stream, check=True, timeout=600)
                with path.open("rb") as stream:
                    before = stream_digest(stream)
                check(path.stat().st_size == pin["bytes"] and before == pin["sha256"], "Downloaded archive bytes/hash differ from pinned source")
                record.update(file_bytes=path.stat().st_size, before_sha256=before, original_job_conclusion=job["conclusion"])
                try:
                    with zipfile.ZipFile(path, "r") as stream:
                        archive = Archive(stream)
                        record["evidence"] = generator(archive) if role == "generator" else observer(archive)
                        if role == "observer":
                            record["preserved_original_json"] = preserve_observer_json(archive, output)
                        record.update(json_file_sha256=archive.json_sha256, physical_trajectories_checked=len(archive.trace_hashes),
                                      ordered_trajectory_hashes_sha256=digest(archive.trace_hashes))
                finally:
                    with path.open("rb") as stream:
                        record["after_sha256"] = stream_digest(stream)
                    check(record["after_sha256"] == before, "Read-only inspection modified the original archive")
            except Exception as exc:
                record["inspection_error"] = f"{type(exc).__name__}: {exc}"
                result["errors"].append(role + ": " + record["inspection_error"])
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    result["status"] = "read_only_inspection_complete" if not result["errors"] else "inspection_incomplete_or_failed"
    write(output / "REPORT.json", result)
    compact = {**result, "artifacts": {}}
    for role, record in result["artifacts"].items():
        compact["artifacts"][role] = {key: value for key, value in record.items() if key != "json_file_sha256"}
        compact["artifacts"][role]["json_files_checked"] = len(record.get("json_file_sha256", {}))
        compact["artifacts"][role]["json_file_identities_sha256"] = digest(record.get("json_file_sha256", {}))
    print("RESULT_JSON=" + json.dumps(compact, sort_keys=True, allow_nan=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output)
    raise SystemExit(0 if not report["errors"] else 1)
