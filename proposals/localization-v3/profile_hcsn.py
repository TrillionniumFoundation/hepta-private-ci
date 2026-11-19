"""Bounded real-window HCSN cost probe, never a completed training epoch."""

import argparse
import json
from pathlib import Path
import time
import traceback

import torch
from cores import CoreStudyModel, explicit_hcsn_grid, tensor_digest
from hcsn_study_support import batches, sources, backward_effective_batch
from capacity import adamw, parameter_audit
from data import save, sha
from episodes import read_episodes
from train_development import peak_rss
from qualification.hcsn_differentiable.training_domain import TrainingDomainRecorder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hcsn-grid-json", type=json.loads, required=True)
    parser.add_argument("--cache-frozen-tables", action="store_true")
    parser.add_argument("--learn-core-adapter", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--micro-batch-size", type=int)
    parser.add_argument("--updates", type=int, default=2)
    parser.add_argument("--positions", type=int, default=256)
    args = parser.parse_args()
    explicit_hcsn_grid(args.hcsn_grid_json)
    if (
        not 1 <= args.batch_size <= 32
        or not 1 <= args.updates <= 2
        or not 1 <= args.positions <= 256
    ):
        parser.error("cost probe envelope exceeded")
    if (
        args.micro_batch_size is not None
        and not 1 <= args.micro_batch_size <= args.batch_size
    ):
        parser.error("micro batch exceeds effective batch")
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    started, cpu_started = time.perf_counter(), time.process_time()
    plan = {**vars(args), "output": str(out)}
    report = {
        "schema": "hcsn-real-window-cost-probe-v1",
        "status": "started",
        "scope": "first ABC windows repeated for bounded cost and trained-posterior observation",
        "complete_training_epochs": 0,
        "formal_fits_started": 0,
        "confirmation_access": False,
        "training_adequacy_established": False,
        "numerical_admission": "HOLD",
        "scientific_admission": "HOLD",
        "steps": [],
        "energy_joules": None,
        "plan_sha256": save(out / "plan.json", plan),
        "source_before": sources(),
    }
    journal = (out / "events.jsonl").open("x")
    model = recorder = None
    try:
        data, _, manifest = read_episodes(args.prepared, args.manifest_sha256)
        if manifest["mode"] != "all-development":
            raise ValueError("complete ABC/D source required")
        selected = data["train"][: args.batch_size]
        ids, x, dt, y = next(
            batches(selected, list(range(len(selected))), args.batch_size)
        )
        x, dt, y = (
            x[:, : args.positions],
            dt[:, : args.positions],
            y[:, : args.positions],
        )
        model = CoreStudyModel(
            "hcsn",
            width=16,
            seed=101,
            hcsn_grid=args.hcsn_grid_json,
            cache_frozen_tables=args.cache_frozen_tables,
            learn_core_adapter=args.learn_core_adapter,
        )
        report.update(
            source_before=sources(model),
            model=parameter_audit(model),
            cost_geometry=model.core.cost_geometry,
            episode_ids=ids,
            events=int((y >= 0).sum()),
            data_manifest_sha256=args.manifest_sha256,
            grid=args.hcsn_grid_json,
        )
        optimizer, _ = adamw(model, 0.003, 0.0)
        counts = torch.bincount(
            torch.tensor([y for row in data["train"] for y in row["y"]]), minlength=11
        ).double()
        weights = counts.rsqrt()
        weights /= weights.mean()
        torch.save(model.state_dict(), out / "initial.pt")
        recorder = TrainingDomainRecorder(
            out / "training-domain.jsonl",
            data_sha256=args.manifest_sha256,
            configuration_sha256=report["plan_sha256"],
            max_records=512,
            max_bytes=32 * 1024 * 1024,
        )
        model.core.recorder = recorder
        for step in range(args.updates):
            journal.write(
                json.dumps(
                    {
                        "kind": "started",
                        "step": step,
                        "wall_seconds": time.perf_counter() - started,
                    }
                )
                + "\n"
            )
            journal.flush()
            optimizer.zero_grad(set_to_none=True)
            step_start = time.perf_counter()

            def before_forward(start, end):
                model.core.record_context = {
                    "episode_id": "+".join(ids[start:end]),
                    "update_index": step,
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
            active = [p for p in model.parameters() if p.requires_grad]
            if any(
                p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in active
            ):
                raise FloatingPointError("missing/nonfinite learned gradient")
            norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
            if not bool(torch.isfinite(norm)):
                raise FloatingPointError("nonfinite cost-probe loss or gradient norm")
            optimizer.step()
            row = {
                "step": step,
                **receipt,
                "step_seconds": time.perf_counter() - step_start,
                "gradient_norm": float(norm),
            }
            report["steps"].append(row)
            journal.write(json.dumps({"kind": "completed", **row}) + "\n")
            journal.flush()
        torch.save(
            {"model": model.state_dict(), "optimizer": optimizer.state_dict()},
            out / "after.pt",
        )
        report["status"] = "completed_cost_probe"
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    finally:
        if recorder:
            recorder.close()
        report.update(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu_started,
            peak_rss_bytes=peak_rss(),
            source_after=sources(model),
        )
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        if model is not None:
            report["common_weights_unchanged"] = (
                tensor_digest(model.frontend) == model.initial_frontend_sha256
                and tensor_digest(model.head) == model.initial_head_sha256
            )
            if args.cache_frozen_tables:
                report["frozen_table_cache"] = [
                    layer.operator.cache_receipt()
                    for layer in model.core.network.layers
                ]
        journal.close()
        report["artifacts"] = {
            p.name: sha(p.read_bytes()) for p in out.iterdir() if p.is_file()
        }
        save(out / "RESULT.json", report)
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "status",
                        "wall_seconds",
                        "peak_rss_bytes",
                        "source_unchanged",
                    )
                }
            )
        )
    return 0 if report["status"] == "completed_cost_probe" else 2


if __name__ == "__main__":
    raise SystemExit(main())
