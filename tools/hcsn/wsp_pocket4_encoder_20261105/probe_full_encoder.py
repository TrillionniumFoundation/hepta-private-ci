#!/usr/bin/env python3
"""Bounded CPU engineering probe on the actual Laya encoder and adapters.

Inputs are explicitly synthetic, public and unlabeled. This is not a price
forecast evaluation, training run, accelerator qualification or live rollback.
"""
import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time


sys.dont_write_bytecode = True


HELPER_SHA256 = "dee2de37754edbebdc2c80b7ff1796ae8575d7e6d58c70ed4cd8267362f34f6c"
PINNED_SOURCES = {
    "__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "model.py": "64bfa801f4d98c795f64d76fedea70c377b5b9225a26d73c426893e5338be29d",
    "resident_model.py": "5d4c0dc65fd5b765f4f01e949220854a352ef5cb2e984e5551d2470ec4f34cdb",
    "dataset.py": "bdc75bbfbe2b6d6ff674d36b86ddc5502f263cb5cca7ba3f01fb9cb878fea22b",
    "integrity.py": "85b038abf31b281a6972d48ac2ed96c2124353f47c17316dcdb10b331de01694",
    "tokenizer.py": "23c270172ffa944060cce3bd0b3cda343da119ee16990d938b99b38f49e34770",
}
LAYERS = ("scorer.1", "scorer.3", "act_head.2")


def require(value, code):
    if not value:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_once(path, value):
    raw = canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def synthetic_states():
    specs = [("EUR.USD", 300, 6, "flat", "1.1000"),
             ("EUR.USD", 900, 6, "up", "1.1000"),
             ("BTC.USD", 300, 24, "alternating", "60000"),
             ("BTC.USD", 900, 24, "down", "60000")]
    states = []
    for instrument, horizon, count, pattern, base in specs:
        base = Decimal(base)
        quotes = []
        for index in range(count):
            move = {"flat": 0, "up": index, "alternating": (-1)**index * 2,
                    "down": -index}[pattern]
            mid = base * (1 + Decimal(move) / Decimal(10000))
            spread = base / Decimal(100000)
            quotes.append([(index - count + 1) * 1000, str(mid - spread), str(mid + spread)])
        states.append({"instrument": instrument, "anchor_ms": 1793854800000,
                       "reference_mid": str((Decimal(quotes[-1][1]) + Decimal(quotes[-1][2])) / 2),
                       "horizon_sec": horizon, "columns": ["offset_ms", "bid", "ask"],
                       "quotes": quotes, "quantity": "underlying MID return; not execution profit"})
    return states


