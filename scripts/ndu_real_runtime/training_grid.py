"""Generate a complete matched fit inventory; this module executes no fits."""

import argparse
import json
from pathlib import Path
import sys

from .controllers import ControlPlan
from .fit_loop import OBSERVATION_POLICIES
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
    control_plans=None,
    observation_policy="legacy",
    regimes=("frozen", "joint"),
    controllers=JOINT_CONTROLLERS,
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
    if (
        observation_policy not in OBSERVATION_POLICIES
        or not regimes
        or len(set(regimes)) != len(regimes)
        or set(regimes) - {"frozen", "joint"}
        or not controllers
        or len(set(controllers)) != len(controllers)
        or set(controllers) - set(JOINT_CONTROLLERS)
    ):
        raise ValueError("Invalid bounded training policy, regimes or controllers")
    paired = control_plans is not None
    if paired and (
        control_plan is not None
        or set(control_plans) != {"reset", "persistent"}
        or observation_policy != "matched_episodes"
    ):
        raise ValueError("Paired memory plans require the explicit matched policy")
    memory_plans, common_plans = {}, []
    for mode, path in (
        [(mode, control_plans[mode]) for mode in ("reset", "persistent")]
        if paired
        else [(None, control_plan)]
    ):
        if path is None:
            memory_plans["reset"] = None
            continue
        if not Path(path).is_absolute():
            raise ValueError("Control plan needs an absolute source path")
        value = json.loads(Path(path).read_text())
        control = ControlPlan(**value["control"])
        if mode is not None and mode != control.memory_mode:
            raise ValueError("Control plan and paired memory mode differ")
        memory_plans[control.memory_mode] = path
        common_plans.append(
            {**value, "control": {**value["control"], "memory_mode": "paired"}}
        )
    if paired and common_plans[0] != common_plans[1]:
        raise ValueError("Paired plans may differ only in memory_mode")
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
        "observation_policy": observation_policy,
        "memory_modes": list(memory_plans),
        "regimes": list(regimes),
        "controllers": list(controllers),
    }
    prefix = "fit-grid-" + canonical_sha(intent)[:20]
    if control_plan is not None:
        if not Path(control_plan).is_absolute():
            raise ValueError("Control plan needs an absolute source path")
        intent.update(
            control_plan=str(control_plan), control_plan_sha256=file_sha(control_plan)
        )
        prefix = "fit-grid-" + canonical_sha(intent)[:20]
    if paired:
        intent["control_plans"] = {
            mode: {"path": str(path), "sha256": file_sha(path)}
            for mode, path in memory_plans.items()
        }
        prefix = "fit-grid-" + canonical_sha(intent)[:20]
    jobs = []

    def add(
        seed,
        core,
        mode,
        phase,
        regime,
        controller,
        lr,
        pretrained=None,
        trial_index=None,
    ):
        stem = f"s{seed}/{core}" + (f"/{mode}" if paired else "")
        name = (
            f"{stem}/{phase}"
            if phase == "content"
            else f"{stem}/{regime}-{controller}/lr-{lr:g}"
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
        path = memory_plans[mode]
        if path is not None:
            argv += ["--control-plan", str(path)]
        if observation_policy != "legacy":
            argv += ["--observation-policy", observation_policy]
        argv += ["--memory-mode", mode]
        if phase == "content":
            argv.append("--content-only")
        else:
            argv += ["--pretrained", pretrained["output"]]
        row = {
            "job_id": identity,
            "source_pins": dict(intent["source_pins"]),
            "status": "PLANNED_NOT_EXECUTED",
            "seed": seed,
            "core": core,
            "memory_mode": mode,
            "observation_policy": observation_policy,
            "paired_memory_group": f"s{seed}/{core}/{phase}/{regime}/{controller}/{lr:g}",
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
            "shared_by_controllers": list(controllers)
            if regime == "frozen" and phase == "fit"
            else [],
            "costs": None,
            "scientific_admission": "HOLD",
        }
        jobs.append(row)
        return row

    for seed in seeds:
        for core in ("ordinary", "hepta"):
            for mode in memory_plans:
                pretrained = add(
                    seed, core, mode, "content", "frozen", "shared", config.content_lr
                )
                for trial_index, lr in enumerate(head_lrs):
                    for regime in regimes:
                        for controller in (
                            controllers if regime == "joint" else ("shared",)
                        ):
                            add(
                                seed,
                                core,
                                mode,
                                "fit",
                                regime,
                                controller,
                                lr,
                                pretrained,
                                trial_index,
                            )
    if len({job["job_id"] for job in jobs}) != len(jobs):
        raise ValueError(
            "LR path formatting collides; every original job needs a unique identity"
        )
    return {
        "schema": "ndu.real.fit-grid.v2" if paired else "ndu.real.fit-grid.v1",
        "intent": intent,
        "grid_id": prefix,
        "counts": {
            "independent_seed_groups": len(seeds),
            "content": sum(j["phase"] == "content" for j in jobs),
            "frozen_shared": sum(
                j["phase"] == "fit" and j["regime"] == "frozen" for j in jobs
            ),
            "joint": sum(j["phase"] == "fit" and j["regime"] == "joint" for j in jobs),
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
            "memory_mode": job["memory_mode"],
            "observation_policy": job["observation_policy"],
            "paired_memory_group": job["paired_memory_group"],
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
    parser.add_argument("--memory-plans", type=Path)
    parser.add_argument(
        "--observation-policy", choices=OBSERVATION_POLICIES, default="legacy"
    )
    parser.add_argument(
        "--regimes", choices=("frozen", "joint"), nargs="+", default=("frozen", "joint")
    )
    parser.add_argument(
        "--controllers", choices=JOINT_CONTROLLERS, nargs="+", default=JOINT_CONTROLLERS
    )
    args = parser.parse_args(argv)
    result = fit_grid(
        args.records,
        args.records_sha256,
        args.output_root,
        python=args.python,
        seeds=args.seeds,
        head_lrs=args.head_lrs,
        control_plan=args.control_plan,
        control_plans=None
        if args.memory_plans is None
        else json.loads(args.memory_plans.read_text()),
        observation_policy=args.observation_policy,
        regimes=args.regimes,
        controllers=args.controllers,
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
