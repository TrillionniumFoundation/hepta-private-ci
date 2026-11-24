"""Budgeted ABC/D episode training. No HCSN admission or E/confirmation route."""

import argparse
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import traceback

from data import save, sha
from episodes import MODES, prepare_episodes, read_episodes


def sources():
    root = Path(__file__).parent
    return {
        p.name: sha(p.read_bytes())
        for p in sorted(root.iterdir())
        if p.suffix in (".py", ".json")
    }


def peak_rss():
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def metrics(logits, labels):
    import torch

    if not bool(torch.isfinite(logits).all()):
        raise FloatingPointError("nonfinite evaluation logits")
    probabilities = logits.softmax(-1)
    predictions = probabilities.argmax(-1)
    matrix = (
        torch.bincount(labels * 11 + predictions, minlength=121)
        .reshape(11, 11)
        .double()
    )
    support, predicted, correct = matrix.sum(1), matrix.sum(0), matrix.diag()
    f1 = 2 * correct / (support + predicted).clamp_min(1)
    confidence = probabilities.max(-1).values
    ece = 0.0
    for index in range(15):
        selected = (confidence >= index / 15) & (
            (confidence < (index + 1) / 15) if index < 14 else (confidence <= 1)
        )
        if bool(selected.any()):
            ece += float(
                selected.double().mean()
                * (
                    confidence[selected].mean()
                    - (predictions[selected] == labels[selected]).double().mean()
                ).abs()
            )
    return {
        "events": len(labels),
        "accuracy": float((predictions == labels).double().mean()),
        "macro_f1_11_classes": float(f1.mean()),
        "macro_f1_present_classes": float(f1[support > 0].mean()),
        "balanced_accuracy_present_classes": float(
            (correct[support > 0] / support[support > 0]).mean()
        ),
        "nll": float(torch.nn.functional.cross_entropy(logits, labels)),
        "brier_half_sum": float(
            0.5
            * ((probabilities - torch.nn.functional.one_hot(labels, 11)) ** 2)
            .sum(-1)
            .mean()
        ),
        "ece_15_equal_width_bins": ece,
        "confusion_matrix": matrix.long().tolist(),
    }


