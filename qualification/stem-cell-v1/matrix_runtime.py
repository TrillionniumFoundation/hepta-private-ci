"""Run admitted local HF weights through actual V2 Cell populations.

This CPU FP32 executor supports fixed arms and an explicit offline growth profile.
It seals predictions before the separate observer join. No automatic download,
random-weight fallback, final-label loading, native installation or promotion.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

from hf_encoder_kernel import (snapshot_digest, validate_encoder_loading_info,
                               verify_loaded_safetensors, vectorize_case)
from matrix_materials import (file_sha256, public_row, strict_json, validate_config,
                             validate_workload)
from next_round_matrix import _digest
from paired_execution import PHASES

SOURCE_FILES = ("next_round_matrix.py", "paired_execution.py", "head_surgery.py",
                "hf_encoder_kernel.py", "matrix_materials.py", "matrix_bank.py",
                "matrix_runtime.py", "matrix_export.py", "aten_work.py",
                "host_counters.py", "execution_meter.py", "matrix_growth.py", "family_routing.py", "hf_complete_checkpoint.py", "transformer_work.py", "retention_training.py", "consolidation_training.py", "consolidation_record.py")


def verify_source(source_sha):
    """Match all local first-party execution sources to the named Git commit."""
    root = Path(__file__).resolve().parents[2]
    hashes = {}
    for name in SOURCE_FILES:
        relative = "qualification/stem-cell-v1/" + name
        observed = (root / relative).read_bytes()
        result = subprocess.run(["git", "-C", str(root), "show", f"{source_sha}:{relative}"],
                                capture_output=True, check=False, timeout=15)
        if result.returncode or result.stdout != observed:
            raise ValueError("working source does not match the execution contract commit: " + name)
        hashes[relative] = file_sha256(root / relative)
    return hashes


class LocalHFEncoder:
    """Pinned, completely materialized local tensors; operator provenance only."""

    def __init__(self, snapshot, config, profile):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.root = Path(snapshot).resolve()
        self.expected = config["snapshot_sha256"]
        if snapshot_digest(self.root) != self.expected:
            raise ValueError("model snapshot digest mismatch")
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.root), local_files_only=True,
                                                       trust_remote_code=False)
        self.complete_receipt = None
        if config.get("encoder_profile") is not None:
            from hf_complete_checkpoint import load_complete_mlm
            self.checkpoint_model, model, self.complete_receipt = load_complete_mlm(self.root)
            load_receipt = self.complete_receipt["loading"]
            exact_receipt = self.complete_receipt["materialization"]
        else:
            loaded = AutoModel.from_pretrained(str(self.root), local_files_only=True,
                                              trust_remote_code=False, use_safetensors=True,
                                              output_loading_info=True, torch_dtype=torch.float32)
            if not isinstance(loaded, tuple) or len(loaded) != 2:
                raise ValueError("complete weight-loading report required")
            model, info = loaded
            load_receipt = validate_encoder_loading_info(info)
            model = model.to("cpu").eval().requires_grad_(False)
            exact_receipt = verify_loaded_safetensors(torch, model, self.root)
            self.checkpoint_model = model
        count = sum(p.numel() for p in self.checkpoint_model.parameters())
        if profile["stem"] == "421m" and not 350_000_000 <= count <= 480_000_000:
            raise ValueError("loaded model is not a 421M-class Encoder")
        if profile["stem"] == "smaller_control" and not 0 < count < 350_000_000:
            raise ValueError("loaded model is not the declared smaller control")
        self.dimension = getattr(model.config, "hidden_size", None)
        if type(self.dimension) is not int or not 1 <= self.dimension <= 8192:
            raise ValueError("invalid declared hidden dimension")
        position_limit = getattr(model.config, "max_position_embeddings", None)
        if type(position_limit) is int and position_limit < config["context_tokens"]:
            raise ValueError("context exceeds model position budget")
        self.model, self.max_tokens, self.calls = model, config["context_tokens"], 0
        from head_surgery import tensor_inventory
        self.weight_bytes = tensor_inventory(self.checkpoint_model)["unique_weight_bytes"]
        self.receipt = dict(snapshot_sha256=self.expected, upstream_revision=config["upstream_revision"],
                            frozen_encoder_params=count, loading=load_receipt, materialization=exact_receipt,
                            material_approval_sha256=config["material_approval_sha256"],
                            pretrained_provenance_independently_verified=False)
        if self.complete_receipt is not None:
            self.receipt["complete_checkpoint"] = self.complete_receipt
        self.reverify()

    def encode(self, row):
        import torch
        self.calls += 1  # Failed forward attempts also consume an invocation.
        return vectorize_case(torch, self.model, self.tokenizer, row, "cpu", max_tokens=self.max_tokens)

    def reverify(self):
        import torch
        if snapshot_digest(self.root) != self.expected:
            raise ValueError("snapshot changed during execution")
        if self.complete_receipt is not None:
            from hf_complete_checkpoint import TIED_ALIASES
            verify_loaded_safetensors(torch, self.checkpoint_model, self.root, tied_aliases=TIED_ALIASES)
        else:
            verify_loaded_safetensors(torch, self.checkpoint_model, self.root)
        if any(p.requires_grad for p in self.checkpoint_model.parameters()):
            raise ValueError("selected Encoder unexpectedly became trainable")


def execute(plan, contract, config, workload, backend, *, clock=time.time_ns, meter=None):
    """Testable tensor execution; non-HF backends remain mechanism fixtures."""
    import torch
    from matrix_bank import CellBank, state_digest, train_bank
    profile = validate_config(plan, contract, config)
    if ("measurement_policy" in config) != (meter is not None):
        raise ValueError("bound measurement policy requires its actual execution meter")
    if meter is not None and (meter.policy != config["measurement_policy"] or meter.caps != contract["flops_caps"]):
        raise ValueError("execution meter differs from frozen policy or phase caps")
    classes = validate_workload(workload, contract)
    train = workload["train"]
    reference_bytes, subset_bytes = 0, 0
    if "retention_policy" in config:
        from retention_training import validate_retention_rows
        roles = validate_retention_rows(train, config["retention_policy"])
        reference_bytes = len(train) * classes * 4 * (2 if "consolidation_policy" in config else 1)
        # At most one full fitting subset is retained alongside the original
        # cache/reference. Batch/activation/optimizer memory is still separate.
        subset_bytes = (len(roles["old_train_groups"]) + len(roles["new_train_groups"])) * backend.dimension * 4
    if len(train) * backend.dimension * 4 + reference_bytes + subset_bytes > config["max_feature_bytes"]:
        raise ValueError("feature allocation exceeds the frozen byte cap")
    scope = meter.scope if meter is not None else lambda *args: contextlib.nullcontext()
    started = time.perf_counter_ns()
    # One retained cache allocation, not list-of-vectors plus a second stack.
    # The feature cap covers retained payload; process/activation memory is separate.
    with scope("train", "encoder"):
        features = torch.empty((len(train), backend.dimension), dtype=torch.float32)
        for index, row in enumerate(train):
            vector = backend.encode(public_row(row))[0]
            if (vector.shape != (backend.dimension,) or vector.dtype != torch.float32
                    or vector.device.type != "cpu" or vector.requires_grad
                    or not torch.isfinite(vector).all().item()):
                raise ValueError("invalid frozen actual Encoder features")
            features[index].copy_(vector)
        del vector
    feature_ns = time.perf_counter_ns() - started
    with scope("train", "initialization"):
        # Weight loading cannot perturb Head initialization/minibatch seed.
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(plan["seed"])
            if "growth_policy" in config:
                from matrix_growth import initial_bank
                bank = initial_bank(backend.dimension, classes, profile, config,
                                    parameter_cap=contract["max_peak_trainable_params"])
            else:
                bank = CellBank(backend.dimension, classes, profile, config["width_units"])
        targets = torch.tensor([r["label"] for r in train], dtype=torch.long)
        before = state_digest(bank)
    started = time.perf_counter_ns()
    if "growth_policy" in config:
        from matrix_growth import train_with_growth
        bank, training = train_with_growth(bank, features, targets, config, contract, profile,
                                          [r["source_group"] for r in train], seed=plan["seed"], meter=meter)
        trained_digest = state_digest(bank)
    else:
        with scope("train", "bank"):
            training = train_bank(bank, features, targets, config, plan["seed"])
            trained_digest = state_digest(bank)
    training_ns = time.perf_counter_ns() - started
    started = time.perf_counter_ns()
    # Warmup is counted online; only its latency sample is excluded.
    with scope("inference", "encoder"), torch.inference_mode():
        vector, _ = backend.encode(public_row(train[0]))
    with scope("inference", "bank"), torch.inference_mode():
        bank(vector.unsqueeze(0))
    warmup_ns = time.perf_counter_ns() - started
    if not contract["eval_start_ns"] <= clock() < contract["eval_end_ns"]:
        raise ValueError("execution is outside the preregistered evaluation window")
    predictions = []
    for row in workload["eval"]:
        start = time.perf_counter_ns()
        record = dict(task_id=row["sample_id"], input_digest=_digest(public_row(row)),
                      status="unknown", logits=None, token_count=None, error_type=None)
        try:
            if clock() >= contract["eval_end_ns"]:
                raise TimeoutError("evaluation deadline")
            with scope("inference", "encoder"), torch.inference_mode():
                vector, length = backend.encode(public_row(row))
            with scope("inference", "bank"), torch.inference_mode():
                logits = bank(vector.unsqueeze(0))[0]
                if not torch.isfinite(logits).all().item():
                    raise ValueError("nonfinite prediction")
            if clock() >= contract["eval_end_ns"]:
                raise TimeoutError("completed beyond evaluation deadline")
            record.update(status="completed", logits=logits.tolist(), token_count=length)
        except Exception as exc:
            record.update(status="timed_out" if isinstance(exc, TimeoutError) else "failed",
                          error_type=type(exc).__name__)
        record["latency_ns"] = max(1, time.perf_counter_ns() - start)
        record["predicted_at_ns"] = clock()
        # After-RSS is not peak RSS, and absent energy counters are not zero.
        record.update(energy_joules=None, peak_memory_bytes=None)
        predictions.append(record)
    if meter is None or meter.stopped is None:
        with scope("verification", "material"):
            backend.reverify()
            if state_digest(bank) != trained_digest:
                raise ValueError("trained bank changed during inference")
    inventory = bank.inventory()
    manifest = dict(schema="hepta.stem.bound-execution.v1", plan_id=plan["plan_id"],
                    contract_id=contract["contract_id"], arm_id=config["arm_id"], config=config,
                    source_sha=contract["source_sha"], device_id=contract["device_id"],
                    workload_sha256=contract["workload_sha256"],
                    execution_kind="pretrained_local_weights" if type(backend) is LocalHFEncoder else "mechanism_fixture",
                    encoder_receipt=backend.receipt, encoder_calls=backend.calls,
                    unique_weight_bytes=backend.weight_bytes + inventory["unique_weight_bytes"],
                    inventory=inventory, training=training, classification_classes=classes,
                    initial_bank_sha256=before, trained_bank_sha256=trained_digest,
                    phase_flops={p: (0 if p in ("search", "migration") else None) for p in PHASES},
                    flop_profile="unmeasured_full_execution", flop_components=[],
                    durations_ns=dict(feature_materialization=feature_ns, training=training_ns, warmup=warmup_ns),
                    actual_compute_caps_verified=False, latency_scope="sequential_encoder_plus_bank_including_failed_requests",
                    outcomes_loaded=False, independent_success_established=False, production_authorized=False)
    if "growth" in training:
        manifest["schema"] = "hepta.stem.bound-execution.v2"
        manifest["growth_receipt"] = training["growth"]
        if "retention" in training:
            manifest["retention_receipt"] = training["retention"]
        manifest["peak_trainable_params"] = training["growth"]["peak_live_trainable_params"]
        manifest["phase_flops"]["migration"] = None if training["growth"]["split_performed"] else 0
    if "consolidation" in training:
        from consolidation_training import OUTPUT_PROFILE
        manifest.update(schema="hepta.stem.bound-execution.v3", output_profile=OUTPUT_PROFILE,
                        consolidation_receipt=training["consolidation"],
                        retention_receipt=training["consolidation"]["final_retention"],
                        peak_trainable_params=training["consolidation"]["peak_live_trainable_params"])
    if meter is not None:
        observation = meter.report()
        manifest["work_observation"] = observation
        manifest["flop_profile"] = observation["profile"]
        for phase in ("train", "inference"):
            manifest["phase_flops"][phase] = observation["phase_flops"][phase]
        if "consolidation" in training or ("growth" in training and training["growth"]["split_performed"]):
            manifest["phase_flops"]["migration"] = observation["phase_flops"]["migration"]
        manifest["latency_scope"] += "_instrumented"
        manifest["feature_cache_payload_bytes"] = features.numel() * features.element_size()
        if "retention_policy" in config:
            manifest["retention_auxiliary_payload_bound_bytes"] = reference_bytes + subset_bytes
        manifest["accounting_gaps"] = ["independent_observer_evaluation", "publication_after_measurement",
                                       "hardware_kernel_instructions", "python_scalar_arithmetic", "request_peak_memory", "process_energy"]
        # Complete legacy aggregate certification remains false: evaluation is separate.
    return bank, manifest, predictions


def write_json_exclusive(path, value):
    data = (json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False, indent=2) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def publish_prediction_bundle(root, bank, manifest, predictions, *, clock=time.time_ns, budget_check=None):
    """Seal newly created artifacts; callers own exclusive directory creation."""
    from safetensors.torch import save_file
    check = budget_check or (lambda: None)
    check()
    save_file(bank.state_dict(), str(root / "bank.safetensors"))
    with (root / "bank.safetensors").open("rb") as stream:
        os.fsync(stream.fileno())
    check()
    write_json_exclusive(root / "predictions.json", predictions)
    check()
    write_json_exclusive(root / "execution.json", manifest)
    committed = {"schema": "hepta.stem.prediction-seal.v1", "sealed_at_ns": clock(),
                 "files": {name: file_sha256(root / name) for name in
                           ("predictions.json", "execution.json", "bank.safetensors")}}
    committed["seal_id"] = _digest(committed)
    check()
    write_json_exclusive(root / "COMMITTED.json", committed)
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    check()  # A late failure is fenced by run_bound's FAILED marker.
    return committed


def run_bound(plan, contract, config, workload_path, snapshot, output):
    profile = validate_config(plan, contract, config)
    if file_sha256(workload_path) != contract["workload_sha256"]:
        raise ValueError("workload bytes differ from the frozen contract")
    workload = strict_json(workload_path)
    validate_workload(workload, contract)
    if "retention_policy" in config:
        from retention_training import validate_retention_rows
        validate_retention_rows(workload["train"], config["retention_policy"])
    sources = verify_source(contract["source_sha"])
    root = Path(output)
    root.mkdir(exist_ok=False)  # A failed/partial run is never overwritten.
    meter = None
    try:
        if "measurement_policy" in config:
            from execution_meter import WorkLedger, BudgetStop
            meter = WorkLedger(config["measurement_policy"], contract["flops_caps"])
        with meter.scope("setup", "encoder") if meter else contextlib.nullcontext():
            backend = LocalHFEncoder(snapshot, config, profile)
        bank, manifest, predictions = execute(plan, contract, config, workload, backend, meter=meter)
        if meter is not None and meter.stopped:
            write_json_exclusive(root / "partial_predictions.json", predictions)
            raise BudgetStop(meter.stopped)
        if file_sha256(workload_path) != contract["workload_sha256"]:
            raise ValueError("workload changed during execution")
        if verify_source(contract["source_sha"]) != sources:
            raise ValueError("execution source changed")
        manifest["source_files_sha256"] = sources
        manifest["predictions_complete_at_ns"] = time.time_ns()
        return publish_prediction_bundle(root, bank, manifest, predictions,
                                         budget_check=meter.check if meter else None)
    except Exception as exc:
        failure = {"status": "failed", "error_type": type(exc).__name__,
                   "expected_task_ids": contract["task_ids"], "production_authorized": False}
        from matrix_growth import GrowthNotAdmitted
        if isinstance(exc, GrowthNotAdmitted):
            failure["growth_disposition"] = exc.report
        from retention_training import RetentionRejected
        if isinstance(exc, RetentionRejected):
            failure["retention_disposition"] = exc.report
        from consolidation_training import ConsolidationRejected
        if isinstance(exc, ConsolidationRejected):
            failure["consolidation_disposition"] = exc.report
        if meter is not None:
            failure["work_observation"] = meter.report()
        write_json_exclusive(root / "FAILED.json", failure)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("plan", "contract", "config", "workload", "snapshot", "output"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    seal = run_bound(strict_json(args.plan), strict_json(args.contract), strict_json(args.config),
                     args.workload, args.snapshot, args.output)
    print(json.dumps({"seal_id": seal["seal_id"], "production_authorized": False}))


if __name__ == "__main__":
    main()
