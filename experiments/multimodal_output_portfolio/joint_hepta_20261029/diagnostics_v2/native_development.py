"""Actual native-owner execution of fixed-order v2 development checkpoints.

This engineering probe reuses development sources. It is neither confirmation
nor an independent model-quality replication. The planner-versus-ordinary
comparison changes policy as well as operator; it cannot isolate Hepta.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import time

import torch

from experiments.multimodal_output_portfolio.joint_hepta_20261029.checkpoint import load_checkpoint
from experiments.multimodal_output_portfolio.joint_hepta_20261029.contract import JointGenerationProfile
from experiments.multimodal_output_portfolio.joint_hepta_20261029.deployment import (
    _native_evidence, load_candidate,
)
from experiments.multimodal_output_portfolio.joint_hepta_20261029.mechanism_data import batch
from experiments.multimodal_output_portfolio.joint_hepta_20261029.model import tensor_digest
from experiments.multimodal_output_portfolio.joint_hepta_20261029.native_bridge import NativeGuard
from experiments.multimodal_output_portfolio.joint_hepta_20261029.runtime import TARIFF, cpu_seconds, make_profile
from experiments.multimodal_output_portfolio.joint_hepta_20261029.train import evaluate, paired_comparison, write


HERE = Path(__file__).resolve().parents[1]
NAMESPACE = "controller-v2-development"
SPECIFICATIONS = (
    ("teacher", "hepta_dynamic_risk/MODEL.pt", "hepta_dynamic_risk", "planner"),
    ("student", "distillation/STUDENT.pt", "distilled", "greedy"),
    ("ordinary", "ordinary_dynamic_risk/MODEL.pt", "ordinary_dynamic_risk", "dynamic"),
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registered_study(study):
    """Validate the full first registered configuration and its frozen source."""
    study = Path(study).resolve()
    if study.is_file():
        study = study.parent
    if not (study / "RESULTS.json").is_file() and (study / "run" / "RESULTS.json").is_file():
        study = study / "run"
    result = json.loads((study / "RESULTS.json").read_text())
    protocol = json.loads((study / "EXECUTED_PROTOCOL.json").read_text())
    if (result.get("schema") != "hepta.joint-generation.controller-v2.development.v1"
            or result.get("stage") != "development" or result.get("smoke") is not False
            or result.get("seed") != 17 or result.get("width") != 32
            or result.get("confirmation_sources_consumed") != 0):
        raise ValueError("Require the full first registered seed17/width32 v2 development study")
    if (result.get("protocol_sha256") != sha(HERE / "controller_v2_protocol.json")
            or protocol != json.loads((HERE / "controller_v2_protocol.json").read_text())
            or protocol.get("development_namespace") != NAMESPACE
            or set(result["arms"]) != set(protocol["arms"])):
        raise ValueError("Development study protocol or full arm panel differs from registration")
    for mode in ("dual", "ordinary"):
        pretraining = result["pretraining"][mode]
        if (pretraining.get("updates") != protocol["pretraining_updates"]
                or len(pretraining.get("loss_history", [])) != protocol["pretraining_updates"]):
            raise ValueError("Registered core pretraining is incomplete")
    for arm in protocol["arms"]:
        training, evaluation = result["arms"][arm]["training"], result["arms"][arm]["evaluation"]
        expected = protocol["joint_updates"] * protocol["joint_batch"]
        if (training.get("actual_episodes") != expected or len(training.get("updates", [])) != protocol["joint_updates"]
                or training.get("final_parameters_sha256") != result["arms"][arm]["checkpoint"]["model_sha256"]
                or evaluation.get("actual_draws") != protocol["development_sources"] * protocol["evaluation_draws_per_source"]
                or len(evaluation.get("rows", [])) != evaluation.get("actual_draws")
                or {(r["source"], r["draw"]) for r in evaluation["rows"]} !=
                   {(source, draw) for source in range(protocol["development_sources"])
                    for draw in range(protocol["evaluation_draws_per_source"])}):
            raise ValueError("A registered arm is incomplete or its final model identity disagrees")
    distilled = result["distillation"]
    if (distilled.get("actual_training_episodes") != protocol["distillation_rounds"] * protocol["distillation_sources_per_round"]
            or len(distilled.get("rounds", [])) != protocol["distillation_rounds"]
            or distilled.get("generator_and_critics_unchanged") is not True):
        raise ValueError("Registered DAgger training is incomplete")
    source_path, process_path = study.parent / "SOURCE_RECEIPT.json", study.parent / "PROCESS_RECEIPT.json"
    source, process = json.loads(source_path.read_text()), json.loads(process_path.read_text())
    if (source.get("source_bytes_unchanged") is not True or source.get("before") != source.get("after")
            or process.get("exit_code") != 0 or process.get("timed_out") is not False
            or process.get("child_reaped") is not True):
        raise ValueError("Source/process receipt does not establish a completed frozen development run")
    snapshot = source["before"]
    if not re.fullmatch(r"[0-9a-f]{40}", snapshot.get("commit", "")):
        raise ValueError("Source receipt lacks its original commit identity")
    canonical = json.dumps(snapshot["files"], sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != snapshot.get("sha256"):
        raise ValueError("Source snapshot digest differs from its file manifest")
    prefix = "experiments/multimodal_output_portfolio/joint_hepta_20261029/"
    for name, expected in result["source_sha256"].items():
        if (Path(name).name != name or sha(HERE / name) != expected
                or snapshot["files"].get(prefix + name) != expected):
            raise ValueError("Training results/source receipt/current executable bytes disagree")
    profile = JointGenerationProfile.from_dict(json.loads((study / "PROFILE.json").read_text()))
    if profile.digest != result["profile_sha256"] or profile.digest != make_profile().digest:
        raise ValueError("Native diagnostic must execute the exact v2 generation profile")
    return study, result, protocol, profile, source, process


def inspect_termination(directory, evaluation, profile, model_sha):
    """Inspect acknowledged STOP, all child exits, and the actual tensor restore."""
    rows = []
    for item in evaluation["rows"]:
        folder = Path(directory) / f"source-{item['source']:03d}-draw-{item['draw']}"
        record = json.loads((folder / "TRAJECTORY.json").read_text())
        native = record.get("native_receipt") or {}
        final, children = native.get("final") or {}, native.get("native_process_cpu", [])
        recoveries = native.get("recoveries", [])
        stopped = (bool(record.get("actions")) and record["actions"][-1]["action"] == "stop"
                   and final.get("action") == "stop" and final.get("aborted") is False
                   and bool(final.get("native_stop_tick")) and bool(final.get("native_closed_status")))
        reaped = (native.get("native_process_reaped") is True and len(children) == len(recoveries) + 1
                  and len({c["pid"] for c in children}) == len(children)
                  and all(c.get("returncode") == 0 and not c.get("termination_signals") for c in children))
        restored = None
        if item["source"] == 0 and item["draw"] == 0:
            public, _ = batch([0], NAMESPACE)
            loaded, state, _, metadata = load_checkpoint(folder / "TENSOR_CONTINUATION.pt", profile=profile, public=public)
            checkpoint = metadata["checkpoint_identities"]
            restores = record.get("tensor_checkpoint_restores", [])
            restored = (len(restores) == 1 and restores[0].get("restored_in_this_process") is True
                and checkpoint["model_sha256"] == model_sha
                and checkpoint["payload_sha256"] == restores[0]["payload_sha256"]
                and tensor_digest(loaded.state_dict()) == model_sha and state.steps == 1 and not state.stopped
                and tensor_digest(state.tensors()) == record["actions"][0]["after_sha256"]
                and record["actions"][1].get("tensor_checkpoint_sha256") == checkpoint["payload_sha256"]
                and len(recoveries) == 1 and recoveries[0].get("new_os_process") is True
                and recoveries[0].get("same_native_state") is True
                and recoveries[0].get("before") == recoveries[0].get("after"))
        rows.append({"source": item["source"], "draw": item["draw"], "acknowledged_normal_stop": bool(stopped),
                     "all_owned_child_processes_reaped_normally": bool(reaped),
                     "first_episode_checkpoint_independently_loaded_and_bound": restored})
    return {"rows": rows, "all_stops_acknowledged": all(r["acknowledged_normal_stop"] for r in rows),
        "all_processes_reaped_normally": all(r["all_owned_child_processes_reaped_normally"] for r in rows),
        "first_checkpoint_revalidated": any(r["first_episode_checkpoint_independently_loaded_and_bound"] is True for r in rows)}


def run(study, binary, output):
    study, original, protocol, profile, source, process = registered_study(study)
    binary, output = Path(binary).resolve(), Path(output).resolve()
    if output == study or study in output.parents or study.parent == output or study.parent in output.parents:
        raise ValueError("Native outputs must not modify the downloaded source study")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    begun, cpu = time.perf_counter(), cpu_seconds()
    inputs = [study / n for n in ("RESULTS.json", "PROFILE.json", "EXECUTED_PROTOCOL.json")]
    inputs += [study.parent / n for n in ("SOURCE_RECEIPT.json", "PROCESS_RECEIPT.json")]
    for _, relative, _, _ in SPECIFICATIONS:
        inputs += [study / relative, (study / relative).with_suffix(".pt.manifest.json")]
    before = {str(p.relative_to(study.parent)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in inputs}
    result = {"schema": "hepta.joint-generation.native-development-v2.v1",
        "study_results_sha256": sha(study / "RESULTS.json"), "source_receipt": source,
        "study_process_receipt": process, "input_files_before": before,
        "input_snapshot_scope": "all consumed study metadata and three candidate checkpoint/manifest pairs",
        "native_binary_sha256": sha(binary), "profile_sha256": profile.digest,
        "driver_sha256": sha(Path(__file__)), "selection": "seed17/width32 first registered configuration, not highest score",
        "new_episodes": True, "original_quality_draws_independent": False,
        "evaluation_protocol": {"source_namespace": NAMESPACE, "sources": list(range(8)), "draws_per_source": 1,
            "seed": 200017, "first_episode_reopen_and_tensor_restore_at_event": 0,
            "same_inputs_and_rng_as_development_subset": True, "tariff": TARIFF},
        "runtime": {"python": platform.python_version(), "torch": str(torch.__version__), "threads": 2},
        "arms": {}, "candidates": {}, "loading": {}, "comparisons": {},
        "research_effect_qualified": False, "semantic_qualification": False, "deployment_promoted": False,
        "native_readout_selects_generator_actions": False, "trained_tensor_model_executes_inside_native_port": False,
        "comparison_limitation": "Teacher planner versus ordinary dynamic changes controller as well as operator; these are reused development sources, not independent quality replications"}
    write(output / "PROFILE.json", profile.to_dict())
    models = {}
    for name, relative, arm, strategy in SPECIFICATIONS:
        expected = original["distillation"]["checkpoint"] if arm == "distilled" else original["arms"][arm]["checkpoint"]
        start, start_cpu = time.perf_counter(), cpu_seconds()
        model, lineage = load_candidate(study / relative, expected_arm=arm, expected_model_sha256=expected["model_sha256"])
        if (lineage["manifest"] != expected or lineage["old_metadata"].get("stage") != "development"
                or lineage["old_metadata"].get("protocol_sha256") != original["protocol_sha256"]
                or lineage["old_metadata"].get("training_source_sha256") != original["source_sha256"]):
            raise ValueError("Candidate identity/metadata differs from its v2 training result")
        models[name] = model
        result["candidates"][name] = {"lineage": lineage, "strategy": strategy, "arm": arm}
        result["loading"][name] = {"cpu_seconds": cpu_seconds() - start_cpu, "wall_seconds": time.perf_counter() - start}
    if any(not torch.equal(value, models["student"].state_dict()[name]) for name, value in models["teacher"].state_dict().items()
           if not name.startswith("actor.")):
        raise ValueError("Student changed frozen generator or critics")
    result["student_generator_and_critics_equal_teacher"] = True

    def factory(model_sha, profile_sha, directory):
        return NativeGuard(binary=binary, directory=directory, case="joint.v2.development",
            model_sha256=model_sha, profile_sha256=profile_sha,
            allowed_actions=("shared", "image", "audio", "video", "text", "verify", "delivery", "stop"))

    for name, _, _, strategy in SPECIFICATIONS:
        evaluation = evaluate(models[name], output / name, profile, 200017, sources=8, draws=1,
                              strategy=strategy, split=NAMESPACE, native_factory=factory)
        model_sha = result["candidates"][name]["lineage"]["manifest"]["model_sha256"]
        native = _native_evidence(output / name, evaluation, model_sha, profile.digest, result["native_binary_sha256"])
        termination = inspect_termination(output / name, evaluation, profile, model_sha)
        result["arms"][name] = {"evaluation": evaluation, "native": native, "termination": termination}
        write(output / "RESULTS.partial.json", result)
    for left, right in (("student", "teacher"), ("teacher", "ordinary"), ("student", "ordinary")):
        result["comparisons"][left + "_minus_" + right] = paired_comparison(
            result["arms"][left]["evaluation"], result["arms"][right]["evaluation"], 200017, replicates=1000)
    result["input_files_after"] = {str(p.relative_to(study.parent)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in inputs}
    result["consumed_study_files_unchanged"] = before == result["input_files_after"]
    result["native_execution_closed_loop"] = all(
        a["native"]["closed_episode_count"] == 8 and a["native"]["first_episode_reopen_and_tensor_restore_observed"]
        and a["termination"]["all_stops_acknowledged"] and a["termination"]["all_processes_reaped_normally"]
        and a["termination"]["first_checkpoint_revalidated"] for a in result["arms"].values())
    result["total_cost"] = {"cpu_seconds": cpu_seconds() - cpu, "wall_seconds": time.perf_counter() - begun,
        "scope": "candidate loading through owner execution and independent output/checkpoint audit; interpreter startup/import excluded here"}
    write(output / "RESULTS.json", result)
    summary = {k: v for k, v in result.items() if k not in ("arms", "candidates", "source_receipt", "study_process_receipt", "input_files_before", "input_files_after")}
    summary["arms"] = {name: {"evaluation": {k: v for k, v in a["evaluation"].items() if k != "rows"},
        "native": {k: v for k, v in a["native"].items() if k != "episodes"},
        "termination": {k: v for k, v in a["termination"].items() if k != "rows"}} for name, a in result["arms"].items()}
    write(output / "SUMMARY.json", summary)
    print("NATIVE_V2_JSON=" + json.dumps(summary, sort_keys=True), flush=True)
    if not result["native_execution_closed_loop"] or not result["consumed_study_files_unchanged"]:
        raise RuntimeError("Actual native engineering closure failed; observed results are retained")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.study, args.binary, args.output)
