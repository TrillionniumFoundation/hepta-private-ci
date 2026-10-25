"""Additive, explicitly reused-source access; original repair guards stay intact."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WORK = ROOT.parent
REPAIR = HERE.parent / "training_repair"
NATIVE = HERE.parent / "native"
ASSIGNMENT = HERE / "REUSE_ASSIGNMENT-v2.json"
TIMELINE = HERE / "TIMELINE-v2.json"
ROLE = "repair_test"
ORIGIN_ROLE = "unallocated_test"
STUDY_ROLE = "native_candidate_reuse"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def pin(path):
    return {"path": str(Path(path).resolve()), "sha256": sha(path)}


def durable_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_prior_execution(spec, result, access, protocol_sha):
    """Validate completed metadata only; prior repair metric values are not labels."""
    expected = {(row["seed"], row["arm"]): row["sha256"] for row in spec["models"]}
    actual = [(row["seed"], row["arm"]) for row in result["models"]]
    if (len(expected) != 20 or len(actual) != 20 or set(actual) != set(expected)
            or result["status"] != "completed" or result["protocol_sha256"] != protocol_sha
            or result["outcomes_used_for_selection"] is not False
            or result["source_identity"] != spec["source_identity"]
            or access["protocol_sha256"] != protocol_sha
            or access["source_identity"] != spec["source_identity"]
            or access["role_assignment_sha256"] != spec["role_assignment_sha256"]
            or (access["role"], access["origin_role"], access["start"], access["count"])
            != (ROLE, ORIGIN_ROLE, 0, 1000)):
        raise ValueError("Prior assigned-source execution is incomplete, changed or relabeled")
    for row in result["models"]:
        if (row["sha256"] != expected[(row["seed"], row["arm"])]
                or row["rows"] != 16000 or row["shape_per_metric"] != [1000, 8, 2]):
            raise ValueError("Prior completed model/source census changed")


def original_state():
    from ..training_repair.assigned_source import verify_assignment as verify_original_assignment
    from ..training_repair.evaluate import verify as verify_original_twenty_models

    original_assignment = verify_original_assignment()
    path = REPAIR / "EVALUATION_PROTOCOL.json"
    spec = read(path)
    # This invokes the original model, training, source and role guards unchanged.
    verify_original_twenty_models(spec)
    result_path = Path(spec["output"]) / "result.json"
    access_path = Path(spec["output"]) / "access-registration.json"
    validate_prior_execution(spec, read(result_path), read(access_path), sha(path))
    dependencies = {"original_assignment": pin(REPAIR / "ROLE_ASSIGNMENT.json"),
        "source_allocation": pin(REPAIR / "SOURCE_ALLOCATION.json"),
        "original_evaluation_protocol": pin(path), "completed_execution": pin(result_path),
        "original_access_registration": pin(access_path)}
    return original_assignment, dependencies


def make_timeline():
    run = WORK / "abc4-native-runs/future-native-001"
    candidates_path = run / "live-proposal-candidates/candidates.json"
    pending_path = run / "live-proposal-pending/candidates.json"
    evaluation_path = run / "live-proposal-evaluation.json"
    consume_path = run / "live-evaluation.process.registration.json"
    consume_receipt = run / "live-evaluation.process.json"
    access_path = WORK / "abc4-repair-runs/evaluation-001/access-registration.json"
    native_registration = WORK / "abc4-native-runs/future-native-001.process.registration.json"
    native_receipt = WORK / "abc4-native-runs/future-native-001.process.json"
    analysis_registration = WORK / "abc4-repair-runs/analysis-001.process.registration.json"
    candidates, historical, consumption, prior_access = map(read,
        (candidates_path, evaluation_path, consume_path, access_path))
    command = consumption["command"]
    historical_data = command[command.index("--data") + 1]
    completion_times = {"historical_evaluation": evaluation_path.stat().st_mtime_ns,
        "candidate_evaluation_receipt": consume_receipt.stat().st_mtime_ns,
        "native_completion_receipt": native_receipt.stat().st_mtime_ns}
    completion_time = max(completion_times.values())
    if (sha(candidates_path) != sha(pending_path)
            or historical["candidates_file_sha256"] != sha(candidates_path)
            or historical["weights_sha256"] != candidates["baseline_weights_sha256"]
            or historical["generator_digest"] != candidates["generator_digest"]
            or historical_data != str(WORK / "abc4-native-runs/development-001")
            or read(consume_receipt)["registration_sha256"] != sha(consume_path)
            or read(consume_receipt)["exit_code"] != 0
            or read(native_receipt)["registration_sha256"] != sha(native_registration)
            or read(native_receipt)["exit_code"] != 0
            or candidates["context"]["sequence"] != 802
            or not 1568 <= candidates["context"]["pair"] < 3000
            or not consumption["unix_ns"] <= completion_time < prior_access["unix_ns"]):
        raise ValueError("Frozen candidate provenance or pre-repair chronology differs")
    proof = {"candidates": pin(candidates_path), "pending_candidates": pin(pending_path),
        "historical_evaluation": pin(evaluation_path), "candidate_consumption_registration": pin(consume_path),
        "candidate_evaluation_receipt": pin(consume_receipt), "native_completion_receipt": pin(native_receipt),
        "native_start_registration": pin(native_registration),
        "repair_first_access_registration": pin(access_path),
        "repair_analysis_registration": pin(analysis_registration),
        "frozen_proposal_source": pin(NATIVE / "proposal.rs"),
        "frozen_hook_source": pin(NATIVE / "proposal_hook.rs"),
        "frozen_geometry_source": pin(NATIVE / "parameter_geometry.rs"),
        "frozen_historical_evaluator_source": pin(NATIVE / "future_candidate.py")}
    return {"schema": "hepta.abc4.fixed-candidate-reuse-timeline.v1", "proof_inputs": proof,
        "candidate_file_sha256": sha(candidates_path),
        "candidate_ids": [row["id"] for row in candidates["candidates"]],
        "baseline_weights_sha256": candidates["baseline_weights_sha256"],
        "generator_digest": candidates["generator_digest"],
        "candidate_anchor": candidates["context"]["anchor"], "candidate_sequence": 802,
        "candidate_context_source_role": "test", "candidate_context_pair": candidates["context"]["pair"],
        "candidate_evaluation_registered_unix_ns": consumption["unix_ns"],
        "candidate_artifact_existed_before_evaluation_registration_by_frozen_hook_order": True,
        "completed_artifact_local_filesystem_mtime_unix_ns": completion_times,
        "repair_first_access_unix_ns": prior_access["unix_ns"],
        "repair_analysis_start_unix_ns": read(analysis_registration)["unix_ns"],
        "candidate_precedes_any_formal_repair_access": True,
        "registration_lead_before_repair_access_ns": prior_access["unix_ns"] - consumption["unix_ns"],
        "completed_artifact_mtime_lead_before_repair_access_ns": prior_access["unix_ns"] - completion_time,
        "historical_evaluator_input": historical_data,
        "call_isolation": "Pinned proposal/hook reads original native test context and frozen weights; historical evaluator reads development only. No repair execution, metric, target or candidate-selection input is passed.",
        "clock_scope": "Local process registration written and closed, completed-output/receipt filesystem mtimes, immutable artifact bindings and frozen call order. Registration time is not a consumption-completion upper bound; original registration JSON was not fsynced. These are not externally authenticated timestamps.",
        "prepublication_correction": {"supersedes_timeline_sha256": sha(HERE / "TIMELINE.json"),
            "reason": "Correct durability and registration-versus-consumption wording before protocol publication or new branch access; add completed receipts and their observed local mtimes. Old registration was write-and-close; new reuse access has explicit file and directory fsync. Candidate, source and statistics unchanged."},
        "prior_repair_results_now_observed": True,
        "new_project_source_or_independent_replication_claimed": False}


def register_assignment():
    HERE.mkdir(parents=True, exist_ok=True)
    if ASSIGNMENT.exists() or TIMELINE.exists():
        raise ValueError("Reuse source registration already exists")
    original, dependencies = original_state()
    durable_json(TIMELINE, make_timeline())
    record = {"schema": "hepta.abc4.explicit-source-reuse-assignment.v1",
        "registered_unix_ns": time.time_ns(), "source_identity": original["allocation"],
        "origin_manifest_sha256": original["origin_manifest_sha256"],
        "source_role": ROLE, "origin_role": ORIGIN_ROLE, "study_role": STUDY_ROLE,
        "pair_start": 0, "pair_count": 1000, "prior_dependencies": dependencies,
        "timeline_sha256": sha(TIMELINE), "loader_sha256": sha(__file__),
        "supersedes_prepublication_assignment_sha256": sha(HERE / "REUSE_ASSIGNMENT.json"),
        "purpose": "Prospective new future branches for all fixed seq802 predictor candidates on an explicitly reused complete source cohort.",
        "authorization_scope": "User-authorized next research round; coordinator explicitly authorizes separate additive reuse registration before new branch generation.",
        "original_guards_modified": False, "requires_original_complete_twenty_model_guard": True,
        "requires_new_reuse_protocol_and_access_registration": True,
        "source_previously_observed": True, "previous_study": "training_repair",
        "unique_new_source_pairs": 0, "source_pairs_in_this_comparison": 1000,
        "candidate_construction_source_overlap": 0,
        "new_future_outcomes_opened": False, "prior_metrics_used_as_future_labels": False,
        "statistical_scope": "Candidates fixed before prior study access; sources reused across studies. New branch outcomes are prospective, not a new project-wide holdout or global error-control certificate."}
    durable_json(ASSIGNMENT, record)
    verify_assignment()
    print(json.dumps({"reuse_assignment_sha256": sha(ASSIGNMENT), "timeline_sha256": sha(TIMELINE)}), flush=True)


def verify_assignment():
    record = read(ASSIGNMENT)
    original, dependencies = original_state()
    if (record["schema"] != "hepta.abc4.explicit-source-reuse-assignment.v1"
            or record["loader_sha256"] != sha(__file__) or record["timeline_sha256"] != sha(TIMELINE)
            or record["prior_dependencies"] != dependencies
            or record["source_identity"] != original["allocation"]
            or record["origin_manifest_sha256"] != original["origin_manifest_sha256"]
            or (record["source_role"], record["origin_role"], record["study_role"], record["pair_start"], record["pair_count"])
            != (ROLE, ORIGIN_ROLE, STUDY_ROLE, 0, 1000)
            or record["source_previously_observed"] is not True
            or record["unique_new_source_pairs"] != 0):
        raise ValueError("Explicit reuse source assignment changed")
    if read(TIMELINE) != make_timeline():
        raise ValueError("Candidate/source chronology or call isolation evidence changed")
    return record


def access_contract(spec, protocol_path, assignment):
    fields = ("source_role", "origin_role", "study_role", "pair_start", "pair_count", "source_identity")
    if (any(spec[key] != assignment[key] for key in fields)
            or spec["reuse_assignment_sha256"] != sha(ASSIGNMENT)
            or spec["timeline_sha256"] != sha(TIMELINE)):
        raise ValueError("New protocol does not bind the full explicitly reused cohort")
    return {"schema": "hepta.abc4.native-candidate-reuse-access.v1",
        **{key: spec[key] for key in fields}, "protocol_sha256": sha(protocol_path),
        "reuse_assignment_sha256": sha(ASSIGNMENT), "timeline_sha256": sha(TIMELINE),
        "original_assignment_sha256": assignment["prior_dependencies"]["original_assignment"]["sha256"],
        "prior_completed_execution_sha256": assignment["prior_dependencies"]["completed_execution"]["sha256"],
        "source_previously_observed": True, "unique_new_source_pairs": 0,
        "prior_metrics_used_as_future_labels": False}


def register_access(protocol_path, output):
    from .protocol import verify

    spec = verify(Path(protocol_path))
    assignment = verify_assignment()
    output = Path(output)
    if output.resolve() != Path(spec["output"]).resolve():
        raise ValueError("Reuse output directory differs from the frozen protocol")
    access = {**access_contract(spec, protocol_path, assignment), "opened_unix_ns": time.time_ns()}
    output.mkdir(parents=True, exist_ok=False)
    durable_json(output / "access-registration.json", access)
    return access


def verify_access(protocol_path, output):
    from .protocol import verify

    spec = verify(Path(protocol_path))
    assignment = verify_assignment()
    if Path(output).resolve() != Path(spec["output"]).resolve():
        raise ValueError("Reuse output directory differs from the frozen protocol")
    access = read(Path(output) / "access-registration.json")
    expected = access_contract(spec, protocol_path, assignment)
    if (set(access) != set(expected) | {"opened_unix_ns"}
            or any(access[key] != value for key, value in expected.items())
            or type(access["opened_unix_ns"]) is not int
            or access["opened_unix_ns"] <= assignment["registered_unix_ns"]):
        raise ValueError("Missing, stale or relabeled independent reuse access registration")
    return access


def materialize(cache, protocol_path, output):
    """Require new reuse access before reading original source pixels or labels."""
    access = verify_access(protocol_path, output)
    assignment = verify_assignment()
    from ...abc_next.settings import MANIFEST
    from ...v6.data import SourceCorpus, SourceSplit
    from ...v7.sources import _read_cache, build_manifest, digest, read_manifest
    import torch

    if sha(MANIFEST) != assignment["origin_manifest_sha256"]:
        raise ValueError("Original source manifest identity changed")
    original = read_manifest(MANIFEST)
    if original != build_manifest(cache):
        raise ValueError("Original manifest differs from validated archive reconstruction")
    registered = original["roles"][ORIGIN_ROLE]
    ids = tuple(registered["source_ids"])
    identity = assignment["source_identity"]
    pixels_sha = tuple(value.rsplit(":", 1)[1] for value in ids)
    if (len(ids) != 2000 or len(set(ids)) != 2000 or len(set(pixels_sha)) != 2000
            or hashlib.sha256("\n".join(ids).encode()).hexdigest() != identity["ordered_source_ids_sha256"]
            or hashlib.sha256("\n".join(sorted(pixels_sha)).encode()).hexdigest() != identity["sorted_pixel_hashes_sha256"]):
        raise ValueError("Reused source identity or full no-replacement census differs")
    images, labels, hashes = _read_cache(cache)[registered["official_partition"]]
    indices = [int(value.split(":")[2]) for value in ids]
    if any(value.rsplit(":", 1)[1] != hashes[index] for value, index in zip(ids, indices)):
        raise ValueError("Actual reused source pixels differ from their registered identity")
    pixels = torch.frombuffer(bytearray(images), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    values = torch.tensor(list(labels), dtype=torch.long)
    split = SourceSplit(pixels[indices].clone(), values[indices].clone(), ids, pixels_sha)
    derived = {"schema": "hepta.abc4.reused-source-corpus.v1", "roles": {ROLE: registered},
        "origin_role": ORIGIN_ROLE, "study_role": STUDY_ROLE,
        "origin_manifest_sha256": sha(MANIFEST), "reuse_assignment_sha256": sha(ASSIGNMENT),
        "access_registration_sha256": sha(Path(output) / "access-registration.json"),
        "source_previously_observed": access["source_previously_observed"]}
    derived["manifest_sha256"] = digest(derived)
    return SourceCorpus({ROLE: split}, derived)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze-sources",))
    parser.parse_args()
    register_assignment()