def fit(args):
    import torch
    from capacity import adamw, parameter_audit
    from gradient_diagnostics import gradient_activity
    from models import build_model, metadata

    if (
        not 1 <= args.epochs <= 100
        or not 0 <= args.memorization_updates <= 256
        or args.max_updates is not None
        and args.max_updates < 1
        or not math.isfinite(args.wall_seconds)
        or args.wall_seconds <= 0
        or args.rss_bytes < 1
        or not math.isfinite(args.gradient_norm_cap)
        or args.gradient_norm_cap <= 0
    ):
        raise ValueError("invalid training or resource envelope")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    report = {
        "schema": "hcsn-localization-development-fit-v1",
        "status": "started",
        "source_before": sources(),
        "formal_fits_started": 0,
        "confirmation_access": False,
        "scientific_admission": "HOLD",
        "training_adequacy_established": False,
        "main_updates_completed": 0,
        "diagnostic_updates_completed": 0,
        "epochs": [],
        "energy_joules": None,
        "energy_missing_reason": "no complete system meter",
        "per_arm_validation_only": True,
        "memory_enforcement": "external hard envelope required",
    }
    plan = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    report["plan_sha256"] = save(
        output / "plan.json", {"arguments": plan, "source": report["source_before"]}
    )
    log = (output / "events.jsonl").open("x", encoding="utf-8")

    def event(kind, **values):
        log.write(
            json.dumps(
                {
                    "event": kind,
                    "wall_seconds": time.perf_counter() - started,
                    **values,
                },
                allow_nan=False,
            )
            + "\n"
        )
        log.flush()

    def check():
        peak = peak_rss()
        if (
            time.perf_counter() - started > args.wall_seconds
            or peak is not None
            and peak > args.rss_bytes
        ):
            raise TimeoutError("declared wall/RSS envelope exhausted; not convergence")

    model = optimizer = None
    cursor = {"phase": "preparation"}
    try:
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(args.seed)
        episodes, frontend, manifest = read_episodes(
            args.prepared, args.manifest_sha256
        )
        report.update(
            data_manifest_sha256=args.manifest_sha256,
            data_mode=manifest["mode"],
            frontend_sha256=manifest["frontend_sha256"],
            selection_sha256=manifest["selection_sha256"],
        )
        model = build_model(args.arm, s4_repo=args.s4_repo, width=args.width)
        report["model"] = metadata(model)
        probe_generator = torch.Generator().manual_seed(0)
        probe = (
            torch.randn((1, 4, 25), generator=probe_generator, dtype=torch.float64),
            torch.full((1, 4), 0.01, dtype=torch.float64),
        )
        report["capacity"] = parameter_audit(model, probe)
        if report["capacity"]["disconnected_parameters"]:
            raise ValueError(
                "unused trainable parameter in label-free connectivity probe"
            )
        tensors = {
            part: [
                (
                    entry,
                    torch.tensor(entry["x"], dtype=torch.float64)[None],
                    torch.tensor(entry["dt"], dtype=torch.float64)[None],
                    torch.tensor(entry["y"], dtype=torch.long),
                )
                for entry in entries
            ]
            for part, entries in episodes.items()
        }
        weights = torch.tensor(frontend["class_weights"], dtype=torch.float64)
        if (
            weights.shape != (11,)
            or not bool(torch.isfinite(weights).all())
            or bool((weights <= 0).any())
        ):
            raise ValueError("invalid ABC class weights")
        initial = {
            name: value.detach().clone() for name, value in model.state_dict().items()
        }
        initialization_rng = torch.get_rng_state().clone()
        torch.save(initial, output / "initial.pt")
        report["initialization_sha256"] = sha((output / "initial.pt").read_bytes())

        def update(batch, phase, number):
            check()
            entry, x, dt, y = batch
            model.train()
            optimizer.zero_grad(set_to_none=True)
            event("update_started", phase=phase, number=number, episode=entry["id"])
            logits = model(x, dt)
            if logits.shape != (1, len(y), 11) or not bool(
                torch.isfinite(logits).all()
            ):
                raise FloatingPointError("invalid training logits")
            loss = torch.nn.functional.cross_entropy(logits[0], y, weight=weights)
            loss.backward()
            event(
                "gradient_observed",
                phase=phase,
                number=number,
                episode=entry["id"],
                gradient_activity=gradient_activity(model),
                diagnostics=getattr(model, "last_diagnostics", {}),
            )
            active = [p for p in model.parameters() if p.requires_grad]
            if any(
                p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in active
            ):
                raise FloatingPointError("missing/nonfinite training gradient")
            norm = torch.nn.utils.clip_grad_norm_(active, args.gradient_norm_cap)
            if not bool(torch.isfinite(loss)) or not bool(torch.isfinite(norm)):
                raise FloatingPointError("nonfinite loss/gradient norm")
            event("optimizer_step_started", phase=phase, number=number)
            optimizer.step()
            report[phase + "_updates_completed"] += 1
            diagnostics = getattr(model, "last_diagnostics", {})
            event(
                "optimizer_step_completed",
                phase=phase,
                number=number,
                loss=float(loss.detach()),
                preclip_gradient_norm=float(norm),
                diagnostics=diagnostics,
            )
            return float(loss.detach())

        def evaluate(batches):
            logits, labels = [], []
            model.eval()
            with torch.no_grad():
                for _, x, dt, y in batches:
                    check()
                    value = model(x, dt)
                    if value.shape != (1, len(y), 11):
                        raise ValueError("invalid evaluation output shape")
                    logits.append(value[0])
                    labels.append(y)
            return metrics(torch.cat(logits), torch.cat(labels))

        if args.memorization_updates:
            cursor = {"phase": "diagnostic"}
            batch = next(
                (batch for batch in tensors["train"] if len(set(batch[0]["y"])) > 1),
                None,
            )
            if batch is None:
                raise ValueError(
                    "no multiclass training episode for adequacy diagnostic"
                )
            optimizer, groups = adamw(model, args.learning_rate, args.weight_decay)
            before = evaluate([batch])
            for number in range(1, args.memorization_updates + 1):
                update(batch, "diagnostic", number)
            after = evaluate([batch])
            report["memorization"] = {
                "episode": batch[0]["id"],
                "classes": sorted(set(batch[0]["y"])),
                "before": before,
                "after": after,
                "optimizer_groups": groups,
                "passed": after["accuracy"] >= 0.95
                and after["macro_f1_present_classes"] >= 0.9,
                "scope": "training-only diagnostic; restored before main fit",
            }
            model.load_state_dict(initial)
            torch.set_rng_state(initialization_rng)
            report["initialization_restored"] = all(
                torch.equal(v, model.state_dict()[n]) for n, v in initial.items()
            )
            if not report["initialization_restored"]:
                raise ValueError("diagnostic changed main initialization")
        optimizer, report["optimizer_groups"] = adamw(
            model, args.learning_rate, args.weight_decay
        )
        order_rng = random.Random(args.seed)
        best, stale, seen_labels = -1.0, 0, set()
        report["development_before"] = evaluate(tensors["dev"])
        event("main_fit_started", initialization_sha256=report["initialization_sha256"])
        for epoch in range(1, args.epochs + 1):
            order = list(range(len(tensors["train"])))
            order_rng.shuffle(order)
            event(
                "epoch_started",
                epoch=epoch,
                episode_order=[tensors["train"][i][0]["id"] for i in order],
            )
            losses = []
            for position, index in enumerate(order):
                if (
                    args.max_updates is not None
                    and report["main_updates_completed"] >= args.max_updates
                ):
                    break
                cursor = {"phase": "main", "epoch": epoch, "position": position}
                batch = tensors["train"][index]
                losses.append(
                    update(batch, "main", report["main_updates_completed"] + 1)
                )
                seen_labels.update(batch[0]["y"])
            development = evaluate(tensors["dev"])
            complete_epoch = len(losses) == len(order)
            report["epochs"].append(
                {
                    "epoch": epoch,
                    "complete": complete_epoch,
                    "mean_weighted_training_loss": sum(losses) / len(losses),
                    "development": development,
                }
            )
            check()
            score = development["macro_f1_11_classes"]
            if score > best + 0.002:
                best, stale = score, 0
            else:
                stale += 1
            cursor = {
                "phase": "epoch_finished",
                "epoch": epoch,
                "complete": complete_epoch,
            }
            checkpoint = output / f"epoch-{epoch}.pt"
            torch.save(
                {
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "torch_rng": torch.get_rng_state(),
                    "order_rng": order_rng.getstate(),
                    "cursor": cursor,
                    "manifest_sha256": args.manifest_sha256,
                },
                checkpoint,
            )
            event(
                "epoch_checkpoint",
                path=checkpoint.name,
                sha256=sha(checkpoint.read_bytes()),
            )
            if (
                args.max_updates is not None
                and report["main_updates_completed"] >= args.max_updates
            ):
                report["stop_reason"] = "declared_update_cap"
                break
            if complete_epoch and epoch >= 30 and stale >= 10:
                report["stop_reason"] = "development_plateau"
                break
        report.setdefault("stop_reason", "declared_epoch_cap")
        report.update(
            status="completed_development_only",
            labels_seen_by_main_optimizer=sorted(seen_labels),
            multiclass_main_training=len(seen_labels) > 1,
            source_dependency_files_unchanged=all(
                sha(Path(path).read_bytes()) == expected
                for path, expected in report["model"]["source_files_sha256"].items()
            ),
        )
        if not report["source_dependency_files_unchanged"]:
            report["status"] = "source_changed"
    except TimeoutError as error:
        report.update(status="budget_exhausted", error=str(error))
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    finally:
        report.update(
            source_after=sources(),
            cursor=cursor,
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu_started,
            peak_rss_bytes=peak_rss(),
        )
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        event("finished", status=report["status"])
        log.close()
        report["events_sha256"] = sha((output / "events.jsonl").read_bytes())
        save(output / "result.json", report)
    return 0 if report["status"] == "completed_development_only" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--archive", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--selection", choices=MODES, default="development-subset")
    train = sub.add_parser("fit")
    train.add_argument("--prepared", type=Path, required=True)
    train.add_argument("--manifest-sha256", required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument(
        "--arm",
        choices=("gru", "cfc", "snn_plif", "ssm_s4d", "attention"),
        required=True,
    )
    train.add_argument("--width", type=int, required=True)
    train.add_argument("--seed", type=int, required=True)
    train.add_argument("--epochs", type=int, default=100)
    train.add_argument("--max-updates", type=int)
    train.add_argument("--memorization-updates", type=int, default=0)
    train.add_argument("--learning-rate", type=float, default=0.001)
    train.add_argument("--weight-decay", type=float, default=0.0)
    train.add_argument("--gradient-norm-cap", type=float, default=1.0)
    train.add_argument("--wall-seconds", type=float, required=True)
    train.add_argument("--rss-bytes", type=int, required=True)
    train.add_argument("--s4-repo", type=Path)
    args = parser.parse_args()
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[variable] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if args.command == "prepare":
        result = prepare_episodes(args.archive, args.output, mode=args.selection)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "episodes": len(result["episodes"]),
                    "manifest_sha256": sha(
                        (args.output / "data-manifest.json").read_bytes()
                    ),
                }
            )
        )
        return 0
    return fit(args)


if __name__ == "__main__":
    raise SystemExit(main())
