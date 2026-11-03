"""Read-only maintenance audit; no training, owner mutation or policy selection."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from v3.factor_cell import FactorBank  # noqa: E402
from v3.codec import decode_factor  # noqa: E402


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def require(condition, label):
    if not condition:
        raise ValueError(label)


def near(actual, expected, label):
    if expected is None:
        require(actual is None, label)
    elif isinstance(expected, float):
        require(
            isinstance(actual, (int, float))
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10),
            label,
        )
    else:
        require(actual == expected, label)


def reference(bank):
    """Python integer accumulation, independent of production read/reconstruct."""
    positions = [0] * len(bank.blocks)
    result = []
    for row, group in enumerate(bank.routes):
        block = bank.blocks[int(group)]
        latent = block.record_factors[positions[int(group)]]
        positions[int(group)] += 1
        for column in range(bank.shape[1]):
            value = sum(
                int(x) * int(y)
                for x, y in zip(latent, block.decoder[:, column], strict=True)
            )
            if block.shift > 0:
                value = (value + 2 ** (block.shift - 1)) // 2**block.shift
            elif block.shift < 0:
                value *= 2 ** (-block.shift)
            result.append(value + int(block.center[column]))
    return result


def metrics(predictions, matrix, mask, scale):
    targets, valid = matrix.ravel().tolist(), mask.ravel().tolist()
    errors = [
        p - t
        for p, t, ok in zip(predictions, targets, valid, strict=True)
        if ok and p is not None
    ]
    count = sum(valid)
    return {
        "queries": count,
        "coverage": len(errors) / count if count else None,
        "exact_accuracy": sum(e == 0 for e in errors) / count if count else None,
        "mae_original_units": sum(abs(e) for e in errors) / len(errors) / scale
        if errors
        else None,
        "rmse_original_units": math.sqrt(sum(e * e for e in errors) / len(errors))
        / scale
        if errors
        else None,
        "revoked_queries": len(valid) - count,
        "revoked_refusals": sum(
            not ok and p is None for p, ok in zip(predictions, valid, strict=True)
        ),
    }


def audit(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    require(
        not output.exists() and not output.is_relative_to(run),
        "output must be new and outside audited run",
    )
    seal = json.loads((run / "MANIFEST.json").read_bytes())
    inventory = {
        p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()
    } - {"MANIFEST.json"}
    require(inventory == set(seal["files"]), "sealed file inventory differs")
    for name, receipt in seal["files"].items():
        payload = (run / name).read_bytes()
        require(
            len(payload) == receipt["bytes"] and digest(payload) == receipt["sha256"],
            "sealed bytes differ: " + name,
        )
    identity = json.loads((run / "source_identity.json").read_bytes())
    protocol = json.loads((run / "protocol.json").read_bytes())
    environment = json.loads((run / "environment.json").read_bytes())
    summary = json.loads((run / "lifecycle/summary.json").read_bytes())
    settings = protocol["lifecycle"]
    seeds = protocol[
        "development_seeds" if environment["mode"] == "development_only" else "seeds"
    ]
    require([r["seed"] for r in summary["runs"]] == seeds, "lifecycle seed inventory")
    require(summary["source_commit"] == identity["commit"], "source commit binding")
    records, all_queries = [], 0
    with zipfile.ZipFile(run / "source_snapshot.zip") as snapshot:
        for seed_run in summary["runs"]:
            seed = seed_run["seed"]
            require(
                [d["domain"] for d in seed_run["domains"]] == settings["domains"],
                "domain inventory",
            )
            for domain in seed_run["domains"]:
                name = domain["domain"]
                source_name = (
                    "qualification/memory-cell-v3/sources/numeric/" + name + ".json"
                )
                raw = snapshot.read(source_name)
                require(
                    digest(raw) == identity["files"][source_name]["sha256"],
                    "source snapshot hash",
                )
                source = json.loads(raw)
                original = np.array(source["values"], dtype="<i4")
                years, scale = source["years"], source["scale"]
                n, columns = original.shape
                choices = np.random.default_rng(seed).choice(
                    original.size,
                    settings["corrections"] + settings["revocations"],
                    replace=False,
                )
                corrections, revoked = (
                    choices[: settings["corrections"]],
                    choices[settings["corrections"] :],
                )
                changed = original.copy()
                for index, coordinate in enumerate(corrections):
                    changed.ravel()[coordinate] += scale * (1 + index % 5)
                withdrawn = changed.copy()
                withdrawn.ravel()[revoked] = 0
                available = np.ones_like(original, dtype=bool)
                available.ravel()[revoked] = False
                initial_rows = max(2, int(n * settings["initial_fraction"]))
                expected_stages = [
                    (
                        original[:initial_rows],
                        np.ones((initial_rows, columns), dtype=bool),
                        years[:initial_rows],
                    ),
                    (original, np.ones_like(original, dtype=bool), years),
                    (changed, np.ones_like(original, dtype=bool), years),
                    (withdrawn, available, years),
                    (withdrawn, available, years),
                ]
                directory = run / "lifecycle" / f"seed-{seed}" / name
                require(
                    [r["stage"] for r in domain["stages"]] == settings["stages"],
                    "stage inventory",
                )
                previous, stages = None, []
                for generation, (stage, expected) in enumerate(
                    zip(domain["stages"], expected_stages, strict=True), 1
                ):
                    matrix, mask, stage_years = expected
                    version = directory / "owner/versions" / str(generation)
                    manifest = json.loads((version / "manifest.json").read_bytes())
                    require(
                        manifest == stage["manifest"]
                        and manifest["generation"] == generation,
                        "version binding",
                    )
                    for filename, prefix in [
                        ("memory.factor", "model"),
                        ("residual.codec", "residual"),
                        ("addresses.json", "addresses"),
                    ]:
                        payload = (version / filename).read_bytes()
                        require(
                            len(payload) == manifest[prefix + "_bytes"]
                            and digest(payload) == manifest[prefix + "_sha256"],
                            "version component bytes",
                        )
                    addresses = (version / "addresses.json").read_bytes()
                    require(
                        json.loads(addresses)
                        == {"years": stage_years, "columns": columns},
                        "value-free address index",
                    )
                    frontier = digest(
                        matrix.tobytes()
                        + np.packbits(mask.ravel(), bitorder="little").tobytes()
                        + addresses
                    )
                    require(
                        frontier == manifest["frontier_sha256"],
                        "independently regenerated valid source frontier",
                    )
                    bank = FactorBank.from_bytes(
                        (version / "memory.factor").read_bytes(),
                        expected_sha256=manifest["model_sha256"],
                    )
                    require(
                        np.array_equal(bank.mask, mask), "artifact availability mask"
                    )
                    raw_parameters = reference(bank)
                    parameters = [
                        p if ok else None
                        for p, ok in zip(raw_parameters, mask.ravel(), strict=True)
                    ]
                    exact_matrix, exact_mask = decode_factor(
                        (version / "residual.codec").read_bytes(),
                        model=bank,
                        expected_sha256=manifest["residual_sha256"],
                    )
                    require(
                        np.array_equal(exact_matrix, matrix)
                        and np.array_equal(exact_mask, mask),
                        "explicit residual exact reconstruction",
                    )
                    exact = [
                        int(value) if ok else None
                        for value, ok in zip(matrix.ravel(), mask.ravel(), strict=True)
                    ]
                    coordinates = [
                        (year, month)
                        for year in stage_years
                        for month in range(1, columns + 1)
                    ]
                    rows = json.loads(
                        (
                            directory
                            / f"{generation}-{stage['stage']}-predictions.json"
                        ).read_bytes()
                    )
                    expected_rows = [
                        {
                            "address": list(address),
                            "valid": bool(ok),
                            "target": int(value) if ok else None,
                            "parameter_prediction": p,
                            "lossless_prediction": e,
                        }
                        for address, ok, value, p, e in zip(
                            coordinates,
                            mask.ravel(),
                            matrix.ravel(),
                            parameters,
                            exact,
                            strict=True,
                        )
                    ]
                    require(
                        rows == expected_rows,
                        "stored predictions and independently regenerated targets",
                    )
                    all_queries += len(rows)
                    for field, predictions in [
                        ("parameter_metrics", parameters),
                        ("lossless_metrics", exact),
                    ]:
                        recomputed = metrics(predictions, matrix, mask, scale)
                        require(
                            set(recomputed) == set(stage[field]), "metric inventory"
                        )
                        for key, value in recomputed.items():
                            near(stage[field][key], value, field + "/" + key)
                    retention = None
                    if previous is not None:
                        current = {tuple(r["address"]): r for r in rows}
                        overlap = [
                            (r, current[tuple(r["address"])])
                            for r in previous
                            if r["valid"]
                            and tuple(r["address"]) in current
                            and current[tuple(r["address"])]["valid"]
                            and r["target"] == current[tuple(r["address"])]["target"]
                        ]
                        old_errors = [
                            before["parameter_prediction"] - before["target"]
                            for before, after in overlap
                        ]
                        new_errors = [
                            after["parameter_prediction"] - after["target"]
                            for before, after in overlap
                        ]
                        retention = {
                            "unmodified_valid_old_coordinates": len(overlap),
                            "parameter_old_mae_before": sum(map(abs, old_errors))
                            / len(overlap)
                            / scale,
                            "parameter_old_mae_after": sum(map(abs, new_errors))
                            / len(overlap)
                            / scale,
                            "parameter_old_exact_before": sum(
                                e == 0 for e in old_errors
                            )
                            / len(overlap),
                            "parameter_old_exact_after": sum(e == 0 for e in new_errors)
                            / len(overlap),
                            "lossless_old_retention": sum(
                                before["lossless_prediction"]
                                == after["lossless_prediction"]
                                == before["target"]
                                for before, after in overlap
                            )
                            / len(overlap),
                        }
                        for key, value in retention.items():
                            near(stage["old_retention"][key], value, "retention/" + key)
                    if generation == 3:
                        require(
                            stage["corrected_parameter_exact"]
                            == sum(
                                parameters[int(i)] == int(changed.ravel()[i])
                                for i in corrections
                            ),
                            "parameter correction accuracy",
                        )
                        require(
                            stage["corrected_lossless_exact"] == len(corrections),
                            "exact correction accuracy",
                        )
                    stages.append(
                        {
                            "stage": stage["stage"],
                            "parameter_metrics": stage["parameter_metrics"],
                            "lossless_metrics": stage["lossless_metrics"],
                            "old_retention": retention,
                        }
                    )
                    previous = rows
                request = json.loads((directory / "fresh-queries.json").read_bytes())
                require(
                    request
                    == {
                        "scope": name,
                        "generation": 5,
                        "coordinates": [r["address"] for r in rows],
                    },
                    "fresh request contains only value-free addresses",
                )
                process_ids = []
                for mode, field in [
                    ("parameters", "parameter_prediction"),
                    ("lossless_codec", "lossless_prediction"),
                ]:
                    response = json.loads(
                        (directory / f"fresh-{mode}-predictions.json").read_bytes()
                    )
                    require(
                        response["predictions"] == [r[field] for r in rows],
                        "fresh process output parity",
                    )
                    require(
                        response["residual_loaded"] == (mode == "lossless_codec"),
                        "separate residual mode",
                    )
                    if mode == "parameters":
                        require(
                            response["resident_decoded_exact_cache_bytes"] == 0,
                            "parameter process has no decoded exact cache",
                        )
                    process_ids.append(response["process_id"])
                require(len(set(process_ids)) == 2, "two distinct fresh processes")
                require(
                    all(f["rejected"] for f in domain["faults"].values()),
                    "recorded owner fault rejections",
                )
                matches = sum(
                    raw_parameters[int(i)] == int(changed.ravel()[i]) for i in revoked
                )
                require(
                    matches
                    == domain["raw_deleted_coordinate_audit"][
                        "coincidental_old_value_matches"
                    ],
                    "raw deleted-coordinate arithmetic",
                )
                regression = max(
                    s["old_retention"]["parameter_old_exact_before"]
                    - s["old_retention"]["parameter_old_exact_after"]
                    for s in stages
                    if s["old_retention"]
                )
                records.append(
                    {
                        "seed": seed,
                        "domain": name,
                        "stages": stages,
                        "maximum_old_exact_regression": regression,
                        "parameter_retention_gate": regression
                        <= settings["pure_parameter_maximum_old_exact_regression"],
                        "lossless_all_queries_exact": all(
                            s["lossless_metrics"]["exact_accuracy"] == 1 for s in stages
                        ),
                        "faults_recorded_rejected": len(domain["faults"]),
                        "raw_deleted_old_value_matches": matches,
                        "fresh_parameter_and_codec_parity": True,
                    }
                )
    report = {
        "schema": "memory-cell-v3.lifecycle-independent-audit.v1",
        "verified": True,
        "source_commit": identity["commit"],
        "manifest_sha256": digest((run / "MANIFEST.json").read_bytes()),
        "auditor_sha256": digest(Path(__file__).read_bytes()),
        "development_only": environment["mode"] == "development_only",
        "domain_seed_runs": len(records),
        "stage_prediction_rows_recomputed": all_queries,
        "runs": records,
        "parameter_retention_all_runs": all(
            r["parameter_retention_gate"] for r in records
        ),
        "lossless_all_queries_exact": all(
            r["lossless_all_queries_exact"] for r in records
        ),
        "limits": [
            "Saved model parsing and residual decoding reuse production format parsers; parameter inference arithmetic, source targets and metrics are independently recomputed.",
            "Original fault execution and process isolation are retained receipts, not new fault executions by this auditor.",
            "No historical elapsed-time proof, distributed consensus, production admission or weight-unlearning certification.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    audit(arguments.run, arguments.output)