def run(output):
    began, cpu = time.perf_counter(), time.process_time()
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.wsp.full_laya_synthetic_cpu_probe.v1", "status": "STARTED",
              "production_mutated": False, "training_executed": False, "broker_queries_sent": 0,
              "orders_sent": 0, "private_rows_used": False, "value_qualified": False,
              "full_model_forwards_completed": 0, "rows": [], "stage": "binding"}
    cell = parent_state = None
    try:
        helper = Path(__file__).with_name("head_probe_helpers.py")
        require(sha(helper.read_bytes()) == HELPER_SHA256, "HELPER_IDENTITY")
        spec = importlib.util.spec_from_file_location("bound_head_helper", helper)
        h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(h)
        config, job, binding = h.bound_live()
        runtime = Path(config["runtime_directory"])
        module_root = runtime / "learn/laya_cell"
        require(not (runtime / "learn/__init__.py").exists(), "LEARN_NAMESPACE_CHANGED")
        source_files = sorted(module_root.glob("*.py"))
        require(0 < len(source_files) <= 256, "SOURCE_COUNT_BOUND")
        source_hashes = {p.name: sha(h.read(p, 262144)) for p in source_files}
        require(all(source_hashes.get(k) == v for k, v in PINNED_SOURCES.items()), "MODEL_SOURCE_CHANGED")
        raw_inputs = {}
        manifest_inputs = {}
        adapter_manifests = {}
        for name, directory in (("candidate", job["output_directory"]), ("parent", job["parent_directory"])):
            raw_inputs[name] = h.read(Path(directory) / "adapter.safetensors", 1048576)
            manifest_inputs[name] = h.read(Path(directory) / "candidate.json", 524288)
            adapter_manifests[name] = h.unique_json(manifest_inputs[name])
            record = adapter_manifests[name]
            require(record["candidate_id"] == sha(canonical({k: v for k, v in record.items()
                                                            if k != "candidate_id"})), "ADAPTER_CONTENT_ID")
            require(record["adapter_sha256"] == sha(raw_inputs[name]), "ADAPTER_MANIFEST_BINDING")
        candidate = adapter_manifests["candidate"]
        require(candidate["candidate_id"] == h.EXPECTED["candidate_id"], "CANDIDATE_MANIFEST_IDENTITY")
        require(sha(manifest_inputs["parent"]) == job["parent_manifest_sha256"], "PARENT_MANIFEST_IDENTITY")
        require(sha(raw_inputs["candidate"]) == h.EXPECTED["adapter_sha256"], "CANDIDATE_IDENTITY")
        require(sha(raw_inputs["parent"]) == h.EXPECTED["parent_adapter_sha256"], "PARENT_IDENTITY")
        base_dir = Path(config["base_directory"])
        manifest_raw = h.read(base_dir / "base-manifest.json", 65536)
        manifest = h.unique_json(manifest_raw)
        require(sha(canonical(manifest)) == h.EXPECTED["base_id"], "BASE_MANIFEST_IDENTITY")
        require(all(record["base_id"] == h.EXPECTED["base_id"] for record in adapter_manifests.values()),
                "ADAPTER_BASE_BINDING")
        require(manifest["files"]["model.safetensors"]["sha256"] == h.EXPECTED["base_model_sha256"],
                "BASE_CHECKPOINT_BINDING")
        require(candidate["profile"]["targets"] == {
                    "scorer.1": {"rows": [0, 1, 2, 3], "rank": 2},
                    "scorer.3": {"rows": [0], "rank": 1}} and
                candidate["profile"]["action_targets"] == {
                    "act_head.2": {"rows": [0, 1], "cols": list(range(64)), "rank": 1}},
                "DECLARED_PROFILE_CHANGED")
        protocol = {"schema": "hepta.wsp.full_laya_probe.protocol.v1", "expected": h.EXPECTED,
                    "binding": binding, "source_sha256": source_hashes,
                    "adapter_manifest_sha256": {k: sha(v) for k, v in manifest_inputs.items()},
                    "driver_sha256": sha(Path(__file__).read_bytes()), "helper_sha256": HELPER_SHA256,
                    "synthetic_states": synthetic_states(), "states_are_unlabeled": True,
                    "parent_child_restore_order": ["parent", "child", "restored"],
                    "layers": LAYERS, "atol": 0.00002, "rtol": 0.00002,
                    "max_len": 1024, "cpu_threads": 1, "expected_full_forwards": 12,
                    "original_head_probe_failed_gate_is_not_replaced": True,
                    "scope": "Original encoder and installed source classes on four synthetic public states; engineering checks only"}
        result["protocol_sha256"] = write_once(output / "PROTOCOL_FROZEN.json", protocol)
        admission_state = h.unique_json(h.read(Path(config["control_directory"]) / "status.json", 262144))
        require(admission_state["job_counts"]["RUNNING"] == 0, "TRAINER_RUNNING_AT_ADMISSION")
        available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        require(available >= 8 * 1024**3, "HOST_MEMORY_BELOW_ADMISSION_FLOOR")
        result["admission"] = {"running_training_jobs": 0, "mem_available_bytes": available,
                               "minimum_mem_available_bytes": 8 * 1024**3,
                               "is_snapshot_not_resource_reservation": True}
        result["stage"] = "load_full_checkpoint"
        sys.path.insert(0, str(runtime))
        import numpy as np
        import torch
        from safetensors.torch import load
        from learn.laya_cell.dataset import encode_rows, question
        from learn.laya_cell.integrity import verify_snapshot
        from learn.laya_cell.model import load_verified_laya
        from learn.laya_cell.resident_model import ResidentDecisionCell
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.manual_seed(20261105)
        require(not torch.cuda.is_initialized(), "GPU_INITIALIZED")
        raw, tokenizer, base_id = load_verified_laya(base_dir, manifest, enforce_gpu=False)
        require(base_id == h.EXPECTED["base_id"], "LOADED_BASE_IDENTITY")
        require(all(p.device.type == "cpu" and p.dtype == torch.float32 for p in raw.parameters()),
                "MODEL_NOT_CPU_F32")
        require(not any(module.training for module in raw.modules()), "MODEL_NOT_EVAL")
        result["model"] = {"base_id": base_id, "checkpoint": manifest["files"]["model.safetensors"],
                           "pretrained_parameters": sum(p.numel() for p in raw.parameters()),
                           "python_version": sys.version.split()[0],
                           "torch_version": torch.__version__, "numpy_version": np.__version__,
                           "execution_dtype": "CPU_F32", "threads": torch.get_num_threads()}
        cell = ResidentDecisionCell(raw, base_id)
        parent, child = load(raw_inputs["parent"]), load(raw_inputs["candidate"])
        child_keys = {"model." + layer + "." + factor for layer in LAYERS for factor in ("A", "B")}
        require(set(child) == set(candidate["tensor_mask"]) == child_keys, "CHILD_TENSOR_MASK")
        require(set(parent) == {key for key in child_keys if ".scorer." in key}, "PARENT_TENSOR_MASK")

        def factor_identity(state):
            require(all(value.device.type == "cpu" and value.dtype == torch.float32 and
                        torch.isfinite(value).all() for value in state.values()), "FACTOR_NOT_FINITE_CPU_F32")
            return {name: {"shape": list(value.shape), "dtype": str(value.dtype),
                           "sha256": sha(value.detach().contiguous().numpy().tobytes())}
                    for name, value in sorted(state.items())}

        cell.restore_parent(parent, allow_scorer_only=True)
        parent_state = cell.trainable_state()
        require(set(child) == set(parent_state), "CHILD_TENSOR_MASK")
        require(torch.count_nonzero(parent_state["model.act_head.2.B"]).item() == 0,
                "PARENT_ACTION_DELTA_NOT_ZERO")
        expected_factor_identities = {"parent": factor_identity(parent_state), "child": factor_identity(child)}
        require(not any(module.training for module in cell.modules()), "CELL_NOT_EVAL")
        result["complete_factor_identities"] = expected_factor_identities
        result["parent_action_augmentation"] = "Source-initialized A and zero B preserve the original base action head"
        all_numeric = True
        result["stage"] = "forward"
        for index, state in enumerate(protocol["synthetic_states"]):
            batch = encode_rows(tokenizer, [{"state": state, "question": question(state["horizon_sec"])}],
                                max_len=protocol["max_len"])
            require(all(value.device.type == "cpu" for value in batch.values()), "BATCH_NOT_CPU")
            row = {"index": index, "input_sha256": sha(canonical(state)),
                   "batch_shapes": {k: list(v.shape) for k, v in batch.items()}, "passes": {}}
            outputs = {}
            for phase, weights in (("parent", parent_state), ("child", child), ("restored", parent_state)):
                cell.restore_trainable(weights)
                require(factor_identity(cell.trainable_state()) == expected_factor_identities[
                            "child" if phase == "child" else "parent"], "RESTORED_FACTOR_BYTES_MISMATCH")
                captures, encoder_capture, hooks = {}, {}, []
                def capture(name):
                    def apply(_module, args, y):
                        require(name not in captures, "DUPLICATE_HEAD_FORWARD")
                        captures[name] = (args[0].detach().clone(), y.detach().clone())
                    return apply
                def capture_encoder(_module, _args, encoded):
                    require(not encoder_capture, "DUPLICATE_ENCODER_FORWARD")
                    hidden = encoded.last_hidden_state.detach()
                    require(hidden.device.type == "cpu" and hidden.dtype == torch.float32 and
                            torch.isfinite(hidden).all(), "ENCODER_NOT_FINITE_CPU_F32")
                    encoder_capture.update(shape=list(hidden.shape), dtype=str(hidden.dtype),
                                           sha256=sha(hidden.contiguous().numpy().tobytes()),
                                           max_absolute_activation=float(hidden.abs().max()))
                hooks.append(cell.model.encoder.register_forward_hook(capture_encoder))
                for name in LAYERS:
                    hooks.append(cell.model.get_submodule(name).register_forward_hook(capture(name)))
                try:
                    with torch.no_grad():
                        y = cell(**batch)
                finally:
                    for hook in hooks:
                        hook.remove()
                result["full_model_forwards_completed"] += 1
                require(len(y) == 2 and y[0].shape == (1, 7) and y[1].shape == (1, 2), "FULL_OUTPUT_SHAPE")
                require(all(t.device.type == "cpu" and t.dtype == torch.float32 for t in y), "OUTPUT_NOT_CPU_F32")
                require(all(torch.isfinite(t).all() for t in y) and set(captures) == set(LAYERS), "NONFINITE_OR_MISSING_OUTPUT")
                require(bool(encoder_capture), "ENCODER_FORWARD_MISSING")
                outputs[phase] = tuple(t.detach().numpy().copy() for t in y)
                report = {"output_sha256": [sha(t.tobytes()) for t in outputs[phase]],
                          "complete_factor_bytes_match_expected": True,
                          "encoder_output": encoder_capture,
                          "price_argmax": int(y[0].argmax()), "action_argmax": int(y[1].argmax()), "heads": {}}
                for name in LAYERS:
                    module = cell.model.get_submodule(name)
                    x, actual = captures[name]
                    x = x.numpy().reshape(-1, x.shape[-1]).astype(np.float64)
                    actual = actual.numpy().reshape(-1, actual.shape[-1]).astype(np.float64)
                    w = module.base.weight.detach().numpy().astype(np.float64)
                    b = module.base.bias.detach().numpy().astype(np.float64)
                    aa = module.A.detach().numpy().astype(np.float64)
                    bb = module.B.detach().numpy().astype(np.float64)
                    reference = x @ w.T + b
                    delta = ((x[:, :64] if name == "act_head.2" else x) @ aa.T) @ bb.T
                    if name == "act_head.2":
                        reference += delta
                    else:
                        reference[:, :bb.shape[0]] += delta
                    require(np.isfinite(x).all() and np.isfinite(actual).all() and np.isfinite(reference).all(),
                            "NONFINITE_HEAD_REFERENCE")
                    error = np.abs(actual - reference)
                    allowed = protocol["atol"] + protocol["rtol"] * np.abs(reference)
                    failed = np.argwhere(error > allowed)
                    numeric = len(failed) == 0
                    all_numeric = all_numeric and numeric
                    report["heads"][name] = {"input_shape_flat": list(x.shape),
                        "input_max_abs": float(np.abs(x).max()), "max_absolute_error": float(error.max()),
                        "max_error_over_allowed": float((error / allowed).max()), "allclose": numeric,
                        "failed_count": len(failed), "failed_coordinates_first64": failed[:64].tolist(),
                        "all_failed_coordinates_sha256": sha(canonical(failed.tolist())),
                        "source_output_sha256": sha(actual.astype(np.float32).tobytes())}
                row["passes"][phase] = report
            row["restored_output_bytes_equal"] = all(
                np.array_equal(a.view(np.uint32), b.view(np.uint32))
                for a, b in zip(outputs["parent"], outputs["restored"]))
            require(row["restored_output_bytes_equal"], "FULL_RESTORE_MISMATCH")
            row["encoder_output_bytes_equal_all_phases"] = len({
                row["passes"][phase]["encoder_output"]["sha256"] for phase in ("parent", "child", "restored")}) == 1
            require(row["encoder_output_bytes_equal_all_phases"], "FROZEN_ENCODER_OUTPUT_CHANGED")
            row["child_parent_max_absolute_output_changes"] = [
                float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64))))
                for a, b in zip(outputs["child"], outputs["parent"])]
            result["rows"].append(row)
        require(result["full_model_forwards_completed"] == protocol["expected_full_forwards"], "FORWARD_COUNT")
        cell.assert_frozen()
        require(verify_snapshot(base_dir, manifest) == base_id, "BASE_CHANGED_AFTER_EXECUTION")
        require(h.bound_live()[2] == binding, "LIVE_BINDING_CHANGED")
        require({p.name: sha(h.read(p, 262144)) for p in source_files} == source_hashes, "SOURCE_CHANGED_AFTER_EXECUTION")
        require(not (runtime / "learn/__init__.py").exists(), "LEARN_NAMESPACE_CHANGED_AFTER_EXECUTION")
        require(h.read(base_dir / "base-manifest.json", 65536) == manifest_raw, "BASE_MANIFEST_CHANGED")
        for name, directory in (("candidate", job["output_directory"]), ("parent", job["parent_directory"])):
            require(h.read(Path(directory) / "adapter.safetensors", 1048576) == raw_inputs[name], "ADAPTER_CHANGED_AFTER_EXECUTION")
            require(h.read(Path(directory) / "candidate.json", 524288) == manifest_inputs[name], "ADAPTER_MANIFEST_CHANGED")
        require(not torch.cuda.is_initialized(), "GPU_INITIALIZED_AT_END")
        result.update(status="PASS_SYNTHETIC_CPU_FULL_PATH" if all_numeric else "FAIL_FIXED_HEAD_REFERENCE_ON_FULL_PATH",
                      full_model_path_executed=True, all_head_numeric_checks=all_numeric,
                      frozen_parameters_unchanged=True, live_binding_unchanged=True, gpu_initialized=False,
                      production_rollback_qualified=False, original_high_scale_gate_still_failed=True)
    except Exception as error:
        result["status"] = "FAILED_PRESERVED"
        message = str(error)
        result["failure"] = {"type": type(error).__name__, "code": message if
                             message.isupper() and message.replace("_", "").isalnum() and len(message) < 100
                             else "REDACTED_EXCEPTION"}
    finally:
        if cell is not None and parent_state is not None:
            try:
                cell.restore_trainable(parent_state)
                require(factor_identity(cell.trainable_state()) == expected_factor_identities["parent"],
                        "EXIT_FACTOR_BYTES_MISMATCH")
                result["in_memory_parent_factors_restored_on_exit"] = True
            except Exception:
                result["in_memory_parent_factors_restored_on_exit"] = False
                result["status"] = "FAILED_PRESERVED"
    result["cost"] = {"worker_wall_seconds": time.perf_counter() - began,
                      "worker_cpu_seconds": time.process_time() - cpu,
                      "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      "nested_worker_cost_not_additive_to_supervisor": True}
    result_hash = write_once(output / "RESULTS.json", result)
    print(json.dumps({"status": result["status"], "result_sha256": result_hash,
                      "full_forwards": result["full_model_forwards_completed"]}))
    return 0 if result["status"] == "PASS_SYNTHETIC_CPU_FULL_PATH" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().output))
