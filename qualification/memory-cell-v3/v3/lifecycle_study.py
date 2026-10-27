"""Measure additions, corrections, withdrawal, replay, and owner recovery.

Numeric corrections below are explicitly injected qualification events, not
claims that any scientific publisher changed its observations. Parameter-only
distortion is always separate from the exact model-plus-residual replay arm.
"""

import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .codec import decode_factor
from .lifecycle import FactorOwner, canonical, prepare_version, sha


PACKAGE = Path(__file__).resolve().parents[1]


def write_json(path, value):
    Path(path).write_bytes(canonical(value))


def evaluate(predictions, targets, available, scale):
    values = np.asarray([0 if v is None else v for v in predictions], dtype=np.float64)
    known = np.asarray([v is not None for v in predictions])
    available = np.asarray(available, dtype=bool)
    error = values[available] - np.asarray(targets)[available]
    accepted = known[available]
    return {
        "queries": int(available.sum()),
        "coverage": float(accepted.mean()) if len(accepted) else None,
        "exact_accuracy": float(np.mean(accepted & (error == 0)))
        if len(error)
        else None,
        "mae_original_units": float(np.mean(np.abs(error[accepted])) / scale)
        if accepted.any()
        else None,
        "rmse_original_units": float(np.sqrt(np.mean(error[accepted] ** 2)) / scale)
        if accepted.any()
        else None,
        "revoked_queries": int((~available).sum()),
        "revoked_refusals": int((~available & ~known).sum()),
    }


def failure_probe(callback):
    try:
        callback()
    except ValueError as error:
        return {"rejected": True, "reason": str(error)}
    return {"rejected": False}


