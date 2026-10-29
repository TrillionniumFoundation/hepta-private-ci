"""Deploy full-study candidate weights in new, actually native-gated episodes.

This is a weights migration, never continuation of a downloaded episode. Exact
model/core/codec source identities are required; old execution/profile lineage
is retained beside the new execution profile. Hashes provide integrity, not
signatures. A successful native execution does not qualify an empirical gain.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import torch

from .checkpoint import MAX_BYTES, NAMED_RNG_LAW, NAMED_SCHEMA, SCHEMA as CHECKPOINT_SCHEMA
from .checkpoint import _named_states, _safe, _sources
from .contract import JointGenerationProfile, digest
from .model import JointGenerator, tensor_digest
from .native_bridge import NativeGuard
from .runtime import HORIZON, INITIAL_BUDGET, TARIFF, cpu_seconds, make_profile
from .train import evaluate, paired_comparison, write


SCHEMA = "hepta.joint-generation.full-checkpoint-native-deployment.v1"
SOURCE_RUN = 40834365977
SOURCE_SHA = "5a4a763c0001010c172bcef057e137adc636b477"
SOURCE_ARTIFACT = "joint-study-17-32-" + SOURCE_SHA
REQUIRED_SOURCES = tuple("joint_hepta_20261029/" + name
                         for name in ("model.py", "hepta_core.py", "media.py"))
EPISODE_FILES = {"text": "text.txt", "image": "image.png", "audio": "audio.wav", "video": "video.gif"}


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_candidate(path, *, expected_model_sha256=None, expected_arm=None):
    """Return frozen model and lineage, discarding old state, clocks and RNGs.

