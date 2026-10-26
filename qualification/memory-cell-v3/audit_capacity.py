"""Recompute saved capacity evidence without fitting or changing any model."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from v3.capacity_audit_core import (
    Checks,
    Sources,
    WORK_KEYS,
    add_work,
    checked_file,
    compare_work,
    independent_coordinates,
    independent_metrics,
    independent_sources,
    integer_reference,
    read_json,
    receipt_work,
    sha256,
    source_hash,
)
from v3.capacity_audit_extract import extraction
from v3.codec import decode_exact, decode_factor, decompress_bytes
from v3.factor_cell import FactorBank, MAGIC


FAMILIES = {
    "global_svd",
    "predeclared_cells",
    "random_cells",
    "learned_cells",
    "learned_vq",
}


def audit_archives(directory, reported, source, checks):
    values = source["values"]
    common = checked_file(directory, "address-provenance.bin").read_bytes()
    metadata = json.loads(decompress_bytes(common))
    checks.require(
        len(common) == reported["address_provenance_bytes"]
        and sha256(common) == reported["address_provenance_sha256"],
        str(directory.name) + " address/provenance bytes",
    )
    checks.require(
        read_json(checked_file(directory, "archive-accounting.json")) == reported,
        str(directory.name) + " archive accounting copy",
    )
    checks.require(
        values.size == reported["source_values"]
        and values.nbytes == reported["canonical_int32_value_bytes"]
        and source_hash(values) == reported["source_sha256"],
        str(directory.name) + " fixed source identity",
    )
    if "metadata" in source:
        checks.require(
            metadata["canonical_source_json_sha256"] == source["source_json_sha256"],
            str(directory.name) + " canonical source file digest",
        )
        checks.require(
            all(
                metadata.get(k) == v
                for k, v in source["metadata"].items()
                if k != "values"
            ),
            str(directory.name) + " address metadata content",
        )
    elif "source_npz_sha256" in source:
        checks.require(
            metadata["source_sha256"] == source["source_npz_sha256"],
            "digits original npz digest",
        )
    else:
        checks.require(
            metadata["random_replacement_probability"] == source["random_mix"]
            and metadata["seed"] == source["seeds"][0],
            str(directory.name) + " independent synthetic configuration",
        )
    expected_names = {
        form + "/" + method
        for form in ("int32", "offset-bits", "delta-row", "delta-column")
        for method in ("raw", "zlib", "lzma")
    }
    candidates = reported["codec_candidates"]
    checks.require(
        len(candidates) == 12
        and {item["name"] for item in candidates} == expected_names,
        str(directory.name) + " twelve exact controls",
    )
    lengths = {}
    for item in candidates:
        if item["name"] not in expected_names:
            raise ValueError("unknown exact baseline identity")
        payload = checked_file(
            directory, "exact-baselines", item["name"].replace("/", "-") + ".bin"
        ).read_bytes()
        restored, mask = decode_exact(payload, item["sha256"])
        checks.require(
            np.array_equal(restored, values) and mask.all(),
            str(directory.name) + " exact roundtrip " + item["name"],
        )
        checks.require(
            len(payload) == item["archive_bytes"]
            and len(payload) + len(common) == item["complete_stored_bytes"],
            str(directory.name) + " baseline actual bytes " + item["name"],
        )
        lengths[item["name"]] = len(payload)
    best = reported["strongest_exact_baseline"]
    checks.require(
        best["name"] in lengths
        and best["archive_bytes"] == min(lengths.values()) == lengths[best["name"]],
        str(directory.name) + " strongest baseline selection",
    )
    return {
        "common_bytes": len(common),
        "strong_exact_bytes": min(lengths.values()) + len(common),
        "exact_baseline_files": 12,
    }


def audit_codec(payload, bank, reported, truth, checks, label):
    restored, mask = decode_factor(
        payload, model=bank, expected_sha256=reported["archive_sha256"]
    )
    checks.require(
        np.array_equal(restored, truth) and mask.all(),
        label + " model-residual exact roundtrip",
    )
    checks.require(
        reported["model_storage"] == "external"
        and reported["parameter_only_readout"] is False,
        label + " explicit residual mode",
    )
    checks.require(
        reported["archive_bytes"] == len(payload)
        and reported["required_model_bytes"] == len(bank.to_bytes())
        and reported["complete_standalone_bytes"]
        == len(payload) + len(bank.to_bytes()),
        label + " residual complete byte charge",
    )
    checks.require(
        reported["model_sha256"] == bank.digest
        and reported["source_sha256"] == source_hash(truth),
        label + " codec model/source binding",
    )
    return len(payload) + len(bank.to_bytes())


def audit_search_work(base, shape, checks):
    saved = read_json(checked_file(base, "candidate-fit-work.json"))
    work = {}
    for family, data in saved["families"].items():
        routes = [saved["learned_partition"]] if family == "learned_cells" else []
        work[family] = receipt_work(
            data["candidate_receipts"], routes, checks, str(base) + " " + family, shape
        )
        compare_work(work[family], data["work"], checks, family + " search aggregate")
    vq = read_json(checked_file(base, "vq-fit-work.json"))
    work["learned_vq"] = receipt_work(
        vq["factor_receipts"], vq["route_receipts"], checks, str(base) + " VQ", shape
    )
    compare_work(work["learned_vq"], vq["work"], checks, "VQ search aggregate")
    checks.require(
        set(work) == FAMILIES and saved["hidden_targets_used_for_selection"] is False,
        str(base) + " declared search scope",
    )
    return work


def audit_control(path, record, global_sha, search_work, shape, settings, checks):
    control = read_json(
        checked_file(path.parent, path.with_suffix(".control.json").name)
    )
    checks.require(
        {k: v for k, v in control.items() if k != "receipts"}
        == record["same_work_global_control"],
        record["id"] + " control receipt copy",
    )
    extra = receipt_work(
        control["receipts"], [], checks, record["id"] + " control", shape
    )
    baseline, target = search_work["global_svd"], search_work[record["family"]]
    expected_work = baseline["svd_work_proxy"] + extra["svd_work_proxy"]
    expected_time = baseline["fit_wall_seconds"] + extra["fit_wall_seconds"]
    checks.require(
        control["extra_fits"] == len(control["receipts"])
        and control["extra_fits"] <= settings["same_work_max_repeats"],
        record["id"] + " extra fit count",
    )
    checks.require(
        control["same_artifact_sha256"] == global_sha
        and all(r["artifact_sha256"] == global_sha for r in control["receipts"]),
        record["id"] + " controls retain identical global artifact",
    )
    checks.near(
        control["actual_total_svd_work_proxy"],
        expected_work,
        record["id"] + " total control SVD work",
    )
    checks.near(
        control["actual_fit_wall_seconds"],
        expected_time,
        record["id"] + " total control fitting time",
    )
    checks.near(
        control["target_svd_work_proxy"],
        target["svd_work_proxy"],
        record["id"] + " control SVD target",
    )
    checks.near(
        control["target_fit_wall_seconds"],
        target["fit_wall_seconds"],
        record["id"] + " control time target",
    )
    met = (
        expected_work >= target["svd_work_proxy"]
        and expected_time + 1e-12 >= target["fit_wall_seconds"]
    )
    checks.require(
        control["work_floor_met"] == met, record["id"] + " recomputed work floor status"
    )
    return extra, met


def audit_capacity(run_dir, output_path=None, *, allow_legacy_development=False):
    started = time.perf_counter()
    run = Path(run_dir).resolve()
    if output_path is not None:
        output = Path(output_path).resolve()
        if output.is_relative_to(run) or output.exists():
            raise ValueError(
                "audit output must be new and outside the immutable run directory"
            )
    capacity = (
        run / "capacity"
        if (run / "capacity" / "capacity-summary.json").is_file()
        else run
    )
    summary = read_json(checked_file(capacity, "capacity-summary.json"))
    checks = Checks()
    checks.require(
        summary["schema"] == "memory-cell-v3.capacity-study.v1",
        "capacity summary schema",
    )
    store = Sources(run, summary, allow_legacy_development, checks)
    settings = summary["settings"]
    actual_work = dict.fromkeys(WORK_KEYS, 0)
    records, archives, archival_models, checked_models = [], {}, [], set()
    controls_met = control_count = extra_control_fits = 0
    try:
        sources = independent_sources(store, settings, summary["seeds"])
        dataset_records = {item["name"]: item for item in summary["datasets"]}
        checks.require(
            len(dataset_records) == len(summary["datasets"])
            and set(dataset_records) == set(sources),
            "complete independently generated dataset inventory",
        )
        requests = read_json(checked_file(capacity, "isolated-read-requests.json"))
        answers = read_json(checked_file(capacity, "isolated-read-results.json"))[
            "results"
        ]
        requested, answered = (
            {r["id"]: r for r in requests},
            {r["id"]: r for r in answers},
        )
        feasible_ids = {r["id"] for r in summary["records"] if r["feasible"]}
        checks.require(
            len(requested) == len(requests)
            and len(answered) == len(answers)
            and set(requested) == feasible_ids == set(answered),
            "complete isolated read request/answer inventory",
        )
        query_cache, work_cache = {}, {}
        expected_records = set()
        for name, source in sources.items():
            directory = capacity / name
            item, values = dataset_records[name], source["values"]
            checks.require(
                item["shape"] == list(values.shape)
                and item["scale"] == source["scale"],
                name + " source shape/units",
            )
            archives[name] = audit_archives(directory, item["archives"], source, checks)
            budgets = {
                max(1, int(values.nbytes * fraction))
                for fraction in settings["budget_fractions_int32"]
            }
            for seed in source["seeds"]:
                expected_records.update(
                    (name, seed, budget, family)
                    for budget in budgets
                    for family in FAMILIES
                )
                base = directory / ("seed-" + str(seed))
                selection, rows, columns = independent_coordinates(
                    values.shape, seed, settings
                )
                split = read_json(checked_file(base, "query-split.json"))
                checks.require(
                    split["selection_sha256"]
                    == sha256(np.packbits(selection).tobytes())
                    and split["selection_count"] == int(selection.sum()),
                    name + " independent selection split",
                )
                checks.require(
                    split["hidden_rows"] == rows.tolist()
                    and split["hidden_columns"] == columns.tolist()
                    and split["hidden_count"] == len(rows)
                    and split["selection_hidden_overlap"] is False
                    and not selection[rows, columns].any(),
                    name + " independent hidden split",
                )
                query_cache[name, seed] = selection, rows, columns
                work_cache[name, seed] = audit_search_work(base, values.shape, checks)
                for work in work_cache[name, seed].values():
                    add_work(actual_work, work)
                curve = read_json(checked_file(base, "source-codec-curve.json"))
                model_path = checked_file(base, "best-source-codec-model.bin")
                bank = FactorBank.load(model_path, curve["best"]["model_sha256"])
                checked_models.add(model_path.relative_to(capacity).as_posix())
                payload = checked_file(base, "best-source-residual.bin").read_bytes()
                total = audit_codec(
                    payload,
                    bank,
                    curve["best"],
                    values,
                    checks,
                    name + " best archival model",
                )
                checks.require(
                    total
                    == min(c["complete_standalone_bytes"] for c in curve["candidates"]),
                    name + " archival candidate minimum",
                )
                rr, cc = np.indices(values.shape).reshape(2, -1)
                pure = independent_metrics(
                    integer_reference(bank, rr, cc),
                    values.ravel(),
                    source["scale"],
                    float(np.var(values.astype(np.float64))),
                )
                checks.near(
                    curve["best"]["pure_parameter_mse"],
                    pure["mse_scaled_integer"],
                    name + " archival full-source parameter MSE",
                )
                checks.near(
                    curve["best"]["pure_parameter_exact_accuracy"],
                    pure["exact_accuracy"],
                    name + " archival full-source exactness",
                )
                retained = item["best_source_codecs_by_seed"][str(seed)]
                checks.require(
                    all(retained[k] == v for k, v in curve["best"].items()),
                    name + " archival summary binding",
                )
                archival_models.append(
                    {
                        "dataset": name,
                        "seed": seed,
                        "rank": bank.blocks[0].rank,
                        "artifact_bytes": len(bank.to_bytes()),
                        "complete_stored_bytes": total + archives[name]["common_bytes"],
                        "full_source_parameter_metrics": pure,
                    }
                )
        observed_records = {
            (r["dataset"], r["seed"], r["budget_bytes"], r["family"])
            for r in summary["records"]
        }
        checks.require(
            len(observed_records) == len(summary["records"])
            and observed_records == expected_records,
            "complete family/seed/budget inventory",
        )
        for record in summary["records"]:
            if not record["feasible"]:
                continue
            identifier = record["id"]
            try:
                name, seed, budget, family = (
                    record["dataset"],
                    record["seed"],
                    record["budget_bytes"],
                    record["family"],
                )
                checks.require(
                    identifier == f"{name}/{seed}/{budget}/{family}",
                    identifier + " canonical model identity",
                )
                source, accounting = sources[name], archives[name]
                values = source["values"]
                selection, rows, columns = query_cache[name, seed]
                path = checked_file(
                    capacity,
                    name,
                    "seed-" + str(seed),
                    str(budget) + "-" + family + ".bin",
                )
                payload = path.read_bytes()
                request, original_read = requested[identifier], answered[identifier]
                checks.require(
                    set(request) == {"id", "artifact", "sha256", "rows", "columns"},
                    identifier + " value-free request fields",
                )
                checks.require(
                    request["rows"] == rows.tolist()
                    and request["columns"] == columns.tolist(),
                    identifier + " read coordinates",
                )
                checks.require(
                    tuple(Path(request["artifact"]).parts[-3:])
                    == (name, "seed-" + str(seed), path.name),
                    identifier + " model path identity",
                )
                bank = FactorBank.from_bytes(payload, request["sha256"])
                checked_models.add(path.relative_to(capacity).as_posix())
                checks.require(
                    bank.shape == values.shape and bank.mask.all(),
                    identifier + " saved source scope",
                )
                if family == "predeclared_cells":
                    checks.require(
                        np.array_equal(bank.routes, source["declared_routes"]),
                        identifier + " predeclared routes",
                    )
                if family == "random_cells":
                    route = np.arange(len(values)) % min(settings["cells"], len(values))
                    np.random.default_rng(seed + 17).shuffle(route)
                    checks.require(
                        np.array_equal(bank.routes, route),
                        identifier + " independently seeded random routes",
                    )
                if family == "global_svd":
                    checks.require(
                        len(bank.blocks) == 1, identifier + " global model identity"
                    )
                if family == "learned_vq":
                    checks.require(
                        all(block.rank == 0 for block in bank.blocks)
                        and len(bank.blocks) <= settings["max_vq_cells"],
                        identifier + " codebook family/ceiling",
                    )
                predicted = integer_reference(bank, rows, columns)
                checks.require(
                    predicted == bank.read(rows, columns) == original_read["answers"],
                    identifier + " independent integer prediction parity",
                )
                checks.require(
                    bank.digest == original_read["artifact_sha256"],
                    identifier + " isolated read model digest",
                )
                recomputed = independent_metrics(
                    predicted,
                    values[rows, columns],
                    source["scale"],
                    float(np.var(values.astype(np.float64))),
                )
                for key, value in recomputed.items():
                    checks.near(
                        record["hidden"][key], value, identifier + " hidden " + key
                    )
                n, d = values.shape
                expected_bytes = (
                    20
                    + (n * (len(bank.blocks) - 1).bit_length() + 7) // 8
                    + sum(
                        8 + 4 * d + 2 * block.rank * (len(block.record_factors) + d)
                        for block in bank.blocks
                    )
                )
                checks.require(
                    len(payload)
                    == expected_bytes
                    == record["artifact_bytes"]
                    <= budget,
                    identifier + " actual serialized bytes and budget",
                )
                checks.require(
                    record["parameter_bytes"] == bank.parameter_bytes
                    and record["complete_parameter_read_bytes"]
                    == len(payload) + accounting["common_bytes"],
                    identifier + " complete parameter state",
                )
                checks.require(
                    record["selection"]["budget_bytes"] == budget
                    and record["selection"]["unused_budget_bytes"]
                    == budget - len(payload)
                    and record["selection"]["ranks"]
                    == [block.rank for block in bank.blocks],
                    identifier + " selected allocation receipt",
                )
                error = (
                    bank.reconstruct()[selection].astype(np.float64) - values[selection]
                )
                checks.near(
                    record["selection"]["selection_squared_error"],
                    float(np.square(error).sum()),
                    identifier + " selection squared error",
                )
                resident = bank.parameter_bytes + bank.routes.nbytes + bank.mask.nbytes
                checks.require(
                    record["resident_model_array_bytes"]
                    == original_read["resident_model_array_bytes"]
                    == resident,
                    identifier + " resident array bytes",
                )
                residual = checked_file(
                    path.parent, path.with_suffix(".residual").name
                ).read_bytes()
                exact_bytes = audit_codec(
                    residual,
                    bank,
                    record["source_codec_receipt"],
                    values,
                    checks,
                    identifier,
                )
                checks.require(
                    record["complete_exact_replay_bytes"]
                    == exact_bytes + accounting["common_bytes"]
                    and record["strong_exact_baseline_bytes"]
                    == accounting["strong_exact_bytes"],
                    identifier + " model-residual versus exact complete state",
                )
                compare_work(
                    work_cache[name, seed][family],
                    record["all_candidate_fit_work"],
                    checks,
                    identifier + " reused search work",
                )
                control = None
                if family != "global_svd":
                    global_id = f"{name}/{seed}/{budget}/global_svd"
                    extra, control = audit_control(
                        path,
                        record,
                        requested[global_id]["sha256"],
                        work_cache[name, seed],
                        values.shape,
                        settings,
                        checks,
                    )
                    add_work(actual_work, extra)
                    extra_control_fits += extra["candidate_fits"]
                    control_count += 1
                    controls_met += control
                else:
                    checks.require(
                        record["same_work_global_control"] is None,
                        identifier + " no redundant global control",
                    )
                records.append(
                    {
                        "id": identifier,
                        "dataset": name,
                        "seed": seed,
                        "budget_bytes": budget,
                        "family": family,
                        "artifact_sha256": bank.digest,
                        "artifact_bytes": len(payload),
                        "complete_parameter_read_bytes": len(payload)
                        + accounting["common_bytes"],
                        "complete_exact_replay_bytes": exact_bytes
                        + accounting["common_bytes"],
                        "hidden": recomputed,
                        "same_work_floor_met": control,
                    }
                )
            except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
                checks.require(
                    False,
                    identifier + " auditable artifact",
                    type(error).__name__ + ": " + str(error),
                )
        retained_models = {
            path.relative_to(capacity).as_posix()
            for path in capacity.rglob("*.bin")
            if path.read_bytes()[: len(MAGIC)] == MAGIC
        }
        checks.require(
            checked_models == retained_models,
            "every retained pure-parameter artifact audited",
        )
        retained_bytes = sum(
            path.stat().st_size
            for path in capacity.rglob("*")
            if path.is_file() and path.name != "capacity-summary.json"
        )
        checks.require(
            retained_bytes == summary["research_output_bytes_before_summary"],
            "actual complete capacity research retention",
        )
        if "actual_total_training_work" in summary:
            compare_work(
                actual_work,
                summary["actual_total_training_work"],
                checks,
                "actual aggregate training work counted once",
            )
            checks.require(
                extra_control_fits
                == summary["actual_total_training_work"]["extra_control_fits"],
                "aggregate extra control fit count",
            )
        else:
            checks.require(
                store.mode == "legacy_development_without_source_snapshot",
                "formal aggregate work required",
            )
        report = {
            "schema": "memory-cell-v3.capacity-independent-audit.v1",
            "passed": not checks.failures,
            "checks": checks.count,
            "failures": checks.failures,
            "run_directory": str(run),
            "source_binding": store.binding,
            "mode": store.mode,
            "reported_source_commit": summary["source_commit"],
            "settings": settings,
            "seeds": summary["seeds"],
            "audited_selected_models": len(records),
            "audited_archival_models": len(archival_models),
            "audited_pure_parameter_files": len(checked_models),
            "same_work_controls": {
                "checked": control_count,
                "floors_met": controls_met,
            },
            "actual_training_work_from_receipts": actual_work
            | {"extra_control_fits": extra_control_fits},
            "capacity_research_retained_bytes": retained_bytes
            + checked_file(capacity, "capacity-summary.json").stat().st_size,
            "records": records,
            "archival_models": archival_models,
            "compact": extraction(
                records,
                archives,
                archival_models,
                sources,
                store.protocol.get("statistics", {}),
            ),
            "audit_seconds": time.perf_counter() - started,
            "boundaries": [
                "No fitting or policy updates are performed by this audit.",
                "Independent Python integer arithmetic recomputes parameter readout; source truth is separately reconstructed from bound fixed sources or the declared synthetic generator.",
                "Receipt arithmetic and work floors are checked, but historical wall time is recorded telemetry, not independently attested CPU execution.",
                "This audit complements the full run manifest/source verifier and does not replace it.",
                "Legacy development without an execution snapshot cannot establish an exact historical code identity.",
            ],
        }
        code_paths = [
            Path(__file__),
            Path(__file__).parent / "v3" / "capacity_audit_core.py",
            Path(__file__).parent / "v3" / "capacity_audit_extract.py",
        ]
        report["auditor_source_sha256"] = {
            path.name: sha256(path.read_bytes()) for path in code_paths
        }
        if output_path is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x") as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
        return report
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-legacy-development", action="store_true")
    args = parser.parse_args()
    report = audit_capacity(
        args.run, args.output, allow_legacy_development=args.allow_legacy_development
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "checks": report["checks"],
                "failures": len(report["failures"]),
                "pure_parameter_files": report["audited_pure_parameter_files"],
                "output": str(args.output.resolve()),
            }
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