def domain_run(source, output, *, seed, rank, correction_count, revocation_count):
    output.mkdir(parents=True, exist_ok=False)
    original = np.asarray(source["values"], dtype=np.int32)
    years, domain, scale = source["years"], source["domain"], source["scale"]
    n, d = original.shape
    initial_rows = max(2, int(n * 0.6))
    rng = np.random.default_rng(seed)
    choices = rng.choice(n * d, correction_count + revocation_count, replace=False)
    corrections, revocations = choices[:correction_count], choices[correction_count:]
    changed = original.copy()
    for index, coordinate in enumerate(corrections):
        changed.ravel()[coordinate] += scale * (1 + index % 5)
    withdrawn, mask = changed.copy(), np.ones_like(original, dtype=bool)
    withdrawn.ravel()[revocations] = 0
    mask.ravel()[revocations] = False
    stages = [
        (
            "initial",
            original[:initial_rows],
            np.ones((initial_rows, d), dtype=bool),
            years[:initial_rows],
        ),
        ("append", original, np.ones_like(original, dtype=bool), years),
        ("correct", changed, np.ones_like(original, dtype=bool), years),
        ("withdraw", withdrawn, mask, years),
        ("clean_replay", withdrawn, mask, years),
    ]
    owner_root = output / "owner"
    witness = output / "witness" / "current.json"
    owner = FactorOwner(owner_root, witness, scope=domain)
    records, old_pointer, previous = [], None, None
    started = time.perf_counter()
    for generation, (name, matrix, available, address_years) in enumerate(stages, 1):
        replay_receipt = None
        if name == "clean_replay":
            active = owner.recover()
            version = owner_root / "versions" / str(generation - 1)
            matrix, available = decode_factor(
                (version / "residual.codec").read_bytes(),
                model=owner._bank,
                expected_sha256=active["residual_sha256"],
            )
            if not np.array_equal(matrix, withdrawn) or not np.array_equal(
                available, mask
            ):
                raise AssertionError("lossless replay changed valid source frontier")
            replay_receipt = {
                "from": "matching prior artifact plus explicit residual",
                "original_source_file_read_for_replay": False,
                "invalid_source_coordinates_excluded": len(revocations),
                "previous_weights_used_for_initialization": False,
            }
        manifest, preparation = prepare_version(
            owner_root,
            scope=domain,
            generation=generation,
            years=address_years,
            matrix=matrix,
            mask=available,
            rank=rank,
            seed=seed,
        )
        publish_start = time.perf_counter()
        owner.publish(generation, expected_generation=generation - 1)
        publication_seconds = time.perf_counter() - publish_start
        owner = FactorOwner(owner_root, witness, scope=domain)
        coordinates = [
            (year, month) for year in address_years for month in range(1, d + 1)
        ]
        read_start = time.perf_counter()
        parameters = owner.read(coordinates, generation=generation)
        exact = owner.read(coordinates, generation=generation, mode="lossless_codec")
        read_seconds = time.perf_counter() - read_start
        targets, known = matrix.ravel(), available.ravel()
        if exact != [
            int(v) if valid else None for v, valid in zip(targets, known, strict=True)
        ]:
            raise AssertionError("active lossless memory differs from valid writes")
        retained = None
        if previous is not None:
            before = {tuple(row["address"]): row for row in previous}
            after = {
                coordinate: (target, valid, prediction)
                for coordinate, target, valid, prediction in zip(
                    coordinates, targets, known, parameters, strict=True
                )
            }
            overlap = [
                (row, after[address])
                for address, row in before.items()
                if address in after
                and row["valid"]
                and after[address][1]
                and row["target"] == after[address][0]
            ]
            old_error = np.asarray(
                [row["parameter_prediction"] - row["target"] for row, _ in overlap]
            )
            new_error = np.asarray([int(new[2]) - int(new[0]) for _, new in overlap])
            retained = {
                "unmodified_valid_old_coordinates": len(overlap),
                "parameter_old_mae_before": float(np.mean(np.abs(old_error)) / scale),
                "parameter_old_mae_after": float(np.mean(np.abs(new_error)) / scale),
                "parameter_old_exact_before": float(np.mean(old_error == 0)),
                "parameter_old_exact_after": float(np.mean(new_error == 0)),
                "lossless_old_retention": 1.0,
            }
        rows = [
            {
                "address": list(address),
                "valid": bool(valid),
                "target": int(target) if valid else None,
                "parameter_prediction": p,
                "lossless_prediction": e,
            }
            for address, valid, target, p, e in zip(
                coordinates, known, targets, parameters, exact, strict=True
            )
        ]
        write_json(output / f"{generation}-{name}-predictions.json", rows)
        previous = rows
        record = {
            "stage": name,
            "generation": generation,
            "manifest": manifest,
            "preparation": preparation,
            "parameter_metrics": evaluate(parameters, targets, known, scale),
            "lossless_metrics": evaluate(exact, targets, known, scale),
            "old_retention": retained,
            "replay": replay_receipt,
            "publication_seconds": publication_seconds,
            "reads_and_owner_validation_seconds": read_seconds,
            "resident_parameter_bytes": owner._bank.parameter_bytes
            + owner._bank.routes.nbytes
            + owner._bank.mask.nbytes,
            "resident_decoded_exact_cache_bytes": sum(
                array.nbytes for array in owner._exact
            ),
            "owner_and_history_retained_bytes": sum(
                p.stat().st_size for p in owner_root.rglob("*") if p.is_file()
            )
            + witness.stat().st_size,
        }
        if name == "initial":
            unknown = [(year, 1) for year in years[initial_rows:]]
            record["unwritten_new_addresses_refused"] = sum(
                v is None for v in owner.read(unknown, generation=generation)
            )
            record["unwritten_new_addresses"] = len(unknown)
            old_pointer = (owner_root / "active.json").read_bytes()
        if name == "correct":
            record["corrected_parameter_exact"] = sum(
                parameters[int(i)] == int(changed.ravel()[i]) for i in corrections
            )
            record["corrected_lossless_exact"] = sum(
                exact[int(i)] == int(changed.ravel()[i]) for i in corrections
            )
            record["correction_count"] = len(corrections)
        records.append(record)
    latest = owner.recover()
    current_pointer = (owner_root / "active.json").read_bytes()
    faults = {
        "stale_generation": failure_probe(
            lambda: owner.read([(years[0], 1)], generation=1)
        ),
        "wrong_artifact": failure_probe(
            lambda: owner.admission_check(5, "c01", "0" * 64, latest["frontier_sha256"])
        ),
        "wrong_frontier": failure_probe(
            lambda: owner.admission_check(5, "c01", latest["model_sha256"], "0" * 64)
        ),
    }
    try:
        (owner_root / "active.json").write_bytes(old_pointer)
        faults["rollback_pointer"] = failure_probe(lambda: owner.recover())
    finally:
        (owner_root / "active.json").write_bytes(current_pointer)
    model_path = owner_root / "versions" / "5" / "memory.factor"
    raw = model_path.read_bytes()
    try:
        damaged = raw[:-1] + bytes([raw[-1] ^ 1])
        model_path.write_bytes(damaged)
        faults["tampered_artifact"] = {
            **failure_probe(lambda: owner.read([(years[0], 1)], generation=5)),
            "damaged_sha256": sha(damaged),
        }
    finally:
        model_path.write_bytes(raw)
    owner.recover()
    final_coordinates = [(year, month) for year in years for month in range(1, d + 1)]
    request_path = output / "fresh-queries.json"
    write_json(
        request_path,
        {"scope": domain, "generation": 5, "coordinates": final_coordinates},
    )
    fresh, processes = {}, []
    for mode in ("parameters", "lossless_codec"):
        response_path = output / f"fresh-{mode}-predictions.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(PACKAGE / "owner_reader.py"),
                "--owner",
                str(owner_root),
                "--witness",
                str(witness),
                "--queries",
                str(request_path),
                "--output",
                str(response_path),
                "--mode",
                mode,
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=120,
        )
        response = json.loads(response_path.read_text())
        fresh[mode] = response["predictions"]
        processes.append(
            {
                "mode": mode,
                "returncode": completed.returncode,
                "residual_loaded": response["residual_loaded"],
                "resident_decoded_exact_cache_bytes": response[
                    "resident_decoded_exact_cache_bytes"
                ],
                "process_id": response["process_id"],
            }
        )
    parity = fresh["parameters"] == [
        row["parameter_prediction"] for row in previous
    ] and fresh["lossless_codec"] == [row["lossless_prediction"] for row in previous]
    if not parity:
        raise AssertionError("fresh-process read changed numeric memory output")
    raw_deleted = owner._bank.reconstruct().ravel()[revocations]
    old_values = changed.ravel()[revocations]
    summary = {
        "domain": domain,
        "seed": seed,
        "stages": records,
        "faults": faults,
        "all_faults_rejected": all(row["rejected"] for row in faults.values()),
        "fresh_process": {
            "parity": parity,
            "queries": len(final_coordinates),
            "prediction_modes": 2,
            "processes": processes,
            "target_values_in_request": False,
        },
        "raw_deleted_coordinate_audit": {
            "coordinates": len(revocations),
            "coincidental_old_value_matches": int(np.sum(raw_deleted == old_values)),
            "serving_refusals": sum(
                fresh["parameters"][int(i)] is None for i in revocations
            ),
            "weight_unlearning_proven": False,
            "old_immutable_artifacts_retained_for_audit": True,
        },
        "qualification_wall_seconds": time.perf_counter() - started,
        "control_plane_limit": "single writer; external witness must be protected against joint rollback; no distributed consensus or complete erasure claim",
    }
    write_json(output / "summary.json", summary)
    return summary


def run_lifecycle(protocol, output, source_commit, seeds, *, development=False):
    settings = protocol["lifecycle"]
    root = Path(output) / "lifecycle"
    root.mkdir(parents=True, exist_ok=False)
    runs = []
    for seed in seeds:
        domains = []
        for domain in settings["domains"]:
            source = json.loads(
                (PACKAGE / "sources" / "numeric" / f"{domain}.json").read_text()
            )
            domains.append(
                domain_run(
                    source,
                    root / f"seed-{seed}" / domain,
                    seed=seed,
                    rank=settings["rank"],
                    correction_count=settings["corrections"],
                    revocation_count=settings["revocations"],
                )
            )
        runs.append({"seed": seed, "domains": domains})
    result = {
        "schema": "memory-cell-v3.lifecycle-study.v1",
        "source_commit": source_commit,
        "development_only": development,
        "runs": runs,
        "parameter_and_residual_metrics_separated": True,
        "injected_corrections_are_qualification_workload": True,
    }
    write_json(root / "summary.json", result)
    return result
