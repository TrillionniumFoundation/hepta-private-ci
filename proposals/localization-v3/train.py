"""Source-bound full-ABC development fits with common frontend and head.

No E scoring command is provided. Every attempt retains its own journal,
checkpoints, source identities, training adequacy findings and measured costs.
"""

import argparse
import json
import os
from pathlib import Path
import random
import time
import traceback

import torch
from cores import (
    ARMS,
    CoreStudyModel,
    tensor_digest,
    explicit_hcsn_grid,
    explicit_plif_configuration,
)
from capacity import adamw, parameter_audit
from data import save, sha
from episodes import read_episodes
from train_development import metrics, peak_rss
from hcsn_study_support import sources, batches, backward_effective_batch

# The campaign supplies dispatch time, including process spawn and all imports.
PROCESS_STARTED = float(os.environ.get("HCSN_PROCESS_STARTED", time.monotonic()))


def aggregate_training_objectives(receipts):
    """Aggregate weighted CE by its target-weight denominator, not event count."""
    denominator = sum(row["target_weight_sum"] for row in receipts)
    if denominator <= 0:
        raise ValueError("no positive objective weight")
    return sum(row["weighted_loss_numerator"] for row in receipts) / denominator


def fit(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    report = {
        "schema": "hcsn-common-core-development-v1",
        "status": "started",
        "formal_fits_started": 0,
        "confirmation_access": False,
        "scientific_admission": "HOLD",
        "arm": args.arm,
        "seed": args.seed,
        "epochs": [],
        "main_updates": 0,
        "diagnostic_updates": 0,
        "energy_joules": None,
        "peak_vram_bytes": None,
        "main_micro_forward_attempts": 0,
        "diagnostic_micro_forward_attempts": 0,
        "resume_supported": False,
        "unmeasured_cost_reason": "CPU development; no complete-system energy or GPU meter",
        "training_adequacy_established": False,
        "time_to_quality_seconds": None,
        "quality_threshold_macro_f1": args.quality_threshold,
        "time_to_quality_scope": "first observed development evaluation crossing; crossing between evaluations is not localized",
        "source_before": sources(),
    }
    plan = vars(args).copy()
    report["plan_sha256"] = save(out / "plan.json", plan)
    journal = (out / "events.jsonl").open("x")
    optimizer = model = recorder = None
    order_rng = random.Random(args.seed)

    def event(kind, **values):
        journal.write(
            json.dumps(
                {"kind": kind, "wall_seconds": time.perf_counter() - started, **values},
                allow_nan=False,
            )
            + "\n"
        )
        journal.flush()

    def budget():
        rss = peak_rss()
        if (
            time.perf_counter() - started > args.wall_seconds
            or rss is not None
            and rss > args.rss_bytes
        ):
            raise TimeoutError("declared resource limit; not convergence")

    def evaluate(rows, *, retain=None):
        results, targets = [], []
        model.eval()
        with torch.no_grad():
            for _, x, dt, y in batches(rows, list(range(len(rows))), args.batch_size):
                budget()
                value = model(x, dt)
                selected = y >= 0
                results.append(value[selected])
                targets.append(y[selected])
        logits, labels = torch.cat(results), torch.cat(targets)
        result = metrics(logits, labels)
        result["brier_mean_classes"] = result["brier_half_sum"] * (2 / 11)
        if retain:
            torch.save(
                {
                    "logits": logits,
                    "labels": labels,
                    "episode_ids": [r["id"] for r in rows],
                },
                retain,
            )
        return result

    def update(batch, phase):
        budget()
        ids, x, dt, y = batch
        model.train()
        optimizer.zero_grad(set_to_none=True)
        event("update_started", phase=phase, episode_ids=ids)

        def before_forward(start, end):
            budget()
            report[phase + "_micro_forward_attempts"] += 1
            if args.arm == "hcsn" and recorder:
                model.core.record_context = {
                    "episode_id": "+".join(ids[start:end]),
                    "update_index": report[phase + "_updates"],
                }

        receipt = backward_effective_batch(
            model,
            x,
            dt,
            y,
            weights,
            micro_batch_size=args.micro_batch_size,
            before_forward=before_forward,
        )
        receipt["target_weight_sum"] = float(weights[y[y >= 0]].sum())
        receipt["weighted_loss_numerator"] = (
            receipt["loss"] * receipt["target_weight_sum"]
        )
        active = [p for p in model.parameters() if p.requires_grad]
        if any(
            p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in active
        ):
            raise FloatingPointError("missing or nonfinite connected gradient")
        norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
        if not bool(torch.isfinite(norm)):
            raise FloatingPointError("nonfinite loss or gradient norm")
        event("optimizer_started", phase=phase)
        optimizer.step()
        report[phase + "_updates"] += 1
        event(
            "optimizer_completed",
            phase=phase,
            number=report[phase + "_updates"],
            gradient_norm=float(norm),
            **receipt,
        )
        return receipt

    def checkpoint(path):
        temporary = Path(str(path) + ".tmp")
        torch.save(
            {
                "model": model.state_dict(),
                "model_configuration": model.construction_configuration,
                "optimizer": optimizer.state_dict() if optimizer else None,
                "torch_rng": torch.get_rng_state(),
                "order_rng": order_rng.getstate(),
                "epochs_completed": len(report["epochs"]),
                "main_updates": report["main_updates"],
                "data_manifest_sha256": args.manifest_sha256,
            },
            temporary,
        )
        temporary.replace(path)
        return sha(path.read_bytes())

    try:
        data, frontend, manifest = read_episodes(args.prepared, args.manifest_sha256)
        if manifest["mode"] != "all-development":
            raise ValueError("only complete ABC/D preparation is accepted")
        labels = sorted({label for row in data["train"] for label in row["y"]})
        if labels != list(range(11)):
            raise ValueError("complete 11-class training support required")
        report.update(
            data_manifest_sha256=args.manifest_sha256,
            frontend_sha256=manifest["frontend_sha256"],
            train_events=sum(len(r["y"]) for r in data["train"]),
            dev_events=sum(len(r["y"]) for r in data["dev"]),
            training_classes=labels,
            episodes_train=len(data["train"]),
            split="ABC train, D development, E never interpreted or scored",
        )
        counts = torch.bincount(
            torch.tensor([y for r in data["train"] for y in r["y"]]), minlength=11
        ).double()
        weights = counts.rsqrt()
        weights /= weights.mean()
        model = CoreStudyModel(
            args.arm,
            width=args.width,
            seed=args.seed,
            s4_repo=args.s4_repo,
            hcsn_grid=args.hcsn_grid_json,
            freeze_shared=not args.train_shared,
            cache_frozen_tables=args.cache_frozen_tables,
            learn_core_adapter=args.learn_core_adapter,
            plif_configuration=args.plif_config_json,
        )
        report.update(
            model=parameter_audit(model),
            initial_frontend_sha256=model.initial_frontend_sha256,
            initial_head_sha256=model.initial_head_sha256,
            torch_version=torch.__version__,
            torch_git_version=torch.version.git_version,
            source_before=sources(model),
            shared_frontend="25->width linear+tanh",
            shared_head="width->11 linear",
            shared_regime="jointly_trained_secondary"
            if args.train_shared
            else "frozen_shared_primary",
            module_parameters={
                name: parameter_audit(module)
                for name, module in (
                    ("frontend", model.frontend),
                    ("core", model.core),
                    ("temporal_adapter", model.temporal_adapter),
                    ("head", model.head),
                )
            },
            temporal_output_interface="learned_identity_initialized_linear"
            if args.learn_core_adapter
            else "raw_core_output",
            initial_temporal_adapter_sha256=tensor_digest(model.temporal_adapter),
            equal_initial_common_weights=True,
            parameter_count_matched=False,
            effective_batch_size=args.batch_size,
            micro_batch_size=args.micro_batch_size or args.batch_size,
            accumulation_semantics="whole-effective-batch target-weight denominator, one clip and optimizer step, padded length retained",
            state_window_events=256,
            dtype="float64",
            device="cpu",
            model_configuration=model.construction_configuration,
        )
        if args.arm == "hcsn":
            report.update(
                hcsn_configuration=model.core.network.configuration(),
                hcsn_cost_geometry=model.core.cost_geometry,
                numerical_admission="development_candidate_not_whole_training_qualified",
            )
        initial = {k: v.detach().clone() for k, v in model.state_dict().items()}
        torch.save(
            {"model": initial, "model_configuration": model.construction_configuration},
            out / "initial.pt",
        )
        report["initialization_sha256"] = sha((out / "initial.pt").read_bytes())
        optimizer, report["optimizer_groups"] = adamw(model, args.learning_rate, 0.0)
        if args.memorization_updates:
            chosen = next(row for row in data["train"] if len(set(row["y"])) > 1)
            batch = next(batches([chosen], [0], 1))
            before = evaluate([chosen])
            curve = [
                {
                    "update": 0,
                    "metrics": before,
                    "process_wall_seconds": time.monotonic() - PROCESS_STARTED,
                    "diagnostics": getattr(model.core, "diagnostics", {}),
                }
            ]
            after, first_pass = before, None
            for step in range(1, args.memorization_updates + 1):
                update(batch, "diagnostic")
                if (
                    step % args.memorization_check_every == 0
                    or step == args.memorization_updates
                ):
                    after = evaluate([chosen])
                    passed = (
                        after["accuracy"] >= 0.95
                        and after["macro_f1_present_classes"] >= 0.9
                    )
                    row = {
                        "update": step,
                        "metrics": after,
                        "passed": passed,
                        "process_wall_seconds": time.monotonic() - PROCESS_STARTED,
                        "diagnostics": getattr(model.core, "diagnostics", {}),
                    }
                    curve.append(row)
                    event("memorization_evaluated", **row)
                    if passed:
                        first_pass = step
                        break
            report["memorization"] = {
                "episode_id": chosen["id"],
                "before": before,
                "after": after,
                "passed": after["accuracy"] >= 0.95
                and after["macro_f1_present_classes"] >= 0.9,
                "maximum_updates": args.memorization_updates,
                "check_every": args.memorization_check_every,
                "first_observed_passing_update": first_pass,
                "curve": curve,
                "scope": "training-only diagnostic; exact initial weights and optimizer restored for main fit",
            }
            report["memorization_checkpoint_sha256"] = checkpoint(
                out / "memorization.pt"
            )
            model.load_state_dict(initial)
            if any(
                not torch.equal(v, initial[k]) for k, v in model.state_dict().items()
            ):
                raise ValueError("diagnostic initialization restore failed")
            optimizer, _ = adamw(model, args.learning_rate, 0.0)
        if args.arm == "hcsn":
            from qualification.hcsn_differentiable.training_domain import (
                TrainingDomainRecorder,
            )

            recorder = TrainingDomainRecorder(
                out / "training-domain.jsonl",
                data_sha256=args.manifest_sha256,
                configuration_sha256=report["plan_sha256"],
                max_records=args.trace_records,
                max_bytes=args.trace_bytes,
            )
            model.core.recorder = recorder
        if args.arm == "hcsn" and recorder:
            model.core.recorder = None
        report["development_before"] = evaluate(data["dev"])
        report["development_before_process_wall_seconds"] = (
            time.monotonic() - PROCESS_STARTED
        )
        if args.arm == "hcsn" and recorder:
            model.core.recorder = recorder
        best, plateau_anchor, stale = -1.0, -1.0, 0
        for epoch in range(1, args.max_epochs + 1):
            order = list(range(len(data["train"])))
            order_rng.shuffle(order)
            event(
                "epoch_started",
                epoch=epoch,
                episode_order=[data["train"][i]["id"] for i in order],
            )
            losses = [
                update(batch, "main")
                for batch in batches(data["train"], order, args.batch_size)
            ]
            # Training records are complete above; evaluation capture uses a distinct identity.
            if args.arm == "hcsn" and recorder:
                model.core.recorder = None
            development = evaluate(data["dev"])
            if args.arm == "hcsn" and recorder:
                model.core.recorder = recorder
            row = {
                "epoch": epoch,
                "complete": True,
                "events": sum(row["events"] for row in losses),
                "training_weighted_loss": aggregate_training_objectives(losses),
                "training_target_weight_sum": sum(
                    row["target_weight_sum"] for row in losses
                ),
                "training_weighted_loss_numerator": sum(
                    row["weighted_loss_numerator"] for row in losses
                ),
                "development": development,
                "wall_seconds": time.perf_counter() - started,
                "process_wall_seconds": time.monotonic() - PROCESS_STARTED,
                "process_cpu_seconds": time.process_time(),
            }
            report["epochs"].append(row)
            if not args.train_shared and (
                tensor_digest(model.frontend) != model.initial_frontend_sha256
                or tensor_digest(model.head) != model.initial_head_sha256
            ):
                raise ValueError("frozen shared frontend/head changed")
            event("epoch_completed", **row)
            score = development["macro_f1_11_classes"]
            if (
                report["time_to_quality_seconds"] is None
                and score >= args.quality_threshold
            ):
                report["time_to_quality_seconds"] = row["wall_seconds"]
                report["process_time_to_quality_seconds"] = (
                    time.monotonic() - PROCESS_STARTED
                )
            if score > best:
                best = score
                report["best_epoch"] = epoch
                report["best_checkpoint_sha256"] = checkpoint(out / "best.pt")
            if score > plateau_anchor + args.plateau_delta:
                plateau_anchor, stale = score, 0
            else:
                stale += 1
            report["last_checkpoint_sha256"] = checkpoint(out / "last.pt")
            if epoch >= args.min_epochs and stale >= args.patience:
                report["stop_reason"] = "development_plateau"
                break
        report.setdefault("stop_reason", "epoch_cap_not_convergence")
        if args.arm == "hcsn" and recorder:
            model.core.recorder = None
        model.load_state_dict(torch.load(out / "best.pt", weights_only=False)["model"])
        report["selected_development"] = evaluate(
            data["dev"], retain=out / "development_logits.pt"
        )
        report["training_adequacy_established"] = report[
            "stop_reason"
        ] == "development_plateau" and report.get("memorization", {}).get(
            "passed", False
        )
        report["status"] = "completed_development"
    except TimeoutError as error:
        report.update(status="budget_exhausted", error=str(error))
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    finally:
        if recorder:
            recorder.close()
        if (
            model is not None
            and optimizer is not None
            and report["status"] != "completed_development"
        ):
            report["interrupted_checkpoint_sha256"] = checkpoint(out / "interrupted.pt")
        report.update(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu_started,
            process_wall_seconds=time.monotonic() - PROCESS_STARTED,
            peak_rss_bytes=peak_rss(),
            source_after=sources(model),
        )
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
            report["training_adequacy_established"] = False
        if model is not None:
            report["final_frontend_sha256"] = tensor_digest(model.frontend)
            report["final_head_sha256"] = tensor_digest(model.head)
            report["common_weights_unchanged"] = (
                report["final_frontend_sha256"] == model.initial_frontend_sha256
                and report["final_head_sha256"] == model.initial_head_sha256
            )
            if args.arm == "hcsn" and args.cache_frozen_tables:
                report["frozen_table_cache"] = [
                    layer.operator.cache_receipt()
                    for layer in model.core.network.layers
                ]
        event("finished", status=report["status"])
        journal.close()
        report["events_sha256"] = sha((out / "events.jsonl").read_bytes())
        save(out / "result.json", report)
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "status",
                        "arm",
                        "seed",
                        "main_updates",
                        "wall_seconds",
                        "training_adequacy_established",
                    )
                }
            )
        )
    return 0 if report["status"] == "completed_development" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--arm", required=True, choices=ARMS)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--width", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--micro-batch-size",
        type=int,
        help="optional memory bound; gradients normalize over the full effective batch",
    )
    parser.add_argument("--learning-rate", type=float, default=0.003)
    parser.add_argument("--min-epochs", type=int, default=30)
    parser.add_argument("--max-epochs", type=int, default=60)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--plateau-delta", type=float, default=0.002)
    parser.add_argument("--memorization-updates", type=int, default=256)
    parser.add_argument("--memorization-check-every", type=int, default=64)
    parser.add_argument("--wall-seconds", type=float, required=True)
    parser.add_argument("--rss-bytes", type=int, default=4294967296)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--quality-threshold", type=float, default=0.3)
    parser.add_argument("--s4-repo")
    parser.add_argument(
        "--plif-config-json",
        type=json.loads,
        help="PLIF only: full initialization and spike/membrane/trace readout configuration",
    )
    parser.add_argument(
        "--hcsn-grid-json",
        type=json.loads,
        help="HCSN only: complete seven-field GridSpec JSON object, with no implicit geometry defaults",
    )
    parser.add_argument("--trace-records", type=int, default=4096)
    parser.add_argument("--trace-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument(
        "--cache-frozen-tables",
        action="store_true",
        help="HCSN only: exact per-fit table memoization, rejects differentiable physics",
    )
    parser.add_argument(
        "--train-shared",
        action="store_true",
        help="secondary regime; default freezes frontend/head",
    )
    parser.add_argument(
        "--learn-core-adapter",
        action="store_true",
        help="identical identity-initialized trainable Linear(width,width) inside every temporal core",
    )
    args = parser.parse_args()
    if (
        not 1 <= args.min_epochs <= args.max_epochs <= 100
        or args.batch_size < 1
        or args.threads < 1
        or args.memorization_updates < 0
        or args.memorization_check_every < 1
    ):
        parser.error("invalid training envelope")
    if (
        args.micro_batch_size is not None
        and not 1 <= args.micro_batch_size <= args.batch_size
    ):
        parser.error("micro batch must be between 1 and effective batch size")
    try:
        if args.plif_config_json is not None:
            if args.arm != "snn_plif":
                raise ValueError("PLIF configuration is only valid for PLIF")
            explicit_plif_configuration(args.plif_config_json)
        if args.arm == "hcsn":
            explicit_hcsn_grid(args.hcsn_grid_json)
        elif args.hcsn_grid_json is not None or args.cache_frozen_tables:
            raise ValueError("HCSN configuration is only valid for HCSN")
    except ValueError as error:
        parser.error(str(error))
    return fit(args)


if __name__ == "__main__":
    raise SystemExit(main())
