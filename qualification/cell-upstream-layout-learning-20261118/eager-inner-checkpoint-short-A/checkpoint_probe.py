"""Prospective original-eager / inner-checkpoint numerical calibration."""

import argparse
import contextlib
import fcntl
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "PROTOCOL.json"
WORK = HERE.parent
OLD_OWNER = Path(
    "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/owner.py"
)
OLD_OWNER_SHA = "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"
LOCK = Path(
    "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-round03-20261118-392934-b/WORKER.lock"
)
PYTHON = "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            + b"\n"
        )


def require(condition, message):
    if not condition:
        raise ValueError(message)


def admit():
    protocol = read(PROTOCOL)
    require(sha(__file__) == protocol["probe_source_sha256"], "probe source changed")
    for name, digest in protocol["original_files"].items():
        require(sha(name) == digest, "fixed dependency changed: " + name)
    deployment = read(WORK / "PROBE_DEPLOYMENT.json")
    require(
        deployment["protocol_sha256"] == sha(PROTOCOL)
        and deployment["probe_source_sha256"] == sha(__file__),
        "published probe deployment differs",
    )
    return protocol, deployment


def old_owner():
    require(sha(OLD_OWNER) == OLD_OWNER_SHA, "original owner utility changed")
    spec = importlib.util.spec_from_file_location("sdpa_original_owner", OLD_OWNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def walk_nodes(root):
    pending, seen, counts = [root], set(), {}
    while pending:
        node = pending.pop()
        if node is None or node in seen:
            continue
        seen.add(node)
        name = type(node).__name__
        counts[name] = counts.get(name, 0) + 1
        pending.extend(child for child, _ in node.next_functions)
    return counts


def compare(torch, first, second):
    a, b = first["logits"].float(), second["logits"].float()
    difference = (a - b).abs()
    squared, reference, dot, norm_b, maximum = 0.0, 0.0, 0.0, 0.0, 0.0
    require(first["gradients"].keys() == second["gradients"].keys(), "gradient keys")
    for name in first["gradients"]:
        x, y = first["gradients"][name].double(), second["gradients"][name].double()
        squared += float(((x - y) ** 2).sum())
        reference += float((x**2).sum())
        norm_b += float((y**2).sum())
        dot += float((x * y).sum())
        maximum = max(maximum, float((x - y).abs().max()))
    require(reference > 0 and norm_b > 0, "nonzero actual gradients required")
    return {
        "absolute_cross_entropy_difference": abs(first["loss"] - second["loss"]),
        "selected_logit_max_absolute_difference": float(difference.max()),
        "selected_logit_mean_absolute_difference": float(difference.mean()),
        "selected_logit_argmax_agreement": float(
            (a.argmax(-1) == b.argmax(-1)).double().mean()
        ),
        "gradient_relative_l2_error": (squared / reference) ** 0.5,
        "gradient_cosine_similarity": dot / ((reference * norm_b) ** 0.5),
        "gradient_max_absolute_difference": maximum,
        "eager_gradient_l2": reference**0.5,
        "candidate_gradient_l2": norm_b**0.5,
        "bitwise_equivalence_claimed": False,
    }


def child():
    protocol, deployment = admit()
    original = Path(protocol["original_candidate_root"])
    sys.path.insert(0, str(original))
    ctx = __import__("layout_context")
    layout = __import__("layout_sft")
    records = ctx.read(original / "prepared/DATASET.json")
    if isinstance(records, dict):
        records = records["records"]
    require(
        ctx.data.digest(records) == protocol["train_records_digest"],
        "original records changed",
    )
    output = WORK / "probe-result-1"
    output.mkdir(exist_ok=False)
    write(
        output / "STARTED.json",
        {"at_ns": time.time_ns(), "source_commit": deployment["source_commit"]},
    )
    started, cpu, predictor, torch = (
        time.perf_counter(),
        time.process_time(),
        None,
        None,
    )
    events, saved, comparisons = [], [], []

    def event(name, **values):
        record = {"event": name, "at_ns": time.time_ns(), **values}
        with (output / "COMPUTE.jsonl").open("ab") as stream:
            stream.write(ctx.data.canonical(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        events.append(record)

    try:
        torch, _ = layout.probe._libraries()
        checkpoint_engine = __import__("checkpoint_softmax")
        checkpoint_engine.register()
        parent = ctx.read(ctx.PARENT_PATH)
        device = torch.device(parent["runtime"]["device"])
        torch.cuda.empty_cache()
        torch.cuda.set_per_process_memory_fraction(0.70, device)
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(1729)
        torch.cuda.manual_seed_all(1729)
        predictor = layout.matched.Predictor(parent, ctx.ARTIFACT, ctx.OLD_CODE)
        require(predictor.model_digest == protocol["parent_model_digest"], "parent")
        write(output / "ALLOCATOR.json", layout.allocator_admission(torch, device))
        model = predictor.model
        base = model.get_base_model()
        require(
            base.config._attn_implementation == "eager", "original inference engine"
        )
        for name, value in model.named_parameters():
            value.requires_grad_("lora_" in name)
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        model.enable_input_require_grads()
        model.train()
        require(float(base.config.attention_dropout) == 0.0, "nonzero dropout")
        parameters = [
            (name, value)
            for name, value in model.named_parameters()
            if value.requires_grad
        ]
        before = layout.numeric._parameter_hash(parameters, torch)
        require(
            before == protocol["parent_parameter_digest"], "actual parent parameters"
        )
        write(
            output / "MODEL_LOADED.json",
            {
                "actual_parent_model_digest": predictor.model_digest,
                "parameter_before": before,
                "at_ns": time.time_ns(),
                "wall_seconds_since_stage_entry": time.perf_counter() - started,
                "device": predictor.device_report,
                "optimizer_created": False,
                "training": model.training,
                "use_cache_for_every_call": False,
                "past_key_values_for_every_call": None,
                "model_config": {
                    key: getattr(base.config, key, None)
                    for key in (
                        "attention_dropout",
                        "sliding_window",
                        "use_sliding_window",
                        "layer_types",
                        "rope_theta",
                        "rope_scaling",
                        "num_attention_heads",
                        "num_key_value_heads",
                    )
                },
                "attention_layers": [
                    {
                        "name": name,
                        "is_causal": getattr(module, "is_causal", None),
                        "sliding_window": getattr(module, "sliding_window", None),
                    }
                    for name, module in base.named_modules()
                    if type(module).__name__ == "Qwen2Attention"
                ],
            },
        )
        for mode in layout.MODES:
            group = layout.encode_groups(
                predictor.tokenizer, [records[protocol["record_index"]]], 1024, mode
            )[0]
            require(len(group) == 1, "short complete target must fit one head chunk")
            row = group[0]
            padding = 1024 - len(row["input_ids"])
            require(padding >= 0, "short calibration must not truncate")
            ids = torch.tensor(
                [row["input_ids"] + [predictor.tokenizer.pad_token_id] * padding],
                device=device,
            )
            labels = torch.tensor([row["labels"] + [-100] * padding], device=device)
            mask = torch.tensor(
                [[1] * len(row["input_ids"]) + [0] * padding], device=device
            )
            positions = torch.nonzero(labels[0, 1:] != -100, as_tuple=False).flatten()
            require(int(positions.numel()) == 115, "frozen target size differs")
            require(not bool((mask[0, positions + 1] != 1).any()), "masked target")
            pair = {}
            for engine in protocol["engine_order"]:
                checkpoint_engine.TRACKER.reset()
                base.set_attn_implementation(engine)
                require(
                    base.config._attn_implementation == engine, "engine switch rejected"
                )
                require(
                    all(
                        module.config._attn_implementation == engine
                        for module in base.modules()
                        if type(module).__name__ == "Qwen2Attention"
                    ),
                    "attention modules disagree",
                )
                for _, value in parameters:
                    value.grad = None
                gc.collect()
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats(device)
                torch.manual_seed(1729)
                torch.cuda.manual_seed_all(1729)
                manager = contextlib.nullcontext()
                tick = time.perf_counter()
                event(
                    "forward_started", mode=mode, engine=engine, padded_positions=1024
                )
                with manager:
                    logits = model(
                        input_ids=ids,
                        attention_mask=mask,
                        use_cache=False,
                        past_key_values=None,
                        output_attentions=False,
                        logits_to_keep=positions,
                    ).logits
                    require(logits.shape[:2] == (1, 115), "causal selected logits")
                    loss = torch.nn.functional.cross_entropy(
                        logits[0].float(), labels[0, positions + 1]
                    )
                    require(
                        bool(torch.isfinite(logits).all())
                        and bool(torch.isfinite(loss)),
                        "finite output",
                    )
                    nodes = walk_nodes(loss.grad_fn)
                    fused = {
                        name: count
                        for name, count in nodes.items()
                        if "ScaledDotProduct" in name
                        and ("Flash" in name or "Efficient" in name)
                    }
                    require(not fused, "this candidate must retain eager attention")
                    event(
                        "forward_completed",
                        mode=mode,
                        engine=engine,
                        actual_backend_nodes=fused,
                    )
                    checkpoint_engine.TRACKER.phase = "backward"
                    event("backward_started", mode=mode, engine=engine)
                    loss.backward()
                    torch.cuda.synchronize(device)
                    event("backward_completed", mode=mode, engine=engine)
                gradients = {
                    name: value.grad.detach().cpu().clone()
                    for name, value in parameters
                    if value.grad is not None
                }
                require(
                    len(gradients) == len(parameters)
                    and all(
                        bool(torch.isfinite(value).all())
                        for value in gradients.values()
                    ),
                    "finite complete LoRA gradients required",
                )
                pair[engine] = {
                    "logits": logits.detach().cpu().clone(),
                    "gradients": gradients,
                    "loss": float(loss.detach()),
                }
                path = output / (mode + "-" + engine + ".pt")
                torch.save(pair[engine], path)
                measured = {
                    "mode": mode,
                    "engine": engine,
                    "input_tokens": len(row["input_ids"]),
                    "padded_positions": 1024,
                    "supervised_positions": 115,
                    "encoded_group_digest": ctx.data.digest(group),
                    "loss": pair[engine]["loss"],
                    "actual_backend_nodes": fused,
                    "inner_checkpoint_actual_counts": checkpoint_engine.TRACKER.snapshot(),
                    "per_parameter_gradient": {
                        name: {
                            "finite": bool(torch.isfinite(value).all()),
                            "zero_elements": int((value == 0).sum()),
                            "elements": value.numel(),
                            "l2": float(value.double().norm()),
                            "entirely_zero": bool((value == 0).all()),
                        }
                        for name, value in gradients.items()
                    },
                    "all_autograd_node_counts": nodes,
                    "raw_tensors_file": str(path),
                    "raw_tensors_sha256": sha(path),
                    "raw_tensors_bytes": path.stat().st_size,
                    "wall_seconds": time.perf_counter() - tick,
                    "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(
                        device
                    ),
                    "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                    "optimizer_updates": 0,
                }
                write(output / (mode + "-" + engine + ".json"), measured)
                saved.append(measured)
                del logits, loss
            measured = {
                "mode": mode,
                **compare(torch, pair["eager"], pair["eager_checkpointed_softmax"]),
            }
            tolerances = protocol["engineering_tolerances"]
            checks = {
                name: measured[name] <= value
                for name, value in tolerances["maximum"].items()
            }
            checks.update(
                {
                    name: measured[name] >= value
                    for name, value in tolerances["minimum"].items()
                }
            )
            measured["predeclared_checks"] = checks
            measured["passed"] = all(checks.values())
            comparisons.append(measured)
            write(output / (mode + "-COMPARISON.json"), measured)
            del pair, gradients, ids, labels, mask, positions
        after = layout.numeric._parameter_hash(parameters, torch)
        require(after == before, "calibration changed parameters")
        result = {
            "status": "PASS"
            if all(row["passed"] for row in comparisons)
            else "NUMERICAL_REJECT",
            "source_commit": deployment["source_commit"],
            "protocol_sha256": sha(PROTOCOL),
            "parameter_before": before,
            "parameter_after": after,
            "comparisons": comparisons,
            "actual_runs": saved,
            "model_forwards": sum(
                row["event"] == "forward_completed" for row in events
            ),
            "model_backwards": sum(
                row["event"] == "backward_completed" for row in events
            ),
            "optimizer_updates": 0,
            "model_generation_calls": 0,
            "wall_seconds": time.perf_counter() - started,
            "self_cpu_seconds": time.process_time() - cpu,
            "no_b3_material_read": True,
            "attention_kernel_work_matches_eager": False,
            "additional_inner_softmax_recomputation": True,
            "full_system_cost_known": False,
        }
        write(output / "RESULT.json", result)
        require(result["status"] == "PASS", "predeclared numerical limits failed")
    except BaseException as error:
        write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "events_completed": events,
                "optimizer_updates": 0,
                "model_generation_calls": 0,
                "automatic_retry": False,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


def own():
    protocol, deployment = admit()
    utilities = old_owner()
    owned = WORK / "owned-probe-1"
    owned.mkdir(exist_ok=False)
    samples = []

    def sample():
        measured = utilities.energy_sample()
        write(owned / ("ENERGY-" + str(len(samples)) + ".json"), measured)
        samples.append(measured)

    require(
        LOCK.is_file() and not LOCK.is_symlink(), "original shared GPU lock required"
    )
    with LOCK.open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write(
            owned / "INTENT.json",
            {
                "source_commit": deployment["source_commit"],
                "protocol_sha256": sha(PROTOCOL),
                "started_at_ns": time.time_ns(),
                "lock": str(LOCK),
                "automatic_retry": False,
                "max_model_forwards": 4,
                "max_model_backwards": 4,
                "optimizer_updates": 0,
                "generation_calls": 0,
            },
        )
        write(owned / "GPU_ADMISSION.json", utilities.gpu_admission())
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            not in (
                "PYTHONPATH",
                "PYTHONSTARTUP",
                "PYTHONHOME",
                "PYTORCH_ALLOC_CONF",
                "PYTORCH_CUDA_ALLOC_CONF",
            )
        }
        env.update(
            PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            HF_DATASETS_OFFLINE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
            TOKENIZERS_PARALLELISM="false",
            OMP_NUM_THREADS="2",
            OPENBLAS_NUM_THREADS="1",
        )
        sample()
        tick, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
        timed_out = False
        with (
            (owned / "STDOUT.txt").open("xb") as stdout,
            (owned / "STDERR.txt").open("xb") as stderr,
        ):
            process = subprocess.Popen(
                [PYTHON, "-B", str(Path(__file__).resolve()), "--child"],
                cwd=HERE,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            write(
                owned / "STARTED.json",
                {
                    "pid": process.pid,
                    "started_at_ns": time.time_ns(),
                    "timeout_seconds": 900,
                },
            )
            while True:
                try:
                    code = process.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    sample()
                    if time.perf_counter() - tick > 900:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            code = process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            code = process.wait(timeout=10)
                        break
        sample()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(
            owned / "EXIT.json",
            {
                "wait_returncode": code,
                "timed_out": timed_out,
                "finished_at_ns": time.time_ns(),
                "exit_source": "subprocess.Popen.wait",
                "wall_seconds": time.perf_counter() - tick,
                "child_cpu_seconds_including_energy_reads": after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
                "stdout_sha256": sha(owned / "STDOUT.txt"),
                "stderr_sha256": sha(owned / "STDERR.txt"),
                "whole_host_rapl_samples": len(samples),
                "whole_host_package_energy_not_model_only": True,
                "full_system_cost_known": False,
            },
        )
        require(code == 0 and not timed_out, "owned numerical calibration failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    child() if args.child else own()


if __name__ == "__main__":
    main()
