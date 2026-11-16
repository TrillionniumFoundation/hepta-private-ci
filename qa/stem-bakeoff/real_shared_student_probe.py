"""Predeclared tiny shared-student update on reused real COCO/EG2 evidence.

No download, foundation-model update, production activation or blind-test claim.
The raw image/text student and the fixed teacher targets have independent paths.
"""

import argparse
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import PIL
import torch
from torch.nn import functional as F

from cell_evolution_snapshot import EvolutionError, WithdrawalViewV1, digest
from feature_shard import read_shard
from offline_shard_distill import SPLITS
from shared_coco_inputs import (BANK_SHA256, DATASET_SHA256, FEATURE_FILE_SHA256,
    RECIPE, ROLE_NAMES, canonical, control_cohorts, make_inputs, select_sources)
from shared_student_training import (MODEL_ID, TEACHER, TEACHER_INVENTORY, TEACHER_REVISION,
    load_shared_student, tensor_sha, train_shared_student)

SEEDS = (7, 17, 29)
ARMS = ("multimodal", "image_only", "text_only")
SCOPE = "coco-shared-tiny-research-v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    data = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(data)
    return sha(data)


def dependencies():
    directory = Path(__file__).resolve().parent
    pending, result = [Path(__file__).resolve()], {}
    while pending:
        path = pending.pop()
        if path.name in result:
            continue
        data = path.read_bytes()
        result[path.name] = sha(data)
        for node in ast.walk(ast.parse(data)):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                     [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                candidate = directory / (name.split(".")[0] + ".py")
                if candidate.is_file():
                    pending.append(candidate)
    return dict(sorted(result.items()))


class Withdrawals:
    def __init__(self):
        self.view = WithdrawalViewV1(SCOPE)

    def __call__(self):
        return self.view

    def revoke(self, source):
        self.view = replace(self.view, epoch=self.view.epoch + 1,
            revoked_source_digests=tuple(sorted(set(self.view.revoked_source_digests) | {source})))


def metrics(prediction, target):
    value = torch.from_numpy(prediction.copy())
    mse = (value - target).square().mean(-1)
    cosine = F.cosine_similarity(value, target, dim=-1, eps=1e-8)
    scores = F.normalize(value, dim=-1) @ F.normalize(target, dim=-1).T
    selected = scores.argmax(-1)
    correct = selected == torch.arange(len(target))
    return {"mse": float(mse.mean()), "cosine": float(cosine.mean()),
        "objective": float(mse.mean() + 0.1 * (1 - cosine.mean())),
        "within_role_target_retrieval_r1": float(correct.float().mean()),
        "per_source_mse": mse.tolist(), "per_source_cosine": cosine.tolist(),
        "retrieved_target_row": selected.tolist(), "retrieval_correct": correct.tolist()}


def rejection(function):
    try:
        function()
    except (ValueError, EvolutionError) as exc:
        return {"rejected": True, "type": type(exc).__name__, "reason": str(exc)}
    raise AssertionError("withdrawn shared-student artifact was accepted")


def run_probe(raw_root, bank_root, output):
    torch.set_num_threads(1)
    torch.set_default_dtype(torch.float32)
    torch.use_deterministic_algorithms(True)
    target = Path(output)
    target.mkdir(parents=False, exist_ok=False)
    selection = select_sources(raw_root)  # Source IDs only; no model or outcome.
    plan = {"schema": "hepta.real-shared-tiny-plan.v1", "model_id": MODEL_ID,
        "scope_id": SCOPE, "seeds": list(SEEDS), "arms": list(ARMS), "steps": 20, "learning_rate": 0.05,
        "student": {"backbone": "one TransformerEncoder layer, width64, heads4, FF128, dropout0",
            "backbone_parameters": 33472, "shared_readout_parameters": 99840, "total_parameters": 133312,
            "initialization": "new random student, identical seed initial weights across input controls",
            "optimizer": "stock SGD, no momentum or state, gradient norm clipped at1",
            "full_batch_train_source_groups": 8, "parameter_example_updates_per_arm": 21329920},
        "teacher": {"candidate": TEACHER, "revision": TEACHER_REVISION, "checkpoint_inventory_sha256": TEACHER_INVENTORY,
            "bank_manifest_sha256": BANK_SHA256, "feature_file_sha256": FEATURE_FILE_SHA256,
            "targets": RECIPE["targets"], "executed_or_trained_in_this_probe": False},
        "dataset_manifest_sha256": DATASET_SHA256, "raw_root": str(raw_root), "teacher_bank_root": str(bank_root),
        "selected_source_groups": {role: [f"coco2017:{row['image_id']}" for row in rows] for role, rows in selection.items()},
        "selected_caption_ids": {role: [row["caption_id"] for row in rows] for role, rows in selection.items()},
        "grouping": "original image and its canonical source caption form one group; all five roles disjoint",
        "role_names": ROLE_NAMES, "recipe": RECIPE, "sampling_uses_labels_or_model_outputs": False,
        "known_reuse": "original COCO bank and source groups previously used in multimodal pairing/model-comparison work",
        "evaluation_boundary": "COCO2017 validation photos/captions, 8 per role, exploratory reuse; no fresh blind, temporal, OOD or cross-task claim",
        "legacy_role_warning": "future_1/future_2/ood are API slot names only; actual roles are dev/testA/testB",
        "objectives": "MSE + 0.1*(1-cosine); only train provides gradients; calibration does not choose hyperparameters",
        "metrics": ["objective", "mse", "cosine", "within-role target retrieval R@1 with8 targets"],
        "controls": {"before_training": "same actual randomly initialized model and each arm's own inputs",
            "single_modality": "same architecture, targets, initial seed,20steps and parameter-example update count; differing raw information",
            "train_target_mean": "training-target centroid repeated as prediction; no SGD or raw input, cheaper and not compute matched"},
        "outcome_policy": "retain all3seeds and all arms; no resampling, early stopping, thresholds or tuning from evaluation results",
        "negative_checks": ["ancestor teacher-source withdrawal", "source-group withdrawal", "whole-bank withdrawal",
                            "frontier rollback after rejection", "reload exact prediction parity"],
        "cost_scope": "actual model forwards and parameter-example updates; tensors and gradients; excludes backend operations, activations and allocator peak",
        "code_dependency_sha256": dependencies(), "runtime": {"python": platform.python_version(),
            "torch": torch.__version__, "numpy": np.__version__, "pillow": PIL.__version__, "platform": platform.platform()},
        "foundation_encoder_updates": 0, "old_cell_or_feature_generation_reuse_allowed": False,
        "inference_scope": "replay only the artifact's exact source-bound five cohorts; new inputs require new evidence",
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    plan_sha = write(target / "plan.json", plan)  # No scoring/training above this point.
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    cohorts, records, inputs, input_sha = make_inputs(raw_root, bank_root, selection, target / "inputs")
    targets = {name: read_shard(cohorts[name].teacher_shard)[0] for name in SPLITS}
    centroid = targets["train"].mean(0)
    centroid_metrics = {name: metrics(centroid.repeat(len(targets[name]), 1).numpy(), targets[name]) for name in SPLITS}
    results, ledgers = [], []
    for seed in SEEDS:
        (target / f"seed-{seed}").mkdir()
        initial_hashes = []
        for arm in ARMS:
            pairs = control_cohorts(cohorts, arm)
            directory = target / f"seed-{seed}" / arm
            withdrawals = Withdrawals()
            student, predictions = train_shared_student(pairs, records, directory, withdrawals, seed=seed,
                teacher_bank_sha256=BANK_SHA256, input_manifest_sha256=input_sha, scope_id=SCOPE,
                steps=plan["steps"], learning_rate=plan["learning_rate"])
            report = student.report
            initial_hashes.append(report["initial_tensor_sha256"])
            observed = {"student_forwards": 0, "readout_forwards": 0, "student_examples": 0, "readout_examples": 0}
            reloaded = load_shared_student(directory, expected_manifest_sha256=student.manifest_sha256,
                                           withdrawal_provider=withdrawals)
            handles = []
            for component in ("student", "readout"):
                def observe(module, args, name=component):
                    observed[name + "_forwards"] += 1
                    observed[name + "_examples"] += len(args[0])
                handles.append(reloaded._model[component].register_forward_pre_hook(observe))
            for name in SPLITS:
                result = reloaded.predict_slots(pairs[name].slots, role=name,
                    expected_slots_sha256=pairs[name].expected_slot_sha256, withdrawal_provider=withdrawals)
                if not np.array_equal(result["teacher_prediction"].numpy(), predictions["after:" + name]):
                    raise AssertionError("reloaded real shared student changed predictions")
            for handle in handles:
                handle.remove()
            np.savez(directory / "predictions.npz", **predictions)
            scores = {stage: {name: metrics(predictions[stage + ":" + name], targets[name]) for name in SPLITS}
                      for stage in ("before", "after")}
            for stage in scores:
                for name in SPLITS:
                    ledgers.append({"seed": seed, "arm": arm, "stage": stage, "role": name,
                        "role_meaning": ROLE_NAMES[name], "source_records": records[name],
                        "student_slots_sha256": pairs[name].expected_slot_sha256,
                        "teacher_target_sha256": inputs["teacher_target_sha256"][name],
                        "predictions_npz_key": stage + ":" + name, **scores[stage][name]})
            faults = []
            sources = {"teacher_source": records["train"][0]["teacher_image_source_sha256"],
                "source_group": digest(["shared-student-source-group.v1", records["train"][0]["source_group_id"]]),
                "teacher_bank": BANK_SHA256}
            for kind, source in sources.items():
                provider = Withdrawals()
                candidate = load_shared_student(directory, expected_manifest_sha256=student.manifest_sha256,
                                                withdrawal_provider=provider)
                calls = [0]
                def count(module, args):
                    calls[0] += 1
                hook = candidate._model["student"].register_forward_pre_hook(count)
                provider.revoke(source)
                invalid = rejection(lambda: candidate.predict_slots(pairs["ood"].slots, role="ood",
                    expected_slots_sha256=pairs["ood"].expected_slot_sha256, withdrawal_provider=provider))
                provider.view = WithdrawalViewV1(SCOPE)
                rollback = rejection(lambda: candidate.predict_slots(pairs["ood"].slots, role="ood",
                    expected_slots_sha256=pairs["ood"].expected_slot_sha256, withdrawal_provider=provider))
                hook.remove()
                if calls[0]:
                    raise AssertionError("withdrawn shared student executed")
                faults.append({"source_kind": kind, "source_sha256": source, **invalid,
                               "frontier_rollback": rollback, "actual_student_forwards": calls[0]})
            entry = {"seed": seed, "arm": arm, "artifact_manifest_sha256": student.manifest_sha256,
                "predictions_npz_sha256": sha((directory / "predictions.npz").read_bytes()),
                "artifact": report, "scores": scores, "reload_bitwise_equal": True,
                "reload_actual_forwards": observed, "withdrawal_faults": faults}
            results.append(entry)
            print(json.dumps({"seed": seed, "arm": arm,
                "after_objective": {name: scores["after"][name]["objective"] for name in SPLITS}}), flush=True)
        if len(set(initial_hashes)) != 1:
            raise AssertionError("control initial model parameters differ")
    if dependencies() != plan["code_dependency_sha256"] or select_sources(raw_root) != selection:
        raise ValueError("experiment code or original source partition changed")
    report = {"schema": "hepta.real-shared-tiny-report.v1", "plan_sha256": plan_sha,
        "input_manifest_sha256": input_sha, "elapsed_ns": time.perf_counter_ns() - started,
        "process_cpu_ns": time.process_time_ns() - cpu,
        "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "results": results, "train_target_mean_baseline": centroid_metrics,
        "ledger_sha256": write(target / "prediction_ledger.json", ledgers),
        "trained_artifacts": 9, "new_shared_student_optimizer_steps": 180, "foundation_encoder_updates": 0,
        "old_cell_or_feature_generation_reuse_allowed": False,
        "fresh_blind_or_cross_task_or_temporal_qualification": False,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    write(target / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw-root", "bank-root", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    report = run_probe(args.raw_root, args.bank_root, args.output)
    print(json.dumps({"artifacts": report["trained_artifacts"], "elapsed_ms": report["elapsed_ns"] / 1e6}), flush=True)
