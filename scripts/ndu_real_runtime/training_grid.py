"""Generate a complete matched fit inventory; this module executes no fits."""

import argparse
import json
from pathlib import Path
import sys

from .metering import atomic_json, canonical_sha, file_sha
from .training import FitConfig, _source_pins

PILOT_SEEDS = (104729, 130363, 155921, 196613)
JOINT_CONTROLLERS = ("light", "ndu", "tuned_fixed", "voi", "mpc")


def fit_grid(
    records,
    records_sha256,
    output_root,
    *,
    python=sys.executable,
    seeds=PILOT_SEEDS,
    head_lrs=(0.001, 0.003, 0.01),
    config=FitConfig(),
    control_plan=None,
):
    """Return every pretraining dependency and fit candidate before selection.

    The default grid contains 8 shared content checkpoints, 24 frozen shared-head
    fits and 120 controller-conditioned joint fits. Initial policies use content
    checkpoints without another fit. The common collector is a separate job and
    is never counted among these four independent initialization seeds.
    """
    if (
        not Path(records).is_absolute()
        or not Path(output_root).is_absolute()
        or not Path(python).is_absolute()
        or len(records_sha256) != 64
        or any(c not in "0123456789abcdef" for c in records_sha256)
    ):
        raise ValueError(
            "Absolute paths and the actual records file digest are required"
        )
    if (
        not seeds
        or len(seeds) > 16
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
        or not head_lrs
        or len(head_lrs) > 8
        or len(set(head_lrs)) != len(head_lrs)
    ):
        raise ValueError(
            "Independent seeds and LR candidates must be finite and unique"
        )
    for lr in head_lrs:
        FitConfig(
            config.content_epochs,
            config.fit_epochs,
            config.batch_size,
            config.content_lr,
            lr,
            config.latency_weight,
            config.max_wall_seconds,
        )
    intent = {
        "records": str(records),
        "records_sha256": records_sha256,
        "output_root": str(output_root),
        "python": str(python),
        "seeds": list(seeds),
        "head_lrs": list(head_lrs),
        "content_epochs": config.content_epochs,
        "fit_epochs": config.fit_epochs,
        "batch_size": config.batch_size,
        "content_lr": config.content_lr,
        "latency_weight": config.latency_weight,
        "max_wall_seconds": config.max_wall_seconds,
        "source_pins": _source_pins(),
        "grid_source_sha256": file_sha(__file__),
    }
    prefix = "fit-grid-" + canonical_sha(intent)[:20]
    if control_plan is not None:
        if not Path(control_plan).is_absolute():
            raise ValueError("Control plan needs an absolute source path")
        intent.update(
            control_plan=str(control_plan), control_plan_sha256=file_sha(control_plan)
        )
        prefix = "fit-grid-" + canonical_sha(intent)[:20]
    jobs = []

    def add(
        seed, core, phase, regime, controller, lr, pretrained=None, trial_index=None
    ):
        name = (
            f"s{seed}/{core}/{phase}"
            if phase == "content"
            else f"s{seed}/{core}/{regime}-{controller}/lr-{lr:g}"
        )
        destination = Path(output_root) / name
        identity = prefix + "/" + name
        argv = [
            "-m",
            "ndu_real_runtime.training",
            "--records",
            str(records),
            "--expected-records-sha256",
            records_sha256,
            "--output",
            str(destination),
            "--seed",
            str(seed),
            "--core",
            core,
            "--regime",
            regime,
            "--controller",
            controller,
            "--content-epochs",
            str(config.content_epochs),
            "--fit-epochs",
            str(config.fit_epochs),
            "--batch-size",
            str(config.batch_size),
            "--content-lr",
            str(config.content_lr),
            "--lr",
            str(lr),
            "--latency-weight",
            str(config.latency_weight),
            "--max-wall-seconds",
            str(config.max_wall_seconds),
            "--run-id",
            identity,
            "--replicate-role",
            "fit",
        ]
        if control_plan is not None:
            argv += ["--control-plan", str(control_plan)]
        if phase == "content":
            argv.append("--content-only")
        else:
            argv += ["--pretrained", pretrained["output"]]
        row = {
            "job_id": identity,
            "status": "PLANNED_NOT_EXECUTED",
            "seed": seed,
            "core": core,
            "phase": phase,
            "regime": regime,
            "controller": controller,
            "lr": lr,
            "trial_index": trial_index,
            "command": {"executable": str(python), "args": argv},
            "output": str(destination),
            "depends_on": [] if pretrained is None else [pretrained["job_id"]],
            "weights_path": str(destination / "weights.pt"),
            "weights_sha256": None,
            "receipt_path": str(destination / "receipt.json"),
            "runtime_job_id": None,
            "shared_by_controllers": list(JOINT_CONTROLLERS)
            if regime == "frozen" and phase == "fit"
            else [],
            "costs": None,
            "scientific_admission": "HOLD",
        }
        jobs.append(row)
        return row

    for seed in seeds:
        for core in ("ordinary", "hepta"):
            pretrained = add(
                seed, core, "content", "frozen", "shared", config.content_lr
            )
            for trial_index, lr in enumerate(head_lrs):
                add(seed, core, "fit", "frozen", "shared", lr, pretrained, trial_index)
                for controller in JOINT_CONTROLLERS:
                    add(
                        seed,
                        core,
                        "fit",
                        "joint",
                        controller,
                        lr,
                        pretrained,
                        trial_index,
                    )
    return {
        "schema": "ndu.real.fit-grid.v1",
        "intent": intent,
        "grid_id": prefix,
        "counts": {
            "independent_seed_groups": len(seeds),
            "content": len(seeds) * 2,
            "frozen_shared": len(seeds) * 2 * len(head_lrs),
            "joint": len(seeds) * 2 * len(head_lrs) * len(JOINT_CONTROLLERS),
        },
        "collector_included_in_independent_seed_count": False,
        "fixed_schedule_selection": "separate real development runs; not inferred by this generator",
        "failed_or_unfinished_candidates_may_be_dropped": False,
        "executed": False,
        "jobs": jobs,
    }


def model_index(plan):
    result = {"schema": "ndu.real.model-index.v1", "content": [], "fits": []}
    for job in plan["jobs"]:
        row = {
            "core": job["core"],
            "seed": job["seed"],
            "directory": job["output"],
            "status": "planned",
            "weights_sha256": None,
            "receipt_sha256": None,
        }
        if job["phase"] == "fit":
            row.update(
                regime=job["regime"],
                controller=job["controller"],
                trial_index=job["trial_index"],
            )
        result["content" if job["phase"] == "content" else "fits"].append(row)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True)
    parser.add_argument("--records-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--seeds", type=int, nargs="+", default=PILOT_SEEDS)
    parser.add_argument(
        "--head-lrs", type=float, nargs="+", default=(0.001, 0.003, 0.01)
    )
    parser.add_argument("--control-plan", type=Path)
    args = parser.parse_args(argv)
    result = fit_grid(
        args.records,
        args.records_sha256,
        args.output_root,
        python=args.python,
        seeds=args.seeds,
        head_lrs=args.head_lrs,
        control_plan=args.control_plan,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    digest = atomic_json(args.manifest, result)
    index_path = args.index or args.manifest.with_name(
        args.manifest.stem + ".index.json"
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_digest = atomic_json(index_path, model_index(result))
    print(
        json.dumps(
            {
                "manifest": str(args.manifest),
                "sha256": digest,
                "index": str(index_path),
                "index_sha256": index_digest,
                "counts": result["counts"],
                "executed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
