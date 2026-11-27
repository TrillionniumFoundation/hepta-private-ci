"""Four bounded real-batch cold resumes, preserving the original C2 UNKNOWN."""

import argparse
import copy
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import resource
import signal
import subprocess
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
THREADS = {name: "1" for name in (
    "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"
)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def frozen_inputs():
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        require(sha(HERE / name) == expected, "new probe source identity: " + name)
    request = json.loads((HERE / "REQUEST.json").read_text())
    require(request["identity"] == freeze["identity"], "new diagnostic identity")
    require(request["confirmation_access"] is False, "sealed confirmation access")
    return request


def semantic(value, torch):
    digest = hashlib.sha256()

    def add(item):
        if isinstance(item, torch.Tensor):
            tensor = item.detach().cpu().contiguous()
            digest.update(f"tensor:{tensor.dtype}:{tuple(tensor.shape)}:".encode())
            digest.update(tensor.numpy().tobytes())
        elif isinstance(item, dict):
            digest.update(b"mapping:")
            for key in sorted(item, key=lambda x: (type(x).__name__, repr(x))):
                add(key)
                add(item[key])
            digest.update(b"endmapping")
        elif isinstance(item, (list, tuple)):
            digest.update(f"{type(item).__name__}:{len(item)}:".encode())
            for child in item:
                add(child)
        else:
            digest.update(f"{type(item).__name__}:{item!r};".encode())

    add(value)
    return digest.hexdigest()


def snapshot(model, optimizer, order_rng, epoch, updates, data_sha, torch):
    return {"model": model.state_dict(), "model_configuration": model.construction_configuration,
            "optimizer": optimizer.state_dict(), "torch_rng": torch.get_rng_state(),
            "order_rng": order_rng.getstate(), "epochs_completed": epoch,
            "main_updates": updates, "data_manifest_sha256": data_sha}


def save_state(path, state, torch):
    with path.open("xb") as stream:
        torch.save(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    return {"bytes": path.stat().st_size, "sha256": sha(path),
            "semantic_sha256": semantic(state, torch)}


def original_context(request, fit, torch):
    root = Path(request["original_root"])
    source = root / request["source_relative"]
    expectations = json.loads((HERE / "SOURCE_EXPECTATIONS.json").read_text())
    for name, expected in expectations["source_files"].items():
        require(sha(source / name) == expected, "original repository source: " + name)
    parent = root / "campaign-v2" / fit["name"]
    prior = json.loads((parent / "result.json").read_text())
    plan_path = parent / "plan.json"
    require(sha(plan_path) == prior["plan_sha256"], "original plan digest")
    plan = json.loads(plan_path.read_text())
    require(plan["manifest_sha256"] == request["manifest_sha256"], "original data identity")
    require(plan["threads"] == 1, "original single-thread plan")
    directory = source / "proposals/localization-v3"
    sys.path.insert(0, str(directory))
    cores = importlib.import_module("cores")
    support = importlib.import_module("hcsn_study_support")
    capacity = importlib.import_module("capacity")
    episodes = importlib.import_module("episodes")
    require(Path(cores.__file__).resolve() == directory / "cores.py", "core source origin")
    require(Path(support.__file__).resolve() == directory / "hcsn_study_support.py",
            "batch and backward source origin")
    require(Path(capacity.__file__).resolve() == source / "proposals/localization-v2/capacity.py"
            and Path(episodes.__file__).resolve() == source / "proposals/localization-v2/episodes.py",
            "optimizer and data-reader source origin")
    data, _, manifest = episodes.read_episodes(plan["prepared"], plan["manifest_sha256"])
    require(manifest["mode"] == "all-development" and manifest.get("confirmation_access") is False,
            "original sealed train/development population")
    prepared = Path(plan["prepared"]).resolve()
    for entry in manifest["episodes"]:
        path = (prepared / entry["path"]).resolve()
        require(entry["partition"] in ("train", "dev") and path.is_relative_to(prepared),
                "original episode scope")
        require(sha(path) == entry["sha256"], "original episode digest")
    require(len(data["train"]) == prior["episodes_train"]
            and sum(len(row["y"]) for row in data["train"]) == prior["train_events"]
            and sum(len(row["y"]) for row in data["dev"]) == prior["dev_events"],
            "original population denominator")
    native = root / "c2-native-execution-20261110-c385-v1" / "fits" / fit["name"]
    commit_path = native / "commits" / f"epoch-{fit['epoch']:04d}.json"
    require(sha(commit_path) == fit["commit_sha256"], "original epoch commit digest")
    commit = json.loads(commit_path.read_text())
    checkpoint = Path(commit["checkpoint_path"])
    require(sha(checkpoint) == fit["checkpoint_sha256"] == commit["checkpoint"]["sha256"],
            "surviving checkpoint digest")
    state = torch.load(checkpoint, weights_only=True, map_location="cpu")
    require(state["epochs_completed"] == fit["epoch"]
            and state["main_updates"] == commit["logical_main_updates"]
            and state["data_manifest_sha256"] == request["manifest_sha256"],
            "original checkpoint semantic identity")
    return cores, support, capacity, plan, data, state, native, expectations


def child(fit_name, replica):
    started = time.monotonic()
    request = frozen_inputs()
    budget = request["budget"]
    require(resource.getrlimit(resource.RLIMIT_AS) == (budget["child_address_space_bytes"],) * 2,
            "address-space limit before numerical imports")
    require({name: os.environ.get(name) for name in THREADS} == THREADS, "thread environment")
    require(not any(name in sys.modules for name in ("torch", "numpy")), "early numerical import")
    fit = next(row for row in request["fits"] if row["name"] == fit_name)
    output = HERE / "RUN_OUTPUT" / f"{fit_name}-replica{replica}"
    output.mkdir()
    counts = {"optimizer_started": 0, "optimizer_completed": 0, "micro_forwards_started": 0}
    journal = (output / "events.jsonl").open("x")

    def event(kind, **values):
        journal.write(json.dumps({"kind": kind, "wall_seconds": time.monotonic() - started,
                                  **values}, allow_nan=False) + "\n")
        journal.flush()
        os.fsync(journal.fileno())

    def check_budget(*unused):
        require(time.monotonic() - started < budget["child_timeout_seconds"], "child elapsed budget")
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                <= budget["child_peak_rss_stop_bytes"], "child RSS budget")

    try:
        import numpy as np
        import torch

        require(platform.python_version() == request["runtime"]["python"]
                and torch.__version__ == request["runtime"]["torch"]
                and np.__version__ == request["runtime"]["numpy"], "new CPU runtime identity")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        cores, support, capacity, plan, data, state, native, expectations = original_context(request, fit, torch)
        check_budget()
        model = cores.CoreStudyModel(**state["model_configuration"])
        model.load_state_dict(state["model"], strict=True)
        optimizer, _ = capacity.adamw(model, plan["learning_rate"], 0.0)
        optimizer.load_state_dict(copy.deepcopy(state["optimizer"]))
        order_rng = random.Random()
        order_rng.setstate(state["order_rng"])
        torch.set_rng_state(state["torch_rng"])
        restored = snapshot(model, optimizer, order_rng, fit["epoch"], state["main_updates"],
                            request["manifest_sha256"], torch)
        require(semantic(restored, torch) == semantic(state, torch), "full restored model/optimizer/RNG")
        before = save_state(output / "RESTORED.pt", restored, torch)
        reloaded = torch.load(output / "RESTORED.pt", weights_only=True, map_location="cpu")
        require(semantic(reloaded, torch) == before["semantic_sha256"], "serialized restore roundtrip")
        event("restore_verified", checkpoint_sha256=fit["checkpoint_sha256"], **before)
        order = list(range(len(data["train"])))
        order_rng.shuffle(order)
        ids, x, dt, y = next(support.batches(data["train"], order, plan["batch_size"]))
        target = None
        previous_ids = None
        for line in (native / "events.jsonl").read_bytes().splitlines():
            try:
                observed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if observed["kind"] == "update_started":
                previous_ids = observed["episode_ids"]
            if observed["kind"] == "optimizer_completed" and observed["number"] == state["main_updates"] + 1:
                target = observed
                require(previous_ids == ids, "recovered batch differs from surviving original journal")
                break
        require(target is not None, "original next-update evidence")
        labels = [label for row in data["train"] for label in row["y"]]
        weights = torch.bincount(torch.tensor(labels), minlength=11).double().rsqrt()
        weights /= weights.mean()
        model.train()
        optimizer.zero_grad(set_to_none=True)
        initial_parameters = {name: value.detach().clone() for name, value in model.named_parameters()}
        frozen_names = {name for name, value in model.named_parameters() if not value.requires_grad}
        frozen_names.update(name for name, _ in model.named_buffers())
        frozen_before = {name: model.state_dict()[name].clone() for name in frozen_names}

        def before_forward(*unused):
            check_budget()
            counts["micro_forwards_started"] += 1

        event("batch_started", episode_ids=ids, logical_next_update=state["main_updates"] + 1)
        batch = support.backward_effective_batch(model, x, dt, y, weights,
            micro_batch_size=plan["micro_batch_size"], before_forward=before_forward)
        active = [parameter for parameter in model.parameters() if parameter.requires_grad]
        require(all(value.grad is not None and bool(torch.isfinite(value.grad).all()) for value in active),
                "connected finite gradients")
        gradient_before_clip = semantic([value.grad for value in active], torch)
        norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
        require(bool(torch.isfinite(norm)), "finite gradient norm")
        gradient_after_clip = semantic([value.grad for value in active], torch)
        before_steps = [float(value["step"]) for value in optimizer.state_dict()["state"].values()]
        check_budget()
        counts["optimizer_started"] += 1
        event("optimizer_started")
        optimizer.step()
        counts["optimizer_completed"] += 1
        event("optimizer_completed")
        after_steps = [float(value["step"]) for value in optimizer.state_dict()["state"].values()]
        require(len(before_steps) == len(after_steps)
                and all(after == before_step + 1 for before_step, after in zip(before_steps, after_steps)),
                "AdamW step increment")
        require(all(torch.equal(model.state_dict()[name], value) for name, value in frozen_before.items()),
                "frozen physical/shared state")
        changes = {name: float((value.detach() - initial_parameters[name]).abs().max())
                   for name, value in model.named_parameters() if value.requires_grad}
        require(any(value > 0 for value in changes.values()), "actual nonzero parameter update")
        after_state = snapshot(model, optimizer, order_rng, fit["epoch"], state["main_updates"] + 1,
                               request["manifest_sha256"], torch)
        after_state["continuation_cursor"] = {
            "schema": "hcsn-c2-mid-epoch-cursor-v1", "current_epoch": fit["epoch"] + 1,
            "episode_indices": order, "episode_ids": [data["train"][index]["id"] for index in order],
            "completed_effective_batches": 1, "next_episode_offset": len(ids),
            "batch_size": plan["batch_size"], "micro_batch_size": plan["micro_batch_size"],
            "complete_epoch": False,
        }
        after = save_state(output / "AFTER_UPDATE.pt", after_state, torch)
        metrics = {"loss": batch["loss"], "events": batch["events"],
                   "micro_forward_calls": batch["micro_forward_calls"], "gradient_norm": float(norm)}
        result = {"identity": request["identity"], "fit": fit_name, "replica": replica,
            "status": "ONE_REAL_BATCH_COMPLETED", "counts": counts, "episode_ids": ids,
            "start_epoch": fit["epoch"], "logical_next_update": state["main_updates"] + 1,
            "restored_checkpoint": before, "after_update_checkpoint": after,
            "gradient_before_clip_sha256": gradient_before_clip,
            "gradient_after_clip_sha256": gradient_after_clip,
            "optimizer_steps_before": before_steps, "optimizer_steps_after": after_steps,
            "metrics": metrics, "original_metrics": {key: target[key] for key in metrics},
            "original_metric_absolute_differences": {key: abs(value - target[key]) for key, value in metrics.items()},
            "trainable_parameter_max_abs_changes": changes, "frozen_state_unchanged": True,
            "full_state_restore_exact": True, "source_files_verified": len(expectations["source_files"]),
            "data_manifest_sha256": request["manifest_sha256"], "train_events": len(labels),
            "runtime": {"python": platform.python_version(), "executable": sys.executable,
                        "resolved_executable_sha256": sha(Path(sys.executable).resolve()),
                        "torch": torch.__version__, "torch_git": torch.version.git_version,
                        "numpy": np.__version__, "platform": platform.platform(),
                        "package_records": {name: {"version": importlib.metadata.version(name),
                            "record_sha256": hashlib.sha256(importlib.metadata.distribution(name).read_text(
                                "RECORD").encode()).hexdigest()} for name in ("torch", "numpy", "mpmath", "einops")}},
            "original_runtime_exact_replay": False, "full_six_fit_replay": False,
            "after_update_contains_explicit_mid_epoch_cursor": True,
            "original_controller_terminal": "UNKNOWN", "scientific_admission": "HOLD"}
        write(output / "RESULT.json", result)
    except BaseException as error:
        event("failed", error_type=type(error).__name__, error=str(error))
        write(output / "FAILURE.json", {"status": "FAILED", "counts": counts,
            "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        journal.close()


def main():
    request = frozen_inputs()
    budget = request["budget"]
    output = HERE / "RUN_OUTPUT"
    output.mkdir()
    started = time.monotonic()
    attempts = []

    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (budget["child_address_space_bytes"],) * 2)
        os.setsid()

    for fit in request["fits"]:
        for replica in range(1, budget["replicas_per_fit"] + 1):
            require(time.monotonic() - started < budget["parent_timeout_seconds"], "parent time budget")
            name = f"{fit['name']}-replica{replica}"
            wall = time.monotonic()
            with (output / (name + ".stdout")).open("x") as stdout, (output / (name + ".stderr")).open("x") as stderr:
                process = subprocess.Popen([sys.executable, str(Path(__file__)), "--child", fit["name"],
                                            "--replica", str(replica)], stdout=stdout, stderr=stderr,
                    env={**os.environ, **THREADS, "PYTHONDONTWRITEBYTECODE": "1"}, preexec_fn=limit)
                timed_out = False
                while True:
                    pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        break
                    if time.monotonic() - wall > budget["child_timeout_seconds"]:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGKILL)
                        _, status, usage = os.wait4(process.pid, 0)
                        break
                    time.sleep(0.1)
                process.returncode = os.waitstatus_to_exitcode(status)
            cost = {"name": name, "pid": process.pid, "returncode": process.returncode,
                    "timed_out": timed_out, "wall_seconds": time.monotonic() - wall,
                    "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
                    "peak_rss_bytes": usage.ru_maxrss * 1024,
                    "scope": "exact per-PID wait4 through process exit"}
            write(output / (name + ".COST.json"), cost)
            attempts.append(cost)
            if process.returncode or timed_out:
                write(output / "TERMINAL.json", {"status": "FAILED", "attempts": attempts,
                    "expected_children": 4, "unstarted_children": 4 - len(attempts),
                    "original_controller_terminal": "UNKNOWN", "full_six_fit_replay": False})
                return 2
    comparisons = []
    for fit in request["fits"]:
        first, second = [json.loads((output / f"{fit['name']}-replica{i}" / "RESULT.json").read_text())
                         for i in (1, 2)]
        fields = ("episode_ids", "gradient_before_clip_sha256", "gradient_after_clip_sha256",
                  "metrics", "optimizer_steps_before", "optimizer_steps_after")
        equal = all(first[key] == second[key] for key in fields)
        equal = equal and all(first[key]["semantic_sha256"] == second[key]["semantic_sha256"]
                              for key in ("restored_checkpoint", "after_update_checkpoint"))
        comparisons.append({"fit": fit["name"], "cold_repeats_bitwise_semantically_equal": equal})
    write(output / "TERMINAL.json", {"status": "COMPLETED" if all(row["cold_repeats_bitwise_semantically_equal"]
        for row in comparisons) else "REPEAT_MISMATCH", "identity": request["identity"],
        "attempts": attempts, "cold_repeat_comparisons": comparisons, "optimizer_calls_completed": 4,
        "independent_complete_training_replays": 0, "full_six_fit_replay": False,
        "original_runtime_exact_replay": False, "original_controller_terminal": "UNKNOWN",
        "scientific_admission": "HOLD"})
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child")
    parser.add_argument("--replica", type=int)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.replica)
    else:
        raise SystemExit(main())
