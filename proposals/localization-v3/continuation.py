"""Explicit continuation from a completed v8 epoch-cap checkpoint.

The original run is immutable. This separately costed phase restores the last
complete epoch, including optimizer and RNG state. It cannot recover a partial
batch, change a learning rate, refresh the diagnostic, or grant numerical scope.
"""

# ruff: noqa: E402
# Capture the standalone clock before heavy imports; native controllers supply
# the earlier process-dispatch timestamp, which includes interpreter startup.
import os
import time

PROCESS_STARTED = float(os.environ.get("HCSN_PROCESS_STARTED", time.monotonic()))

import argparse
import json
from pathlib import Path
import random
import shutil
import traceback

import torch
from cores import CoreStudyModel, tensor_digest
from capacity import adamw
from data import save, sha
from episodes import read_episodes
from hcsn_study_support import sources, batches, backward_effective_batch
from continuation_state import load_parent, source_equivalence, plateau_state  # noqa: F401 - public audit API
import importlib.util

# Upstream S4 and the previous study also have train.py; bind this exact sibling.
_train_spec = importlib.util.spec_from_file_location(
    "hcsn_v8_training_for_continuation", Path(__file__).with_name("train.py")
)
_train_module = importlib.util.module_from_spec(_train_spec)
_train_spec.loader.exec_module(_train_module)
aggregate_training_objectives = _train_module.aggregate_training_objectives
peak_rss = _train_module.peak_rss
metrics = _train_module.metrics


