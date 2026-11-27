"""Crossed data/init/order diagnostics on new train/dev material only.

No confirmation runner is imported. Reused factor levels are deliberately
dependent: this program reports descriptive decompositions, never seed p-values.
All files are create-only; failed fits retain their identity and consumed work.
"""

import argparse
import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
from time import perf_counter, process_time

import numpy as np

from .crossed_design import canonical, decompose, design_cells, validate_config
from .crossed_training_fit import _write, fit
from .simulator import generate_dataset


def _source():
    names = (
        "__init__.py",
        "contracts.py",
        "crossed_design.py",
        "crossed_training.py",
        "crossed_training_fit.py",
        "evaluation.py",
        "models.py",
        "preparation.py",
        "simulator.py",
    )
    return {name: (Path(__file__).parent / name).read_bytes() for name in names}


def _summaries(config, records):
    dims = tuple(
        len(config[key]) for key in ("data_seeds", "init_seeds", "order_seeds")
    )
    cells = design_cells(config)
    lookup = {
        (r["variant"], r["data_seed"], r["init_seed"], r["order_seed"]): r
        for r in records
    }
    metrics = {
        "dev_observed_nll": lambda r: r["dev_observed_nll"],
        "legacy_dev_net_utility": lambda r: r["dev"]["net_utility"],
        "expanded_cheap_fixed1_net_utility": lambda r: r["resource_panels"][
            "expanded_resources"
        ]["arms"]["fixed_1_cheap"]["expected_net_utility"],
        "expanded_adaptive_net_utility": lambda r: r["resource_panels"][
            "expanded_resources"
        ]["arms"]["adaptive_shared_panel"]["expected_net_utility"],
    }
    arrays = {
        variant: {
            key: np.asarray([get(lookup[(variant, *cell)]) for cell in cells]).reshape(
                dims
            )
            for key, get in metrics.items()
        }
        for variant in config["variants"]
    }
    comparisons = {}
    if "gru" in arrays:
        for other in ("single_step", "gru_reset", "gru_no_action", "gru_no_time"):
            if other in arrays:
                comparisons["gru_minus_" + other] = {
                    key: decompose(arrays["gru"][key] - arrays[other][key])
                    for key in metrics
                }
    return {
        "per_variant": {
            v: {k: decompose(a) for k, a in values.items()}
            for v, values in arrays.items()
        },
        "paired_factor_cell_differences": comparisons,
        "inference": "Descriptive crossed factors; shared levels are dependent; no hypothesis test or promotion.",
    }


def run(config, output):
    """Execute a frozen train/dev design; return COMPLETE or retained INCOMPLETE."""
    start_wall, start_cpu = perf_counter(), process_time()
    config = copy.deepcopy(config)
    validate_config(config)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    files = _source()
    manifest = {name: sha256(data).hexdigest() for name, data in files.items()}
    _write(out / "config.json", config)
    _write(
        out / "attempt.json",
        {
            "schema": config["schema"],
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config_sha256": sha256(canonical(config).encode()).hexdigest(),
            "source_sha256": manifest,
            "base_commit": config["base_commit"],
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "thread_environment": {
                    k: os.environ.get(k)
                    for k in (
                        "OPENBLAS_NUM_THREADS",
                        "OMP_NUM_THREADS",
                        "MKL_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS",
                    )
                },
            },
            "confirmation_data_read": False,
            "confirmation_samples_generated": 0,
            "scope": "new train/dev finite simulator; expanded resources are a declared intervention, not a new task",
        },
    )
    snapshot = out / "source"
    snapshot.mkdir()
    for name, data in files.items():
        with (snapshot / name).open("xb") as stream:
            stream.write(data)
    fit_dir = out / "fits"
    fit_dir.mkdir()
    records, datasets, failures = [], {}, []
    for data_seed in config["data_seeds"]:
        wall, cpu = perf_counter(), process_time()
        try:
            train = generate_dataset(
                config["train_episodes"], data_seed, "train", config["history_length"]
            )
            dev = generate_dataset(
                config["dev_episodes"], data_seed, "dev", config["history_length"]
            )
            if set(train.groups) & set(dev.groups):
                raise AssertionError("train/dev groups overlap")
            datasets[str(data_seed)] = {
                "train_sha256": train.fingerprint(),
                "dev_sha256": dev.fingerprint(),
                "train_episodes": len(train.x),
                "dev_episodes": len(dev.x),
                "generation_wall_seconds": perf_counter() - wall,
                "generation_process_cpu_seconds": process_time() - cpu,
                "train_observation_counts": train.observation_counts,
                "dev_observation_counts": dev.observation_counts,
            }
            _write(out / f"dataset-{data_seed}.json", datasets[str(data_seed)])
        except Exception as error:
            failure = dict(
                data_seed=data_seed,
                error_type=type(error).__name__,
                error=str(error),
                generation_wall_seconds=perf_counter() - wall,
                generation_process_cpu_seconds=process_time() - cpu,
            )
            _write(out / f"dataset-{data_seed}.failed.json", failure)
            failures.append(failure)
            continue
        for seeds in (cell for cell in design_cells(config) if cell[0] == data_seed):
            for variant in config["variants"]:
                record = fit(config, variant, seeds, train, dev, fit_dir)
                records.append(record)
                print(
                    json.dumps(
                        {
                            key: record[key]
                            for key in (
                                "variant",
                                "data_seed",
                                "init_seed",
                                "order_seed",
                                "status",
                            )
                        }
                    ),
                    flush=True,
                )
                if record["status"] != "COMPLETE":
                    failures.append(
                        {
                            k: record[k]
                            for k in (
                                "variant",
                                "data_seed",
                                "init_seed",
                                "order_seed",
                                "error",
                            )
                        }
                    )
    source_unchanged = manifest == {
        name: sha256(data).hexdigest() for name, data in _source().items()
    }
    expected = len(design_cells(config)) * len(config["variants"])
    complete = not failures and source_unchanged and len(records) == expected
    summary = None
    if complete:
        try:
            summary = _summaries(config, records)
        except Exception as error:
            failures.append(
                dict(
                    stage="descriptive_summary",
                    error_type=type(error).__name__,
                    error=str(error),
                )
            )
            complete = False
    result = {
        "schema": "pred1-crossed-training-result-v1",
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "qualification": "HOLD_UNCHANGED",
        "expected_fits": expected,
        "completed_fits": sum(r["status"] == "COMPLETE" for r in records),
        "failed_fits": sum(r["status"] == "FAILED" for r in records),
        "failures": failures,
        "unstarted_fits": expected - len(records),
        "source_unchanged": source_unchanged,
        "datasets": datasets,
        "confirmation_data_read": False,
        "confirmation_samples_generated": 0,
        "summary": summary,
        "wall_seconds": perf_counter() - start_wall,
        "process_cpu_seconds": process_time() - start_cpu,
        "physical_cost_complete": False,
        "energy_joules": None,
        "financial_cost": None,
        "timing_scope": "run entry to before final result serialization; excludes import/startup; phase times nested",
    }
    _write(out / "RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.config.read_text(encoding="utf-8")), args.output)
    print(
        canonical(
            {
                k: result[k]
                for k in ("status", "completed_fits", "expected_fits", "qualification")
            }
        )
    )
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
