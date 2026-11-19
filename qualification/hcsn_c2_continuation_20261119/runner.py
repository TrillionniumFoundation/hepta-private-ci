"""Independent bounded C2 continuation using the unchanged original numerical helpers."""

import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import resource
import signal
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
THREADS = {key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")}


class BudgetStop(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def run(fit_name):
    started = float(os.environ["HCSN_PHASE_START"])
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        require(sha(HERE / name) == expected, "frozen continuation input " + name)
    request = json.loads((HERE / "REQUEST.json").read_text())
    bindings = json.loads((HERE / "BINDINGS.json").read_text())
    require(request["identity"] == freeze["identity"] == bindings["identity"], "new continuation identity")
    fit = next(row for row in request["fits"] if row["name"] == fit_name)
    bound = bindings["fits"][fit_name]
    limits = request["budget"]
    require(resource.getrlimit(resource.RLIMIT_AS) == (limits["address_space_bytes_per_fit"],) * 2,
            "address space must be bounded before numerical imports")
    require({key: os.environ.get(key) for key in THREADS} == THREADS, "single-thread environment")
    require(os.sched_getaffinity(0) == {int(os.environ["HCSN_ASSIGNED_CPU"])}, "one assigned logical CPU")
    require(not any(name in sys.modules for name in ("torch", "numpy")), "early numerical import")
    out = HERE / "RUN_OUTPUT" / fit_name
    out.mkdir()
    for name in ("updates", "checkpoints", "commits"):
        (out / name).mkdir()
    journal = (out / "events.jsonl").open("x")
    report = {"schema": "hcsn-c2-independent-continuation-result-v1", "identity": fit["new_identity"],
        "status": "STARTED", "scientific_admission": "HOLD", "full_six_fit_replay": False,
        "independent_complete_training_replays": 0, "original_controller_terminal": "UNKNOWN",
        "original_runtime_exact_replay": False, "old_c2_admission_reused": False,
        "old_posterior_recording_contract_completed": False, "confirmation_access": False,
        "new_optimizer_started": 0, "new_optimizer_completed": 0, "new_micro_forwards_started": 0,
        "optimizer_completions_after_scientific_deadline": 0,
        "development_forwards_started": 0, "epochs": [], "start_epoch": fit["epoch"],
        "last_complete_epoch": fit["epoch"], "logical_main_updates": fit["epoch"] * bound["steps_per_epoch"],
        "original_partial_work": request["original_partial_work"], "cold_probe_calls_separate": 4,
        "scientific_wall_budget_seconds": limits["scientific_wall_seconds_per_fit"],
        "finalization_reserve_seconds": limits["finalization_reserve_seconds"],
        "training_adequacy_established": False, "selected_development_complete": False,
        "energy_joules": None, "peak_vram_bytes": None,
        "unmeasured_cost_reason": "CPU continuation; no complete-system energy meter",
        "runtime": {}, "uncommitted_optimizer_call": False,
        "frozen_initial_comparison_verified": False,
        "deadline_overrun_scope": "May include an uninterruptible in-flight operation and Python finalization; no additional qualified training or validation budget."}
    model = optimizer = order_rng = cold = None
    last_update = last_epoch = best_path = None
    last_commit = copy.deepcopy(bound["last_commit"])
    stopping = copy.deepcopy(bound["stopping"])
    history = copy.deepcopy(bound["inherited_history"])
    cursor = None
    parameter_names = []
    all_inputs = dict(bindings["input_files"])

    def elapsed():
        return time.monotonic() - started

    def event(kind, **values):
        journal.write(json.dumps({"kind": kind, "new_phase_wall_seconds": elapsed(), **values}, allow_nan=False) + "\n")
        journal.flush()
        os.fsync(journal.fileno())

    def budget(*unused, finalizing=False):
        maximum = limits["scientific_wall_seconds_per_fit"]
        if not finalizing:
            maximum -= limits["finalization_reserve_seconds"]
        if elapsed() >= maximum:
            raise BudgetStop("scientific wall boundary reached" if finalizing else "training boundary reserved for finalization")
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 > limits["peak_rss_stop_bytes_per_fit"]:
            raise BudgetStop("peak RSS boundary reached")

    def terminated(signum, frame):
        stop = out / "STOP_REQUEST.json"
        reason = json.loads(stop.read_text()) if stop.is_file() else {"reason": "SIGTERM"}
        raise BudgetStop("controller stop: " + json.dumps(reason, sort_keys=True))

    signal.signal(signal.SIGTERM, terminated)

    def verify_inputs():
        for path, expected in all_inputs.items():
            require(sha(path) == expected["sha256"], "source or original input changed: " + path)

    def verify_frozen(initial):
        state = model.state_dict()
        require(all(torch.equal(state[name], initial["model"][name]) for name in parameter_names),
                "frozen common, physical or buffer tensor changed")

    def save(path, state):
        metadata = cold.save_state(path, state, torch)
        return {"path": str(path), **metadata}

    def evaluate(rows, *, retain=None, finalizing=False):
        model.eval()
        values, labels = [], []
        with torch.no_grad():
            for ids, x, dt, y in support.batches(rows, list(range(len(rows))), plan["batch_size"]):
                budget(finalizing=finalizing)
                report["development_forwards_started"] += 1
                logits = model(x, dt)
                values.append(logits[y >= 0])
                labels.append(y[y >= 0])
                budget(finalizing=finalizing)
        logits, labels = torch.cat(values), torch.cat(labels)
        result = study.metrics(logits, labels)
        result["brier_mean_classes"] = result["brier_half_sum"] * (2 / 11)
        require(result["events"] == 31952, "complete original development population")
        budget(finalizing=finalizing)
        if retain is not None:
            report["selected_development_logits"] = save(retain, {"logits": logits, "labels": labels,
                "episode_ids": [row["id"] for row in rows]})
        return result

    try:
        budget()
        verify_inputs()
        cold = module("hcsn_c2_frozen_cold_helpers", Path(request["cold_probe_root"]) / "runner.py")
        import numpy as np
        import torch

        require(platform.python_version() == request["runtime"]["python"]
                and torch.__version__ == request["runtime"]["torch"]
                and np.__version__ == request["runtime"]["numpy"], "new CPU runtime identity")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        report["runtime"] = {"python": platform.python_version(), "torch": torch.__version__,
            "torch_git": torch.version.git_version, "numpy": np.__version__, "executable": sys.executable,
            "resolved_executable_sha256": sha(Path(sys.executable).resolve()), "platform": platform.platform(),
            "affinity": sorted(os.sched_getaffinity(0)), "torch_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads()}
        cores, support, capacity, plan, data, state, native, expectations = cold.original_context(request, fit, torch)
        source = Path(request["original_root"]) / request["source_relative"]
        for name, expected in expectations["source_files"].items():
            all_inputs[str(source / name)] = {"sha256": expected}
        prepared = Path(plan["prepared"])
        manifest_path = prepared / "data-manifest.json"
        all_inputs[str(manifest_path)] = {"sha256": request["manifest_sha256"]}
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["episodes"]:
            all_inputs[str(prepared / entry["path"])] = {"sha256": entry["sha256"]}
        study = module("hcsn_original_v8_training_helpers", source / "proposals/localization-v3/train.py")
        require(Path(study.__file__).resolve() == source / "proposals/localization-v3/train.py", "original metric and aggregation source")
        boundary = module("hcsn_c2_original_stopping", Path(request["original_c2_program"]) / "c2_boundary.py")
        require(boundary.plateau_state(history, plan["plateau_delta"]) == stopping,
                "original stopping helper agrees with complete inherited history")
        require(boundary.first_plateau_epoch(history, plan["plateau_delta"], plan["min_epochs"], plan["patience"]) is None,
                "no earlier inherited stopping event")
        initial = torch.load(bound["initial_checkpoint"], weights_only=True, map_location="cpu")
        require(initial["model_configuration"] == state["model_configuration"], "exact original initial configuration")
        model = cores.CoreStudyModel(**state["model_configuration"])
        model.load_state_dict(state["model"], strict=True)
        parameter_names = sorted({name for name, parameter in model.named_parameters() if not parameter.requires_grad}
                                 | {name for name, _ in model.named_buffers()})
        verify_frozen(initial)
        report["frozen_initial_comparison_verified"] = True
        optimizer, _ = capacity.adamw(model, plan["learning_rate"], 0.0)
        optimizer.load_state_dict(copy.deepcopy(state["optimizer"]))
        order_rng = random.Random()
        order_rng.setstate(state["order_rng"])
        torch.set_rng_state(state["torch_rng"])
        restored = cold.snapshot(model, optimizer, order_rng, fit["epoch"], state["main_updates"], request["manifest_sha256"], torch)
        require(cold.semantic(restored, torch) == cold.semantic(state, torch), "complete restored model/AdamW/RNG/schema")
        require(all(float(row["step"]) == state["main_updates"] for row in optimizer.state_dict()["state"].values()),
                "original AdamW update age")
        last_update = last_epoch = save(out / "RESUME_START.pt", restored)
        reloaded = torch.load(last_epoch["path"], weights_only=True, map_location="cpu")
        require(cold.semantic(reloaded, torch) == cold.semantic(state, torch), "durable complete restore roundtrip")
        with (out / "INHERITED_BEST.pt").open("xb") as stream:
            stream.write(Path(bound["best_checkpoint"]).read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        best_path = out / "INHERITED_BEST.pt"
        require(sha(best_path) == fit["best_checkpoint_sha256"], "exact strict-best bytes")
        write(out / "RESUME_WITNESS.json", {"source_checkpoint_sha256": fit["checkpoint_sha256"],
            "restored": last_epoch, "full_state_equal": True, "frozen_tensors_match_original_initial": True,
            "initial_source": bound["initial_checkpoint"], "initial_original_path_missing": not bound["original_initial_path_exists"],
            "stopping": stopping, "source_files_verified": len(expectations["source_files"]),
            "new_optimizer_completed": 0, "new_phase_wall_seconds": elapsed()})
        write(out / "INPUT_IDENTITIES.json", all_inputs)
        event("restore_verified", checkpoint=last_epoch, stopping=stopping)
        model.load_state_dict(torch.load(best_path, weights_only=True, map_location="cpu")["model"], strict=True)
        observed_best = evaluate(data["dev"])
        reference_best = bound["best_development"]
        require(observed_best["confusion_matrix"] == reference_best["confusion_matrix"]
                and observed_best["macro_f1_11_classes"] == reference_best["macro_f1_11_classes"],
                "fresh inherited-best classification metrics differ")
        write(out / "INHERITED_BEST_VALIDATION.json", {"fresh_development": observed_best,
            "original_development": reference_best,
            "scalar_absolute_differences": {key: abs(value - reference_best[key]) for key, value in observed_best.items()
                                            if isinstance(value, (int, float))},
            "original_logits_available_for_bitwise_comparison": False})
        model.load_state_dict(state["model"], strict=True)
        torch.set_rng_state(state["torch_rng"])
        order_rng.setstate(state["order_rng"])
        require(cold.semantic(cold.snapshot(model, optimizer, order_rng, fit["epoch"], state["main_updates"],
                request["manifest_sha256"], torch), torch) == cold.semantic(state, torch),
                "restore still exact after inherited-best validation")
        targets = [label for row in data["train"] for label in row["y"]]
        require(sorted(set(targets)) == list(range(11)) and len(targets) == 89216, "complete original training support")
        weights = torch.bincount(torch.tensor(targets), minlength=11).double().rsqrt()
        weights /= weights.mean()
        for epoch in range(fit["epoch"] + 1, request["maximum_cumulative_epochs"] + 1):
            budget()
            order = list(range(len(data["train"])))
            order_rng.shuffle(order)
            episode_order = [data["train"][index]["id"] for index in order]
            event("epoch_started", epoch=epoch, episode_order=episode_order)
            losses = []
            cursor = {"schema": "hcsn-c2-mid-epoch-continuation-v2", "current_epoch": epoch,
                "episode_indices": order, "episode_ids": episode_order, "next_episode_offset": 0,
                "completed_effective_batches": 0, "completed_batch_objectives": [],
                "batch_size": plan["batch_size"], "micro_batch_size": plan["micro_batch_size"], "complete_epoch": False}
            for batch_index, (ids, x, dt, y) in enumerate(support.batches(data["train"], order, plan["batch_size"])):
                budget()
                model.train()
                optimizer.zero_grad(set_to_none=True)
                event("update_started", epoch=epoch, batch_index=batch_index, episode_ids=ids,
                      logical_next_update=report["logical_main_updates"] + 1)

                def before_forward(start, end):
                    budget()
                    report["new_micro_forwards_started"] += 1
                    event("micro_forward_started", epoch=epoch, batch_index=batch_index, start=start, end=end)

                value = support.backward_effective_batch(model, x, dt, y, weights,
                    micro_batch_size=plan["micro_batch_size"], before_forward=before_forward)
                value["target_weight_sum"] = float(weights[y[y >= 0]].sum())
                value["weighted_loss_numerator"] = value["loss"] * value["target_weight_sum"]
                active = [parameter for parameter in model.parameters() if parameter.requires_grad]
                require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in active),
                        "all connected finite gradients")
                norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
                require(bool(torch.isfinite(norm)), "finite gradient norm")
                budget()
                report["new_optimizer_started"] += 1
                report["uncommitted_optimizer_call"] = True
                event("optimizer_started", logical_next_update=report["logical_main_updates"] + 1)
                optimizer.step()
                report["logical_main_updates"] += 1
                report["new_optimizer_completed"] += 1
                report["uncommitted_optimizer_call"] = False
                completed_elapsed = elapsed()
                within_scientific_budget = completed_elapsed <= limits["scientific_wall_seconds_per_fit"]
                report["optimizer_completions_after_scientific_deadline"] += int(not within_scientific_budget)
                event("optimizer_completed", number=report["logical_main_updates"],
                      new_number=report["new_optimizer_completed"], epoch=epoch, batch_index=batch_index,
                      optimizer_return_elapsed_seconds=completed_elapsed,
                      within_scientific_budget=within_scientific_budget,
                      gradient_norm=float(norm), **value)
                require(all(float(item["step"]) == report["logical_main_updates"]
                            for item in optimizer.state_dict()["state"].values()), "actual AdamW update age")
                verify_frozen(initial)
                losses.append(value)
                cursor.update(next_episode_offset=min((batch_index + 1) * plan["batch_size"], len(order)),
                              completed_effective_batches=batch_index + 1, completed_batch_objectives=losses)
                update_state = cold.snapshot(model, optimizer, order_rng, report["last_complete_epoch"],
                    report["logical_main_updates"], request["manifest_sha256"], torch)
                update_state["continuation_cursor"] = copy.deepcopy(cursor)
                last_update = save(out / "updates" / f"update-{report['logical_main_updates']:08d}.pt", update_state)
                last_update["within_scientific_budget"] = within_scientific_budget
                event("optimizer_checkpoint_committed", checkpoint=last_update, number=report["logical_main_updates"])
                if not within_scientific_budget:
                    raise BudgetStop("in-flight optimizer completed after the scientific deadline")
            development = evaluate(data["dev"])
            budget()
            verify_inputs()
            verify_frozen(initial)
            row = {"epoch": epoch, "complete": True, "events": sum(value["events"] for value in losses),
                "training_weighted_loss": study.aggregate_training_objectives(losses),
                "training_target_weight_sum": sum(value["target_weight_sum"] for value in losses),
                "training_weighted_loss_numerator": sum(value["weighted_loss_numerator"] for value in losses),
                "development": development, "new_phase_wall_seconds": elapsed(), "new_phase_cpu_seconds": time.process_time()}
            require(row["events"] == 89216 and len(losses) == bound["steps_per_epoch"], "complete original training epoch")
            next_stopping = boundary.plateau_state(history + [row], plan["plateau_delta"])
            checkpoint = save(out / "checkpoints" / f"epoch-{epoch:04d}.pt", cold.snapshot(model, optimizer,
                order_rng, epoch, report["logical_main_updates"], request["manifest_sha256"], torch))
            candidate_best = Path(checkpoint["path"]) if next_stopping["best_epoch"] == epoch else best_path
            commit = {"schema": "hcsn-c2-independent-complete-epoch-commit-v1", "identity": fit["new_identity"],
                "epoch": row, "checkpoint": checkpoint, "best_checkpoint": {"path": str(candidate_best),
                    "bytes": candidate_best.stat().st_size, "sha256": sha(candidate_best)},
                "stopping": next_stopping, "previous_commit": last_commit, "logical_main_updates": report["logical_main_updates"]}
            last_commit = write(out / "commits" / f"epoch-{epoch:04d}.json", commit)
            history.append(row)
            report["epochs"].append(row)
            report["last_complete_epoch"] = epoch
            last_epoch, last_update, best_path, stopping = checkpoint, checkpoint, candidate_best, next_stopping
            cursor = None
            event("epoch_completed", **row, commit=last_commit)
            if epoch >= plan["min_epochs"] and stopping["stale_epochs"] >= plan["patience"]:
                report.update(status="COMPLETED_PLATEAU", stop_reason="development_plateau")
                break
        else:
            report.update(status="EPOCH_CAP", stop_reason="maximum_epoch_cap_not_convergence")
    except BudgetStop as error:
        report.update(status="BUDGET_STOP", stop_reason=str(error))
        event("budget_stop", reason=str(error))
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        event("failed", error_type=type(error).__name__, error=str(error))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        report["training_end_new_phase_wall_seconds"] = elapsed()
        report["stopping"] = stopping
        report["last_complete_epoch_checkpoint"] = last_epoch
        report["last_complete_optimizer_checkpoint"] = last_update
        report["last_commit"] = last_commit
        report["live_partial_epoch_cursor"] = cursor
        report["open_optimizer_completion_interval"] = [0, 1] if report["uncommitted_optimizer_call"] else [0, 0]
        if model is not None and best_path is not None and report["status"] != "FAILED":
            report["selected_best_checkpoint"] = {"path": str(best_path), "sha256": sha(best_path), "epoch": stopping["best_epoch"]}
            try:
                budget(finalizing=True)
                model.load_state_dict(torch.load(best_path, weights_only=True, map_location="cpu")["model"], strict=True)
                report["selected_development"] = evaluate(data["dev"], retain=out / "DEVELOPMENT_LOGITS.pt", finalizing=True)
                report["selected_development_complete"] = True
            except BudgetStop as error:
                report["finalization_status"] = "BUDGET_STOP_INCOMPLETE"
                report["finalization_error"] = str(error)
            except BaseException as error:
                report.update(status="FAILED", finalization_error=str(error), finalization_traceback=traceback.format_exc())
        try:
            verify_inputs()
            report["all_bound_inputs_unchanged"] = True
            if model is not None and report["frozen_initial_comparison_verified"]:
                verify_frozen(initial)
                report["frozen_initial_tensors_unchanged"] = True
                report["frozen_table_cache"] = [layer.operator.cache_receipt() for layer in model.core.network.layers]
        except BaseException as error:
            report.update(status="FAILED", integrity_error=str(error), integrity_traceback=traceback.format_exc())
        report["training_adequacy_established"] = bool(report["status"] == "COMPLETED_PLATEAU"
            and report["selected_development_complete"] and bound["inherited_memorization"]["passed"])
        report["scientifically_in_budget_optimizer_completions"] = (report["new_optimizer_completed"]
            - report["optimizer_completions_after_scientific_deadline"])
        report["new_phase_wall_seconds_before_exit"] = elapsed()
        report["new_phase_cpu_seconds_before_exit"] = time.process_time()
        report["peak_rss_bytes_before_exit"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        report["cleanup_overrun_seconds_before_exit"] = max(0.0, elapsed() - limits["scientific_wall_seconds_per_fit"])
        event("finished", status=report["status"], new_optimizer_completed=report["new_optimizer_completed"])
        journal.close()
        report["events_sha256"] = sha(out / "events.jsonl")
        write(out / "RESULT.json", report)
    return 2 if report["status"] == "FAILED" else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.fit))