def continue_fit(args):
    parent, outer, prior, plan, state, inherited = load_parent(
        args.parent_dir, args.parent_outer_record
    )
    if (
        not len(prior["epochs"]) < args.max_epochs <= 400
        or args.total_wall_seconds != outer["hard_wall_seconds"]
        or args.total_wall_seconds <= outer["whole_process_wall_seconds"] + 30
    ):
        raise ValueError("continuation must use the original total wall envelope")
    data, _, manifest = read_episodes(plan["prepared"], plan["manifest_sha256"])
    if (
        manifest["mode"] != "all-development"
        or manifest["frontend_sha256"] != prior["frontend_sha256"]
    ):
        raise ValueError("data preparation or frontend differs from original attempt")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(plan["threads"])
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    report = {
        "schema": "hcsn-epoch-cap-continuation-v1",
        "status": "started",
        "scientific_admission": "HOLD",
        "numerical_admission": "not_extended_by_continuation",
        "formal_fits_started": 0,
        "confirmation_access": False,
        "parent": str(parent),
        "parent_report_sha256": outer["result_sha256"],
        "parent_outer_record_sha256": sha(Path(args.parent_outer_record).read_bytes()),
        "parent_source_sha256": prior["source_before"],
        "parent_complete_epochs": len(prior["epochs"]),
        "parent_whole_process_wall_seconds": outer["whole_process_wall_seconds"],
        "parent_recorded_fit_cpu_seconds": prior["cpu_seconds"],
        "parent_full_process_cpu_seconds": None,
        "cpu_scope": "Parent final CPU excludes imports; new-phase full CPU is separately measured. No exact cumulative full CPU is imputed.",
        "arm": prior["arm"],
        "seed": prior["seed"],
        "epochs": [],
        "main_updates": prior["main_updates"],
        "cumulative_epochs_completed": len(prior["epochs"]),
        "training_adequacy_established": False,
        "memorization": prior.get("memorization", {}),
        "energy_joules": None,
        "peak_vram_bytes": None,
        "source_before": sources(),
        "quality_threshold_macro_f1": plan["quality_threshold"],
        "first_observed_quality_crossing_cumulative_wall_seconds": prior.get(
            "process_time_to_quality_seconds"
        ),
    }
    report["plan_sha256"] = save(
        out / "plan.json",
        {
            "parent_plan": plan,
            "parent_outer_record": outer,
            "max_epochs": args.max_epochs,
            "total_wall_seconds": args.total_wall_seconds,
            "new_learning_rate_or_diagnostic": False,
            "resume_boundary": "complete epoch only; new process and cold-cache cost charged",
        },
    )
    model = optimizer = None
    order_rng = random.Random()
    journal = (out / "events.jsonl").open("x")

    def elapsed():
        return time.monotonic() - PROCESS_STARTED

    def event(kind, **values):
        journal.write(
            json.dumps(
                {"kind": kind, "phase_process_wall_seconds": elapsed(), **values},
                allow_nan=False,
            )
            + "\n"
        )
        journal.flush()

    def budget(*unused):
        if (
            outer["whole_process_wall_seconds"] + elapsed()
            > args.total_wall_seconds - 15
            or peak_rss() > plan["rss_bytes"]
        ):
            raise TimeoutError(
                "original total resource budget exhausted; not convergence"
            )

    def snapshot(name):
        temp = out / (name + ".tmp")
        torch.save(
            {
                "model": model.state_dict(),
                "model_configuration": model.construction_configuration,
                "optimizer": optimizer.state_dict(),
                "torch_rng": torch.get_rng_state(),
                "order_rng": order_rng.getstate(),
                "epochs_completed": report["cumulative_epochs_completed"],
                "main_updates": report["main_updates"],
                "data_manifest_sha256": plan["manifest_sha256"],
            },
            temp,
        )
        temp.replace(out / name)
        return sha((out / name).read_bytes())

    def evaluate(rows, retain=False):
        model.eval()
        values, labels = [], []
        with torch.no_grad():
            for _, x, dt, y in batches(
                rows, list(range(len(rows))), plan["batch_size"]
            ):
                budget()
                logits = model(x, dt)
                values.append(logits[y >= 0])
                labels.append(y[y >= 0])
        logits, targets = torch.cat(values), torch.cat(labels)
        result = metrics(logits, targets)
        result["brier_mean_classes"] = result["brier_half_sum"] * (2 / 11)
        if retain:
            torch.save(
                {
                    "logits": logits,
                    "labels": targets,
                    "episode_ids": [r["id"] for r in rows],
                },
                out / "development_logits.pt",
            )
        return result

    try:
        budget()
        targets = [y for row in data["train"] for y in row["y"]]
        if sorted(set(targets)) != list(range(11)):
            raise ValueError("complete original training label support required")
        weights = torch.bincount(torch.tensor(targets), minlength=11).double().rsqrt()
        weights /= weights.mean()
        model = CoreStudyModel(**state["model_configuration"])
        model.load_state_dict(state["model"])
        optimizer, _ = adamw(model, plan["learning_rate"], 0.0)
        optimizer.load_state_dict(state["optimizer"])
        order_rng.setstate(state["order_rng"])
        torch.set_rng_state(state["torch_rng"])
        report["source_before"] = sources(model)
        report["inherited_source_equivalence"] = source_equivalence(
            report["source_before"], prior["source_before"]
        )
        report["model_configuration"] = model.construction_configuration
        report["initial_frontend_sha256"] = prior["initial_frontend_sha256"]
        report["initial_head_sha256"] = prior["initial_head_sha256"]
        for module, field in (
            (model.frontend, "initial_frontend_sha256"),
            (model.head, "initial_head_sha256"),
        ):
            if tensor_digest(module) != prior[field]:
                raise ValueError("resumed common tensors differ from original")
        shutil.copyfile(parent / "best.pt", out / "best.pt")
        report["inherited_best_checkpoint_sha256"] = prior["best_checkpoint_sha256"]
        report["best_checkpoint_sha256"] = prior["best_checkpoint_sha256"]
        best, best_epoch, anchor, stale = inherited
        report["best_epoch"] = best_epoch
        for epoch in range(len(prior["epochs"]) + 1, args.max_epochs + 1):
            budget()
            order = list(range(len(data["train"])))
            order_rng.shuffle(order)
            event(
                "epoch_started",
                epoch=epoch,
                episode_order=[data["train"][i]["id"] for i in order],
            )
            losses = []
            for ids, x, dt, y in batches(data["train"], order, plan["batch_size"]):
                budget()
                model.train()
                optimizer.zero_grad(set_to_none=True)
                event("update_started", phase="main", episode_ids=ids)
                receipt = backward_effective_batch(
                    model,
                    x,
                    dt,
                    y,
                    weights,
                    micro_batch_size=plan["micro_batch_size"],
                    before_forward=budget,
                )
                receipt["target_weight_sum"] = float(weights[y[y >= 0]].sum())
                receipt["weighted_loss_numerator"] = (
                    receipt["loss"] * receipt["target_weight_sum"]
                )
                active = [p for p in model.parameters() if p.requires_grad]
                if any(
                    p.grad is None or not bool(torch.isfinite(p.grad).all())
                    for p in active
                ):
                    raise FloatingPointError("missing/nonfinite continued gradient")
                norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
                if not bool(torch.isfinite(norm)):
                    raise FloatingPointError("nonfinite continued gradient norm")
                event("optimizer_started", phase="main")
                optimizer.step()
                report["main_updates"] += 1
                event(
                    "optimizer_completed",
                    phase="main",
                    number=report["main_updates"],
                    gradient_norm=float(norm),
                    **receipt,
                )
                losses.append(receipt)
            development = evaluate(data["dev"])
            phase_wall_seconds = elapsed()
            row = {
                "epoch": epoch,
                "complete": True,
                "events": sum(v["events"] for v in losses),
                "training_weighted_loss": aggregate_training_objectives(losses),
                "training_target_weight_sum": sum(
                    v["target_weight_sum"] for v in losses
                ),
                "training_weighted_loss_numerator": sum(
                    v["weighted_loss_numerator"] for v in losses
                ),
                "development": development,
                "phase_process_wall_seconds": phase_wall_seconds,
                "cumulative_process_wall_seconds": outer["whole_process_wall_seconds"]
                + phase_wall_seconds,
                "phase_full_process_cpu_seconds": time.process_time(),
            }
            report["epochs"].append(row)
            report["cumulative_epochs_completed"] = epoch
            if (
                tensor_digest(model.frontend) != prior["initial_frontend_sha256"]
                or tensor_digest(model.head) != prior["initial_head_sha256"]
            ):
                raise ValueError("frozen common tensors changed during continuation")
            event("epoch_completed", **row)
            score = development["macro_f1_11_classes"]
            if (
                report["first_observed_quality_crossing_cumulative_wall_seconds"]
                is None
                and score >= plan["quality_threshold"]
            ):
                report["first_observed_quality_crossing_cumulative_wall_seconds"] = row[
                    "cumulative_process_wall_seconds"
                ]
            if score > best:
                best = score
                report["best_epoch"] = epoch
                report["best_checkpoint_sha256"] = snapshot("best.pt")
            if score > anchor + plan["plateau_delta"]:
                anchor, stale = score, 0
            else:
                stale += 1
            report["last_checkpoint_sha256"] = snapshot("last.pt")
            if epoch >= plan["min_epochs"] and stale >= plan["patience"]:
                report["stop_reason"] = "development_plateau"
                break
        report.setdefault("stop_reason", "epoch_cap_not_convergence")
        model.load_state_dict(torch.load(out / "best.pt", weights_only=False)["model"])
        report["selected_development"] = evaluate(data["dev"], retain=True)
        report["training_adequacy_established"] = report[
            "stop_reason"
        ] == "development_plateau" and report["memorization"].get("passed", False)
        report["status"] = "completed_development"
    except TimeoutError as error:
        report.update(status="budget_exhausted", error=str(error))
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    finally:
        report.update(
            phase_process_wall_seconds=elapsed(),
            phase_full_process_cpu_seconds=time.process_time(),
            peak_rss_bytes=peak_rss(),
            source_after=sources(model),
        )
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        report["common_weights_unchanged"] = (
            model is not None
            and tensor_digest(model.frontend) == prior["initial_frontend_sha256"]
            and tensor_digest(model.head) == prior["initial_head_sha256"]
        )
        if not report["source_unchanged"] or not report["common_weights_unchanged"]:
            report["training_adequacy_established"] = False
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        if model is not None and prior["arm"] == "hcsn":
            report["frozen_table_cache"] = (
                [layer.operator.cache_receipt() for layer in model.core.network.layers]
                if plan["cache_frozen_tables"]
                else []
            )
            report["training_domain_coverage"] = (
                "no whole-training qualification; original capture and any later checkpoint audits remain separate"
            )
        event("finished", status=report["status"])
        journal.close()
        report["events_sha256"] = sha((out / "events.jsonl").read_bytes())
        save(out / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-dir", type=Path, required=True)
    parser.add_argument("--parent-outer-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-epochs", type=int, default=400)
    parser.add_argument("--total-wall-seconds", type=float, default=14400)
    report = continue_fit(parser.parse_args())
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "cumulative_epochs_completed",
                    "training_adequacy_established",
                    "phase_process_wall_seconds",
                )
            }
        )
    )
    return (
        0
        if report["status"] == "completed_development" and report["source_unchanged"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
