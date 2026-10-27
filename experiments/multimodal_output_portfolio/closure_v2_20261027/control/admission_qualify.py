"""One actual native execution per newly allocated semantic-admission pair."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...continuation_20261027.control.client import Native, Q, numerical_projection
from ...continuation_20261027.control.training import prefix
from ...continuation_20261027.joint.data import historical_corpus
from ...continuation_20261027.joint.run import reference_observer
from ...v6.data import SourceCorpus, SourceSplit, _parse_images, _parse_labels
from .adapter import Generator, scalar_feedback
from .admission_binding import BoundAdmission
from .admission_protocol import SPEC
from .protocol import preserve_sources, sha, write
from .selective_data import tasks
from .selective_metrics import summarize
from .tasks import persist_tasks
from .verify_media import independent_score, read_outputs, verify_sources


ALLOCATION_SHA256 = "fd18d5dfd6a303285e74cbc51657b5694839d36db863d875dc618ff8441a50f6"


def source_hashes(value):
    if isinstance(value, str) and value.startswith("mnist:"):
        yield value.rsplit(":", 1)[1]
    elif isinstance(value, dict):
        for child in value.values():
            yield from source_hashes(child)
        yield from value.get("head_fit_validation_excluded_pixel_hashes", [])
    elif isinstance(value, list):
        for child in value:
            yield from source_hashes(child)


def allocated_corpus(assets, allocation):
    if sha(allocation) != ALLOCATION_SHA256:
        raise ValueError("New source allocation is not the approved fixed cohort")
    manifest = json.loads(allocation.read_text())
    paths = [assets / "ndu-data" / name for name in ("t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz")]
    if [sha(p) for p in paths] != [manifest["official_test_image_sha256"], manifest["official_test_label_sha256"]]:
        raise ValueError("Official test pixels or labels changed")
    if hashlib.md5(paths[1].read_bytes()).hexdigest() != "ec29112dd5afa0611ce80d1b7f02629c":
        raise ValueError("Published official test-label MD5 mismatch")
    images, hashes = _parse_images(gzip.decompress(paths[0].read_bytes()))
    labels = _parse_labels(gzip.decompress(paths[1].read_bytes()))
    if images.shape != (10000, 1, 28, 28) or len(labels) != 10000:
        raise ValueError("Official test IDX count/shape differs")
    historical = historical_corpus(assets)
    excluded = {value for split in historical.splits.values() for value in split.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    seen, splits = set(), {}
    for path, expected in manifest["exclusion_source_pins"].items():
        if sha(path) != expected:
            raise ValueError("Source exclusion evidence changed")
        excluded.update(source_hashes(json.loads(Path(path).read_text())))
    if len(excluded) != manifest["excluded_pixel_hashes"]:
        raise ValueError("Rebuilt full historical source-exclusion count differs")
    for role in ("qualification_id", "qualification_ood"):
        record = manifest["splits"][role]
        ids = record["source_ids"]
        if record["pairs"] != SPEC[role + "_pairs"] or len(ids) != 2 * record["pairs"]:
            raise ValueError("Registered ID/OOD sample size changed")
        if hashlib.sha256("\n".join(ids).encode()).hexdigest() != record["identity_sha256"]:
            raise ValueError("Allocated source order changed")
        indices, selected_hashes = [], []
        for identity in ids:
            dataset, split, index, expected = identity.split(":")
            index = int(index)
            if dataset != "mnist" or split != "test" or expected != hashes[index] or expected in excluded | seen:
                raise ValueError("Allocated source pixels overlap or mismatch")
            indices.append(index)
            selected_hashes.append(expected)
            seen.add(expected)
        splits[role] = SourceSplit(images[indices].clone(), labels[indices].clone(), tuple(ids), tuple(selected_hashes))
    return SourceCorpus(splits, manifest)


def execute(task, generator, public_observer, private_observer, bound, binary, development, output):
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    bound.verify()  # A stale artifact must fail before any owner mutation.
    name = f"{task['role']}-{task['index']:04}"
    directory = output / "episodes" / name
    directory.mkdir(parents=True, exist_ok=False)
    model, calibration = development / "MODEL.json", development / "ENCODER_DOMAIN_PROOF.json"
    native = Native(binary)
    native.open(directory / "owner", name, task["expires"], model, calibration)
    if any(row["native_abstain"] for row in prefix(native, 0)):
        raise ValueError("Original owner refused the registered initial event")
    branches = {str(value): native.call({"command": "Forecast", "feedback_q24": value * Q,
        "branch": f"symbol-{value + 1}"}) for value in (-1, 0, 1)}
    initial, _ = generator.deliver(task["public"], 0, directory / "initial-delivery")
    scalar = scalar_feedback(initial["caption"], task["private"].labels[0].tolist())
    feedback_at = time.monotonic_ns()
    evidence = {"actual_initial_sha256": initial["sha256"], "scalar": scalar, "source": "already-delivered-current-output"}
    first = native.tick(1, scalar, evidence)
    closed = native.close()
    old_transcript = native.transcript
    native.finish()
    restart_at = time.monotonic_ns()
    resumed = Native(binary)
    resumed.case = name
    restored = resumed.call({"command": "Resume", "directory": str(directory / "owner"), "case": name,
        "expires": task["expires"], "model": str(model), "model_sha256": sha(model),
        "calibration": str(calibration), "calibration_sha256": sha(calibration)})
    if restored != closed or restored["durable_event_count"] != 5:
        raise ValueError("Feedback state was not durably recovered")
    hold, decision = resumed.tick(2, 0, evidence), resumed.tick(3, 0, evidence)
    ticks = [first, hold, decision]
    proposed = bool(decision["proposed_repair"])
    corrected = bool(proposed and not any(r["native_abstain"] for r in ticks) and task["budget"] >= 2)
    decision_at = time.monotonic_ns()
    if corrected != bool(proposed and task["expires"] >= 7 and task["budget"] >= 2):
        raise ValueError("Actual native admission differs from expiry/budget policy")
    write(directory / "GENERATION_PERMIT.json", {"native_authority": "DENY_ALL",
        "separate_bounded_research_host_scope": str(output.resolve()), "proposed": proposed,
        "native_nonabstention": not any(r["native_abstain"] for r in ticks),
        "generation_budget_remaining": task["budget"] - 1, "admitted": corrected,
        "production_authorization": False})
    candidate = generator.deliver(task["public"], 1, directory / "candidate-draft")[0] if corrected else initial
    prediction = bound.predict(initial, candidate, scalar, task["public"], public_observer)
    predicted_at = time.monotonic_ns()
    write(directory / "PREDICTION_BEFORE_COMMIT.json", prediction)
    terminal = directory / "terminal-host-decision"
    terminal.mkdir()
    confirmed = None
    if prediction["commit"]:
        paths = {key: str(terminal / Path(value).name) for key, value in candidate["paths"].items()}
        for key, value in paths.items():
            Path(value).write_bytes(Path(candidate["paths"][key]).read_bytes())
        confirmed = {**candidate, "paths": paths, "delivered_monotonic_ns": time.monotonic_ns(),
            "role": "bounded-host-semantic-confirmation-of-existing-candidate"}
        read_outputs(confirmed)
        write(terminal / "CONFIRMED.json", confirmed)
    else:
        write(terminal / "ABSTAINED.json", {"candidate_sha256": candidate["sha256"],
            "reason": "Frozen public semantic probability and entropic terminal rule", "initial_delivery_remains_recorded": True})
    committed_at = time.monotonic_ns()
    final_owner = resumed.close()
    transcript = old_transcript + resumed.transcript
    resumed.finish()
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    api_steps = sum(int(r["response"]["result"].get("native_transition_executed", False))
        for r in transcript if r["request"]["command"] == "Tick") + sum(len(b["ticks"]) for b in branches.values())
    forecast_replays = sum(b["ledger_validation_kernel_steps"] + b["original_journal_replayed_prefix_steps"] for b in branches.values())
    cold_replays = 2 * restored["durable_event_count"]
    kernels = api_steps + forecast_replays + cold_replays
    if (api_steps, forecast_replays, cold_replays, kernels) != (16, 24, 10, 50):
        raise ValueError("Future simulation or replay work escaped accounting")
    if numerical_projection(ticks) != numerical_projection(branches[str(scalar)]["ticks"]):
        raise ValueError("Native predicted trajectory differs from actual delayed feedback")
    fee = SPEC["task_sunk_fee"]
    sunk = kernels * fee["kernel"] + (1 + corrected) * fee["generator"] + fee["initial_delivery"] + (proposed and not corrected) * fee["refused_neural_proposal"]
    execution_wall, execution_cpu = time.perf_counter_ns() - started_wall, time.process_time_ns() - started_cpu
    score_wall, score_cpu = time.perf_counter_ns(), time.process_time_ns()
    grade = independent_score(private_observer, candidate, task["private"].pixels.numpy(), task["private"].labels[0].tolist())
    final_utility = SPEC["final_utility"]
    payoff = (final_utility["correct_commit"] if grade["strict_success"] else final_utility["incorrect_commit"]) - final_utility["commit_cost"] if prediction["commit"] else 0.
    record = {"role": task["role"], "index": task["index"], "condition": task["condition"],
        "source_ids": task["source_ids"], "declared_ood": task["declared_ood"], "expires": task["expires"], "budget": task["budget"],
        "feedback": scalar, "initial": initial, "candidate": candidate, "confirmed": confirmed,
        "actual_correction": corrected, "native_proposed": proposed, "native_refused": bool(proposed and not corrected),
        "actual_ticks": ticks, "forecast_branches": branches, "future_state_matches": True,
        "before_cold_close": closed, "cold_restored_state": restored, "final_owner_state": final_owner,
        "actual_original_kernel_executions": kernels, "actual_owner_api_ticks": api_steps,
        "forecast_replay_kernel_executions": forecast_replays, "cold_recovery_kernel_executions": cold_replays,
        "sunk_resource_fee": sunk, "terminal_payoff": payoff, "total_net_utility": payoff - sunk,
        "predicted_terminal_policy_moment": prediction["predicted_commit_moment"] if prediction["commit"] else 1.,
        "predicted_total_policy_moment": math.exp(final_utility["gamma"] * sunk) * (prediction["predicted_commit_moment"] if prediction["commit"] else 1.),
        "actual_total_policy_moment": math.exp(-final_utility["gamma"] * (payoff - sunk)),
        "strict_success": grade["strict_success"], "private_grade": grade, **prediction,
        "chronology": {"initial_delivery": initial["delivered_monotonic_ns"], "scalar_arrived": feedback_at,
            "process_restart": restart_at, "late_native_decision": decision_at,
            "candidate_readback": candidate["delivered_monotonic_ns"], "public_prediction": predicted_at,
            "terminal_host_decision": committed_at, "private_grade": time.monotonic_ns()},
        "wall_ns": execution_wall, "python_cpu_ns": execution_cpu,
        "native_child_user_cpu_seconds": children_after.ru_utime - children_before.ru_utime,
        "native_child_system_cpu_seconds": children_after.ru_stime - children_before.ru_stime,
        "private_score_wall_ns": time.perf_counter_ns() - score_wall, "private_score_python_cpu_ns": time.process_time_ns() - score_cpu,
        "per_case_native_execution": True, "fitted_probability_uses_this_calibration_cohort": False,
        "native_authority": "DENY_ALL", "production_authorization": False}
    write(directory / "TRANSCRIPT.json", transcript)
    write(directory / "EPISODE.json", record)
    return record


def run(assets, generator_path, binary, development, calibration, allocation, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    bound = BoundAdmission(calibration, development, generator_path, binary, assets)
    corpus = allocated_corpus(assets, allocation)
    groups = {role: tasks(corpus, role, SPEC[role + "_pairs"], 0, role, role == "qualification_ood",
        seed=SPEC["new_random_namespaces"][role]) for role in ("qualification_id", "qualification_ood")}
    for role, cases in groups.items():
        persist_tasks(cases, output / (role + "-inputs"))
        verify_sources(output / (role + "-inputs"), assets)
    write(output / "PROTOCOL.json", SPEC)
    (output / "SOURCE_ALLOCATION.json").write_bytes(allocation.read_bytes())
    (output / "CALIBRATOR.json").write_bytes((calibration / "CALIBRATOR.json").read_bytes())
    sources = preserve_sources(output / "executed-source")
    write(output / "QUALIFICATION_SEAL.json", {"registered_ns": time.time_ns(),
        "protocol_sha256": sha(output / "PROTOCOL.json"), "allocation_sha256": sha(allocation),
        "calibrator_sha256": sha(output / "CALIBRATOR.json"), "bound_admission_sha256": bound.fingerprint,
        "source_sha256": sources, "public_private_inputs": {role: {name: sha(output / (role + "-inputs") / name)
            for name in ("PUBLIC.pt", "PRIVATE.pt", "SOURCES.json")} for role in groups},
        "qualification_outputs_computed": False, "native_profile_unchanged": True})
    generator = Generator(generator_path)
    public_observer, private_observer = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    rows = []
    for role, cases in groups.items():
        for task in cases:
            rows.append(execute(task, generator, public_observer, private_observer, bound, binary, development, output))
            if len(rows) % 64 == 0:
                print(f"actual native admission episodes completed: {len(rows)}/1024", flush=True)
    write(output / "ROWS.json", rows)
    result = summarize(rows)
    result.update(actual_native_episodes=len(rows), actual_original_kernel_executions=sum(r["actual_original_kernel_executions"] for r in rows),
        actual_cold_restores=len(rows), actual_neural_generation_calls=sum(1 + r["actual_correction"] for r in rows),
        actual_candidate_media_files=sum(2 + 2 * r["actual_correction"] for r in rows),
        actual_final_confirmation_media_files=2 * sum(r["commit"] for r in rows),
        all_future_numerical_states_admissions_and_refusals_match=all(r["future_state_matches"] for r in rows),
        actual_neural_refusals=sum(r["native_refused"] for r in rows),
        total_python_cpu_seconds=sum(r["python_cpu_ns"] for r in rows) / 1e9,
        total_native_child_cpu_seconds=sum(r["native_child_user_cpu_seconds"] + r["native_child_system_cpu_seconds"] for r in rows),
        total_execution_wall_seconds=sum(r["wall_ns"] for r in rows) / 1e9,
        total_external_scoring_cpu_seconds=sum(r["private_score_python_cpu_ns"] for r in rows) / 1e9,
        mean_net_utility=float(np.mean([r["total_net_utility"] for r in rows])),
        mean_predicted_total_moment=float(np.mean([r["predicted_total_policy_moment"] for r in rows])),
        mean_actual_total_moment=float(np.mean([r["actual_total_policy_moment"] for r in rows])),
        rows_sha256=sha(output / "ROWS.json"), seal_sha256=sha(output / "QUALIFICATION_SEAL.json"),
        calibration_fit_metrics_not_heldout_qualification=False,
        all_candidate_labels_scored_including_abstentions=True, one_fixed_cohort_no_refit=True)
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "calibration", "allocation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.calibration, args.allocation, args.output)