The external expected model digest binds the candidate to the study's training
result. The manifest also binds every old tensor and metadata field, even though
the old episode's persistent state is not restored.
    """
    path = Path(path)
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    if not path.is_file() or not manifest_path.is_file():
        raise ValueError("Candidate file and manifest are both required")
    manifest = json.loads(manifest_path.read_text())
    if (path.stat().st_size > MAX_BYTES or path.stat().st_size != manifest.get("file_bytes")
            or _sha(path) != manifest.get("file_sha256")):
        raise ValueError("Candidate bytes differ from the checkpoint manifest")
    payload = _safe(torch.load(path, map_location="cpu", weights_only=True))
    schema = payload.get("schema")
    if schema not in (CHECKPOINT_SCHEMA, NAMED_SCHEMA):
        raise ValueError("Unsupported candidate checkpoint schema")
    old_profile = JointGenerationProfile.from_dict(payload["profile"])
    model_sha = tensor_digest(payload["model"])
    metadata = payload["metadata"]
    checks = {"schema": schema, "payload_sha256": tensor_digest(payload),
              "model_sha256": model_sha, "state_sha256": tensor_digest(payload["state"]),
              "profile_sha256": old_profile.digest, "input_sha256": metadata["input_sha256"],
              "config_sha256": digest(payload["config"]), "generation_sha256": tensor_digest(metadata),
              "rng_sha256": tensor_digest({"episode": payload["rng"], "global": payload["global_rng"]})}
    if schema == NAMED_SCHEMA:
        named = _named_states(payload.get("named_rng_states"))
        if payload.get("named_rng_law") != NAMED_RNG_LAW or not torch.equal(payload["rng"], named["actor"]):
            raise ValueError("Candidate named RNG identities disagree")
        checks["named_rng_sha256"] = tensor_digest(named)
    elif "named_rng_states" in payload or "named_rng_law" in payload:
        raise ValueError("Candidate RNG fields contradict its checkpoint schema")
    if any(manifest.get(key) != value for key, value in checks.items()):
        raise ValueError("Candidate tensor/model/profile identities disagree")
    if (metadata.get("schema") != "hepta.joint-generation.episode-anchor.v1"
            or metadata.get("parameter_snapshot_sha256") != model_sha
            or metadata.get("profile_sha256") != old_profile.digest):
        raise ValueError("Candidate disagrees with its original parameter/profile anchor")
    if expected_model_sha256 is not None and expected_model_sha256 != model_sha:
        raise ValueError("Candidate model identity differs from the full-study training result")
    if expected_arm is not None and expected_arm != metadata.get("arm"):
        raise ValueError("Candidate training arm differs from the requested full-study arm")
    current_sources, old_sources = _sources(), payload["source_sha256"]
    if any(old_sources.get(name) != current_sources[name] for name in REQUIRED_SOURCES):
        raise ValueError("Candidate model/core/media source code differs from current implementation")
    config = payload["config"]
    if (set(config) != {"width", "depth", "mode", "boundary"}
            or type(config["width"]) is not int or not 1 <= config["width"] <= 512
            or type(config["depth"]) is not int or not 1 <= config["depth"] <= 16
            or config["mode"] not in ("dual", "single", "no_adaptation", "ordinary")
            or config["boundary"] not in ("direct", "fixed")
            or payload["dtype"] not in ("torch.float32", "torch.float64")):
        raise ValueError("Candidate configuration is outside the bounded registered model")
    # Constructing a candidate must not install the downloaded global RNG state.
    with torch.random.fork_rng(devices=[]):
        model = JointGenerator(**config).to(dtype=getattr(torch, payload["dtype"].split(".")[-1]))
    model.load_state_dict(payload["model"], strict=True)
    if tensor_digest(model.state_dict()) != model_sha:
        raise ValueError("Strict candidate loading changed model tensor identities or precision")
    model.eval().requires_grad_(False)
    lineage = {"operation": "candidate_weights_new_episode", "old_trajectory_restored": False,
               "old_rng_and_physical_clocks_restored": False, "manifest": manifest,
               "manifest_file_sha256": _sha(manifest_path), "config": config,
               "old_profile": payload["profile"], "old_metadata": metadata,
               "old_runtime": payload["runtime"], "old_source_sha256": old_sources,
               "current_source_sha256": current_sources,
               "required_exact_sources": list(REQUIRED_SOURCES),
               "source_changes_for_new_episode": {name: {"old": old_sources.get(name), "new": value}
                   for name, value in current_sources.items() if old_sources.get(name) != value}}
    return model, lineage


def _source_receipt(path):
    expected = {"run_id": SOURCE_RUN, "head_sha": SOURCE_SHA, "artifact_name": SOURCE_ARTIFACT}
    if path is None:
        return {"expected_origin": expected, "github_origin_verified_by_receipt": False,
                "basis": "local checkpoint/study integrity only; constants do not establish GitHub origin"}
    path = Path(path)
    receipt = json.loads(path.read_text())
    if (receipt.get("schema") != "hepta.joint-generation.deployment-source.v1"
            or any(receipt.get(key) != value for key, value in expected.items())
            or receipt.get("origin_verified_with_github_api") is not True
            or receipt.get("complete_registered_updates_verified") is not True):
        raise ValueError("Deployment source receipt does not bind the registered complete study")
    api_hashes = receipt.get("api_metadata_sha256", {})
    if not api_hashes or any(Path(name).name != name or _sha(path.parent / name) != value
                             for name, value in api_hashes.items()):
        raise ValueError("Source receipt API evidence is absent or changed")
    if _sha(path.parent / "STUDY_INPUT_MANIFEST.json") != receipt.get("input_file_manifest_sha256"):
        raise ValueError("Source receipt input-file manifest changed")
    return {"expected_origin": expected, "github_origin_verified_by_receipt": True,
            "basis": "workflow-verified GitHub API receipt and matching adjacent evidence; no new API request",
            "receipt_sha256": _sha(path), "receipt": receipt}


def _native_evidence(directory, evaluation, model_sha, profile_sha, binary_sha):
    evidence = []
    for row in evaluation["rows"]:
        episode = directory / f"source-{row['source']:03d}-draw-{row['draw']}"
        path = episode / "TRAJECTORY.json"
        record = json.loads(path.read_text())
        receipt = record.get("native_receipt") or {}
        identity = receipt.get("identity", {})
        if (record.get("parameter_snapshot_sha256") != model_sha or record.get("profile_sha256") != profile_sha
                or identity.get("generator_model_sha256") != model_sha
                or identity.get("ndu_profile_sha256") != profile_sha
                or identity.get("binary_sha256") != binary_sha):
            raise ValueError("Actual native trajectory model/profile/binary identities disagree")
        artifacts = dict(record["outcome"]["artifact_sha256"])
        files_valid = (set(artifacts) == set(EPISODE_FILES) and artifacts == dict(row["artifacts"])
                       and all(_sha(episode / "outputs" / EPISODE_FILES[name]) == value
                               for name, value in artifacts.items()))
        restores = sum(item.get("restored_in_this_process") is True
                       for item in record.get("tensor_checkpoint_restores", []))
        closed = (record.get("native_integration_executed") is True
                  and record.get("contract_validated") is True and record.get("failure") is None
                  and record["outcome"]["terminal_kind"] == "delivered" and files_valid
                  and receipt.get("finished") is True and receipt.get("native_process_reaped") is True
                  and receipt.get("native_tick_count", 0) > 0 and not receipt.get("failures"))
        evidence.append({"source": row["source"], "draw": row["draw"], "trajectory_sha256": _sha(path),
                         "closed_and_output_bytes_verified": bool(closed),
                         "native_ticks": receipt.get("native_tick_count", 0),
                         "native_recoveries": len(receipt.get("recoveries", [])),
                         "actual_tensor_restores": restores,
                         "native_owner_cpu_seconds": receipt.get("native_owner_cpu_seconds"),
                         "native_journal_bytes_written": receipt.get("native_journal_bytes_written", 0)})
    first = next(item for item in evidence if item["source"] == 0 and item["draw"] == 0)
    return {"episodes": evidence, "episode_count": len(evidence),
            "closed_episode_count": sum(item["closed_and_output_bytes_verified"] for item in evidence),
            "native_tick_count": sum(item["native_ticks"] for item in evidence),
            "native_recovery_count": sum(item["native_recoveries"] for item in evidence),
            "actual_tensor_restore_count": sum(item["actual_tensor_restores"] for item in evidence),
            "first_episode_reopen_and_tensor_restore_observed": first["native_recoveries"] > 0 and first["actual_tensor_restores"] > 0,
            "native_readout_selects_generator_action": False,
            "tensor_restore_scope": "same-process numerical restore and independent native-owner process reopen; no wall-clock restoration"}


def cost_accounting(training_seconds, loading, teacher, student):
    """Descriptive cost-only amortization; no quality or cross-host guarantee."""
    def priced(seconds):
        return TARIFF["cpu_second"] * seconds["cpu"] + TARIFF["wall_second"] * seconds["wall"]
    distillation = priced(training_seconds)
    loads = {name: {**seconds, "tariff_cost": priced(seconds)} for name, seconds in loading.items()}
    saving = teacher["mean_cost"] - student["mean_cost"]
    upfront = distillation + loads["student"]["tariff_cost"] - loads["teacher"]["tariff_cost"]
    return {"original_distillation_seconds": training_seconds, "distillation_tariff_cost": distillation,
            "model_loading": loads,
            "loading_scope": "checkpoint file/manifest/source verification, tensor construction and strict load; excludes Python startup/imports",
            "observed_teacher_minus_student_serving_cost": saving,
            "incremental_distillation_plus_load_cost": upfront,
            "cost_only_break_even_episodes": max(0, math.ceil(upfront / saving)) if saving > 0 else None,
            "break_even_basis": "positive observed serving cost saving" if saving > 0 else "nonpositive observed serving cost saving",
            "student_primary_ce_change": student["population_ce"] - teacher["population_ce"],
            "quality_noninferiority_established": False,
            "scope": "registered tariff units, measured source/deployment hosts; excludes candidate selection/common pretraining and uncertainty in extrapolation"}


def run(study, binary, output, *, source_receipt=None):
    study, binary, output = Path(study).resolve(), Path(binary).resolve(), Path(output).resolve()
    if output == study or study in output.parents:
        raise ValueError("Deployment evidence must not modify the downloaded study directory")
    original = json.loads((study / "RESULTS.json").read_text())
    if (original.get("schema") != "hepta.joint-generation.study.v1" or original.get("smoke") is not False
            or original.get("seed") != 17 or original.get("width") != 32):
        raise ValueError("Require the registered full seed17/width32 study, never smoke/partial weights")
    for arm in ("hepta_dynamic_risk", "ordinary_dynamic_mean"):
        training = original["arms"][arm]["training"]
        if training["actual_episodes"] != 512 or len(training["updates"]) != 64:
            raise ValueError("Full-study candidate has incomplete registered joint training")
    origin = _source_receipt(source_receipt)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), cpu_seconds()
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    profile, binary_sha = make_profile(), _sha(binary)
    result = {"schema": SCHEMA, "source": origin, "study_results_sha256": _sha(study / "RESULTS.json"),
              "new_episode": True, "old_trajectory_resumed": False, "profile_sha256": profile.digest,
              "original_profile_sha256": original["profile_sha256"], "native_binary_sha256": binary_sha,
              "evaluation_protocol": {"sources": 16, "draws": 2, "seed": 900017, "split": "test",
                  "initial_budget": INITIAL_BUDGET, "horizon": HORIZON, "gamma": profile.ndu.gamma,
                  "cost_tariff": TARIFF, "reopen_and_tensor_restore_at_event": 0,
                  "recovery_probe_scope": "first source/draw of each arm; measured overhead included",
                  "same_test_inputs_as_original_study": True, "new_semantic_qualification": False},
              "runtime": {"torch": str(torch.__version__), "python": platform.python_version(), "threads": 2},
              "candidates": {}, "arms": {}, "comparisons": {},
              "original_empirical_results": {"comparisons": original["comparisons"],
                  "distillation_ce_change": original["distillation"]["ce_change"],
                  "distillation_cost_change": original["distillation"]["cost_change"],
                  "research_effect_qualified": original.get("research_effect_qualified", False)},
              "research_effect_qualified": False, "natural_semantic_qualification": False,
              "global_optimality_claimed": False}
    write(output / "PROFILE.json", profile.to_dict())
    specifications = (("teacher", "hepta_dynamic_risk/MODEL.pt", "hepta_dynamic_risk", "planner"),
                      ("student", "distillation/STUDENT.pt", "distilled", "greedy"),
                      ("ordinary", "ordinary_dynamic_mean/MODEL.pt", "ordinary_dynamic_mean", "dynamic"))
    models, loading = {}, {}
    for name, relative, arm, strategy in specifications:
        wall0, cpu0 = time.perf_counter(), cpu_seconds()
        expected = original["arms"][arm]["training"]["final_parameters_sha256"] if arm != "distilled" else None
        model, lineage = load_candidate(study / relative, expected_model_sha256=expected, expected_arm=arm)
        loading[name] = {"wall": time.perf_counter()-wall0, "cpu": cpu_seconds()-cpu0}
        if (lineage["manifest"]["profile_sha256"] != original["profile_sha256"]
                or model.config != {"width": 32, "depth": 1, "mode": "ordinary" if name == "ordinary" else "dual", "boundary": "direct"}):
            raise ValueError("Candidate configuration or original profile differs from the registered study")
        models[name] = model
        result["candidates"][name] = {**lineage, "path_within_study": relative, "strategy": strategy}
    teacher_state, student_state = models["teacher"].state_dict(), models["student"].state_dict()
    if any(not torch.equal(value, student_state[name]) for name, value in teacher_state.items() if not name.startswith("actor.")):
        raise ValueError("Student changed generator/critic tensors outside its registered actor distillation")
    result["student_generator_and_critics_equal_teacher"] = True

    def factory(model_sha, profile_sha, directory):
        return NativeGuard(binary=binary, directory=directory, case="joint.generated",
            model_sha256=model_sha, profile_sha256=profile_sha,
            allowed_actions=("shared", "image", "audio", "video", "text", "verify", "delivery", "stop"))

    for name, _, _, strategy in specifications:
        evaluation = evaluate(models[name], output / name, profile, 900017, sources=16, draws=2,
                              strategy=strategy, split="test", native_factory=factory)
        native = _native_evidence(output / name, evaluation,
            result["candidates"][name]["manifest"]["model_sha256"], profile.digest, binary_sha)
        evaluation["negative_net_return_fraction"] = sum(row["return"] < 0 for row in evaluation["rows"]) / len(evaluation["rows"])
        result["arms"][name] = {"evaluation": evaluation, "native": native}
        write(output / "RESULTS.partial.json", result)
    for left, right in (("student", "teacher"), ("teacher", "ordinary"), ("student", "ordinary")):
        result["comparisons"][left + "_minus_" + right] = paired_comparison(
            result["arms"][left]["evaluation"], result["arms"][right]["evaluation"], 900017, replicates=1000)
    result["cost_accounting"] = cost_accounting(original["distillation"]["training_seconds"], loading,
        result["arms"]["teacher"]["evaluation"], result["arms"]["student"]["evaluation"])
    result["native_execution_closed_loop"] = all(
        item["native"]["closed_episode_count"] == 32
        and item["native"]["first_episode_reopen_and_tensor_restore_observed"] for item in result["arms"].values())
    result["total_wall_seconds"], result["total_cpu_seconds"] = time.perf_counter()-started, cpu_seconds()-cpu
    write(output / "RESULTS.json", result)
    summary = {key: result[key] for key in ("schema", "profile_sha256", "native_execution_closed_loop",
        "comparisons", "cost_accounting", "research_effect_qualified", "natural_semantic_qualification",
        "total_wall_seconds", "total_cpu_seconds")}
    summary["arms"] = {name: {"evaluation": {k: v for k, v in arm["evaluation"].items() if k != "rows"},
                              "native": {k: v for k, v in arm["native"].items() if k != "episodes"}}
                       for name, arm in result["arms"].items()}
    write(output / "SUMMARY.json", summary)
    print("RESULT_JSON=" + json.dumps(summary, sort_keys=True, allow_nan=False), flush=True)
    if not result["native_execution_closed_loop"]:
        raise RuntimeError("Deployment execution was incomplete; observed failures remain in RESULTS.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-receipt", type=Path)
    arguments = parser.parse_args()
    run(arguments.study, arguments.binary, arguments.output, source_receipt=arguments.source_receipt)
