"""Numeric parameter-memory rate/distortion and complete artifact accounting.

The written facts are training data. Selection and hidden *read coordinates*
are disjoint; this is neither forecasting nor unseen-fact generalization.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .capacity_models import (
    allocate_partition,
    coordinate_split,
    equal_work_control,
    fit_partition,
    fit_work,
    kmeans_routes,
)
from .capacity_io import (
    datasets,
    metrics,
    prepare_archives,
    read_requests,
    source_codec_curve,
    write_bytes,
    write_json,
)
from .codec import decode_factor, encode_factor
from .factor_cell import FactorBank


DEFAULTS = {
    "budget_fractions_int32": [0.125, 0.25, 0.5, 1.0],
    "numeric_domains": ["co2", "temperature", "sunspots"],
    "synthetic_rows": 256,
    "synthetic_columns": 24,
    "random_mix": [0.0, 0.25, 0.5, 1.0],
    "cells": 4,
    "kmeans_iterations": 20,
    "selection_fraction": 0.2,
    "max_vq_cells": 256,
    "hidden_query_limit": 512,
    "include_digits": True,
    "same_work_max_repeats": 1024,
}


def add_work(total, work):
    for key in (
        "candidate_fits",
        "svd_calls",
        "svd_work_proxy",
        "fit_wall_seconds",
        "kmeans_distance_component_terms",
        "kmeans_iterations",
    ):
        total[key] = total.get(key, 0) + work[key]


def run_capacity(protocol, output, source_commit, seeds, *, development=False):
    settings = DEFAULTS | protocol.get("capacity", {})
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_dir = Path(
        protocol.get(
            "numeric_source_dir",
            Path(__file__).resolve().parents[1] / "sources" / "numeric",
        )
    )
    started = time.perf_counter()
    requests, records, expected, data_records, total_work = [], [], {}, [], {}
    encoder_work = {
        "strong_exact_baselines_seconds": 0.0,
        "global_source_codec_search_seconds": 0.0,
        "selected_source_archive_seconds": 0.0,
    }
    extra_control_fits = 0
    for name, values, declared, metadata, scale, data_seeds in datasets(
        source_dir, settings, seeds
    ):
        directory = output / name
        directory.mkdir(parents=True, exist_ok=True)
        archives = prepare_archives(directory, values, metadata)
        encoder_work["strong_exact_baselines_seconds"] += archives[
            "codec_search_encode_seconds"
        ]
        best_exact = archives["strongest_exact_baseline"]["archive_bytes"]
        data_records.append(
            {
                "name": name,
                "shape": list(values.shape),
                "scale": scale,
                "archives": archives,
            }
        )
        budgets = sorted(
            set(
                max(1, int(values.nbytes * fraction))
                for fraction in settings["budget_fractions_int32"]
            )
        )
        for seed in data_seeds:
            selection, hidden = coordinate_split(
                values.shape, seed, settings["selection_fraction"]
            )
            coordinates = np.flatnonzero(hidden)
            coordinates = np.random.default_rng(seed + 101).permutation(coordinates)[
                : settings["hidden_query_limit"]
            ]
            query_rows, query_columns = np.unravel_index(coordinates, values.shape)
            base = directory / ("seed-" + str(seed))
            base.mkdir(parents=True, exist_ok=True)
            write_json(
                base / "query-split.json",
                {
                    "selection_sha256": hashlib.sha256(
                        np.packbits(selection).tobytes()
                    ).hexdigest(),
                    "selection_count": int(selection.sum()),
                    "hidden_count": len(coordinates),
                    "hidden_rows": query_rows.tolist(),
                    "hidden_columns": query_columns.tolist(),
                    "selection_hidden_overlap": False,
                },
            )
            n = len(values)
            groups = min(settings["cells"], n)
            random_routes = np.arange(n) % groups
            np.random.default_rng(seed + 17).shuffle(random_routes)
            learned, route_receipt = kmeans_routes(
                values, groups, seed, settings["kmeans_iterations"]
            )
            routes = {
                "global_svd": np.zeros(n, dtype=np.uint8),
                "predeclared_cells": declared,
                "random_cells": random_routes,
                "learned_cells": learned,
            }
            families = {
                key: fit_partition(values, route, selection, seed=seed)
                for key, route in routes.items()
            }
            work = {
                key: fit_work(
                    fitted["receipts"],
                    [route_receipt] if key == "learned_cells" else [],
                )
                for key, fitted in families.items()
            }
            for family_work in work.values():
                add_work(total_work, family_work)
            write_json(
                base / "candidate-fit-work.json",
                {
                    "families": {
                        key: {
                            "work": work[key],
                            "candidate_receipts": fitted["receipts"],
                            "cached_candidate_parameter_bytes": fitted[
                                "cached_parameter_bytes"
                            ],
                        }
                        for key, fitted in families.items()
                    },
                    "learned_partition": route_receipt,
                    "written_facts_visible_at_training": True,
                    "selection_uses_only_declared_coordinates": True,
                    "hidden_targets_used_for_selection": False,
                },
            )
            codec_best = source_codec_curve(
                base,
                values,
                families["global_svd"],
                archives["address_provenance_bytes"],
                best_exact,
            )
            encoder_work["global_source_codec_search_seconds"] += codec_best[
                "selection_search_encode_seconds"
            ]
            data_records[-1].setdefault("best_source_codecs_by_seed", {})[str(seed)] = (
                codec_best
            )
            vq_candidates, vq_fit_receipts, vq_route_receipts = [], [], []
            maximum = min(settings["max_vq_cells"], n, 256)
            largest_feasible = [
                k
                for k in range(1, maximum + 1)
                if 20
                + (n * (k - 1).bit_length() + 7) // 8
                + k * (8 + 4 * values.shape[1])
                <= max(budgets)
            ]
            maximum = max(largest_feasible) if largest_feasible else 1
            vq_sizes = {1, 2, 4, 8, 16, 32, 64, 128, maximum}
            for budget in budgets:
                feasible = [
                    k
                    for k in range(1, maximum + 1)
                    if 20
                    + (n * (k - 1).bit_length() + 7) // 8
                    + k * (8 + 4 * values.shape[1])
                    <= budget
                ]
                if feasible:
                    vq_sizes.add(max(feasible))
            for cells in sorted(k for k in vq_sizes if 1 <= k <= maximum):
                route, receipt = kmeans_routes(
                    values, cells, seed + cells, settings["kmeans_iterations"]
                )
                fitted = fit_partition(
                    values, route, selection, seed=seed, rank_limit=0
                )
                vq_route_receipts.append(receipt)
                vq_fit_receipts.extend(fitted["receipts"])
                allocated = allocate_partition(fitted, values.nbytes * 10 + 65536)
                vq_candidates.append(allocated)
            vq_work = fit_work(vq_fit_receipts, vq_route_receipts)
            add_work(total_work, vq_work)
            write_json(
                base / "vq-fit-work.json",
                {
                    "work": vq_work,
                    "route_receipts": vq_route_receipts,
                    "factor_receipts": vq_fit_receipts,
                },
            )
            for budget in budgets:
                allocations = {
                    key: allocate_partition(fitted, budget)
                    for key, fitted in families.items()
                }
                feasible_vq = [
                    (b, r) for b, r in vq_candidates if len(b.to_bytes()) <= budget
                ]
                allocations["learned_vq"] = (
                    min(
                        feasible_vq,
                        key=lambda pair: (
                            pair[1]["selection_squared_error"],
                            len(pair[0].to_bytes()),
                        ),
                    )
                    if feasible_vq
                    else None
                )
                global_bank = (
                    allocations["global_svd"][0] if allocations["global_svd"] else None
                )
                for family, allocation in allocations.items():
                    if allocation is None:
                        records.append(
                            {
                                "dataset": name,
                                "seed": seed,
                                "family": family,
                                "budget_bytes": budget,
                                "feasible": False,
                            }
                        )
                        continue
                    bank, selection_receipt = allocation
                    if family == "learned_vq":
                        selection_receipt = selection_receipt | {
                            "budget_bytes": budget,
                            "unused_budget_bytes": budget - len(bank.to_bytes()),
                        }
                    identifier = (
                        name + "/" + str(seed) + "/" + str(budget) + "/" + family
                    )
                    path = base / (str(budget) + "-" + family + ".bin")
                    bank.save(path)
                    archive, codec = encode_factor(bank, values)
                    encoder_work["selected_source_archive_seconds"] += codec[
                        "encode_seconds"
                    ]
                    write_bytes(path.with_suffix(".residual"), archive)
                    loaded = FactorBank.load(path, bank.digest)
                    restored, mask = decode_factor(
                        archive, model=loaded, expected_sha256=codec["archive_sha256"]
                    )
                    if not np.array_equal(restored, values) or not mask.all():
                        raise RuntimeError(
                            "retained replay state failed exact recovery"
                        )
                    candidate_work = vq_work if family == "learned_vq" else work[family]
                    control = (
                        equal_work_control(
                            values,
                            global_bank,
                            work["global_svd"],
                            candidate_work,
                            settings["same_work_max_repeats"],
                        )
                        if family != "global_svd" and global_bank is not None
                        else None
                    )
                    if control is not None:
                        write_json(path.with_suffix(".control.json"), control)
                        add_work(total_work, fit_work(control["receipts"]))
                        extra_control_fits += control["extra_fits"]
                    record = {
                        "id": identifier,
                        "dataset": name,
                        "seed": seed,
                        "family": family,
                        "feasible": True,
                        "budget_bytes": budget,
                        "artifact_bytes": len(bank.to_bytes()),
                        "parameter_bytes": bank.parameter_bytes,
                        "complete_parameter_read_bytes": len(bank.to_bytes())
                        + archives["address_provenance_bytes"],
                        "complete_exact_replay_bytes": codec[
                            "complete_standalone_bytes"
                        ]
                        + archives["address_provenance_bytes"],
                        "strong_exact_baseline_bytes": best_exact
                        + archives["address_provenance_bytes"],
                        "source_codec_receipt": codec,
                        "selection": selection_receipt,
                        "all_candidate_fit_work": candidate_work,
                        "same_work_global_control": None
                        if control is None
                        else {k: v for k, v in control.items() if k != "receipts"},
                        "route_semantics": "Explicit serialized row-address route; actual address route equals declared route by construction. Semantic routing is tested in the separate graph study.",
                        "source_free_reload_verified": True,
                    }
                    records.append(record)
                    requests.append(
                        {
                            "id": identifier,
                            "artifact": str(path),
                            "sha256": bank.digest,
                            "rows": query_rows.tolist(),
                            "columns": query_columns.tolist(),
                        }
                    )
                    expected[identifier] = (
                        values[query_rows, query_columns],
                        scale,
                        float(np.var(values.astype(np.float64))),
                    )
    request_path, answer_path = (
        output / "isolated-read-requests.json",
        output / "isolated-read-results.json",
    )
    write_json(request_path, requests)
    environment = os.environ.copy()
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["PYTHONPATH"] = (
        str(Path(__file__).resolve().parents[1])
        + os.pathsep
        + environment.get("PYTHONPATH", "")
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "v3.capacity_study",
            "--read-requests",
            str(request_path),
            "--read-output",
            str(answer_path),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    by_id = {
        item["id"]: item for item in json.loads(answer_path.read_bytes())["results"]
    }
    for record in records:
        if record["feasible"]:
            result = by_id[record["id"]]
            record["hidden"] = metrics(result["answers"], *expected[record["id"]])
            record["read_seconds"] = result["read_seconds"]
            record["resident_model_array_bytes"] = result["resident_model_array_bytes"]
    for dataset in data_records:
        candidates = [
            r for r in records if r["dataset"] == dataset["name"] and r["feasible"]
        ]
        best = min(candidates, key=lambda r: r["complete_exact_replay_bytes"])
        dataset["best_selected_family_exact_replay"] = {
            "id": best["id"],
            "family": best["family"],
            "complete_stored_bytes": best["complete_exact_replay_bytes"],
            "strong_exact_baseline_bytes": best["strong_exact_baseline_bytes"],
            "parameter_only_exact_accuracy": best["hidden"]["exact_accuracy"],
            "selection_scope": "Minimum exact archive bytes among all actually fitted byte-budget candidates; original parameter candidates were chosen on selection-coordinate distortion.",
        }
    summary = {
        "schema": "memory-cell-v3.capacity-study.v1",
        "development": bool(development),
        "source_commit": source_commit,
        "settings": settings,
        "seeds": list(seeds),
        "datasets": data_records,
        "records": records,
        "claims_scope": [
            "Coordinate-addressed memory of previously written numerical facts; not future forecasting or unseen-fact prediction.",
            "Latents, decoder weights, centers, routes, masks, artifact headers and address/provenance metadata are charged.",
            "Parameter-only reads never load residuals or exact source archives. Exact replay uses explicit residual storage and is reported separately.",
            "Same-work controls actually repeat global SVD and report work/time coverage; repeated deterministic fitting is not independent learning evidence.",
            "Model family comparisons do not prove dominance over every possible single-model function.",
            "Research evidence, retained candidate receipts, all model alternatives and read-answer evidence are counted separately from one selected deployment.",
        ],
        "research_output_bytes_before_summary": sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
    }
    summary["actual_total_training_work"] = total_work | {
        "extra_control_fits": extra_control_fits,
        "accounting": "Each candidate fit and actual extra control fit is counted once. Per-model candidate-work receipts refer to reused searches and must not be added again across budgets.",
    }
    summary["actual_encoder_work"] = encoder_work
    summary["total_wall_seconds"] = time.perf_counter() - started
    write_json(output / "capacity-summary.json", summary)
    return summary


def run_study(
    output_dir, source_dir, seeds=(8011,), profile="development", include_digits=True
):
    return run_capacity(
        {
            "numeric_source_dir": str(source_dir),
            "capacity": {"include_digits": include_digits},
        },
        output_dir,
        "development-unfrozen",
        seeds,
        development=profile == "development",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument(
        "--source-dir",
        default=str(Path(__file__).resolve().parents[1] / "sources" / "numeric"),
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[8011, 8017])
    parser.add_argument(
        "--profile", choices=["development", "formal"], default="development"
    )
    parser.add_argument("--protocol")
    parser.add_argument("--source-commit", default="development-unfrozen")
    parser.add_argument("--no-digits", action="store_true")
    parser.add_argument("--read-requests")
    parser.add_argument("--read-output")
    args = parser.parse_args()
    if args.read_requests:
        if not args.read_output:
            parser.error("isolated read requires --read-output")
        read_requests(args.read_requests, args.read_output)
        return
    if not args.output:
        parser.error("capacity study requires --output")
    protocol = json.loads(Path(args.protocol).read_bytes()) if args.protocol else {}
    protocol["numeric_source_dir"] = args.source_dir
    protocol.setdefault("capacity", {})["include_digits"] = not args.no_digits
    summary = run_capacity(
        protocol,
        args.output,
        args.source_commit,
        args.seeds,
        development=args.profile == "development",
    )
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "records": len(summary["records"]),
                "datasets": len(summary["datasets"]),
            }
        )
    )


if __name__ == "__main__":
    main()
