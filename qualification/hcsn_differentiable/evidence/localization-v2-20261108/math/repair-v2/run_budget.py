"""Read-only CPU numerical admission for a separately declared d=0.2 profile.

No training, new model initialization, changed source, label scoring, or old
qualification credit. Each accepted scope is explicit in the output receipt.
"""

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
from zipfile import ZipFile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    folder = Path(__file__).resolve().parent
    spec = json.loads((folder / "profile.json").read_text())
    manifest = json.loads((folder / "source_manifest.json").read_text())
    started = time.perf_counter()
    report = {"schema": "hcsn-localization-v2-budget-result-v1", "status": "started", "profile": spec,
              "profile_sha256": digest((folder / "profile.json").read_bytes()),
              "runner_sha256": digest(Path(__file__).read_bytes()),
              "source_manifest_sha256": digest((folder / "source_manifest.json").read_bytes()),
              "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "device": "cpu", "formal_fits_started": 0, "smoke_fits_started": 0,
              "certified_error_bound": False, "physical_energy_joules": None,
              "inherited_qualification": False, "errors": [], "rows": []}
    save(args.output / "locked-profile.json", report)
    events = (args.output / "events.jsonl").open("x", encoding="utf-8")

    def check():
        if time.perf_counter() - started > spec["wall_budget_seconds"]:
            raise TimeoutError("predeclared CPU wall budget exhausted")
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 > spec["rss_budget_bytes"]:
            raise MemoryError("predeclared RSS budget exceeded")

    def event(kind, **values):
        events.write(json.dumps({"kind": kind, "wall_seconds": time.perf_counter() - started, **values}) + "\n")
        events.flush()

    def source_hashes():
        return {name: digest((args.source_root / name).read_bytes()) for name in manifest}

    code = 2
    try:
        before = source_hashes()
        report["source_before"] = before
        if before != manifest:
            raise ValueError("native source differs from the frozen source manifest")
        archive = args.archive.read_bytes()
        if digest(archive) != spec["archive_sha256"]:
            raise ValueError("archive SHA mismatch")
        with ZipFile(io.BytesIO(archive)) as zipped:
            data = zipped.read("ConfLongDemo_JSI.txt")
        if digest(data) != spec["data_sha256"]:
            raise ValueError("dataset member SHA mismatch")
        groups = defaultdict(list)
        for line, row in enumerate(csv.reader(io.StringIO(data.decode())), 1):
            if row:
                groups[row[0]].append((int(row[2]), line))
        if sum(map(len, groups.values())) != 164860 or len(groups) != 25:
            raise ValueError("unexpected dataset row/sequence cardinality")
        all_ticks, selection = [], {}
        for name, rows in sorted(groups.items()):
            rows.sort()
            all_ticks.extend(b[0] - a[0] for a, b in zip(rows, rows[1:]))
            if name in spec["selection"]:
                selected = rows[:spec["selection"][name]]
                selection[name] = {"row_ids": [row[1] for row in selected],
                                   "gap_ticks": [0] + [b[0] - a[0] for a, b in zip(selected, selected[1:])]}
        all_ticks.sort()
        selected_ticks = sorted({gap for value in selection.values() for gap in value["gap_ticks"]})
        unique_global = sorted(set(all_ticks))
        input_record = {"archive_sha256": spec["archive_sha256"], "data_sha256": spec["data_sha256"],
                        "selection": selection, "selected_unique_gap_ticks": selected_ticks,
                        "global_unique_gap_ticks": unique_global, "global_gap_count": len(all_ticks),
                        "conversion": "integer delta_ticks / 10000000; no clipping, substeps or resampling"}
        save(args.output / "gap-inputs.json", input_record)
        report["gap_inputs_sha256"] = digest((args.output / "gap-inputs.json").read_bytes())
        report["selection"] = selection
        report["global_unique_gaps"] = len(unique_global)
        report["selected_unique_gaps"] = len(selected_ticks)
        if min(unique_global) < 0 or max(unique_global) / 10000000 > spec["grid"]["refractory"]:
            raise ValueError("actual gap lies outside this separate refractory profile")
        sys.path.insert(0, str(args.source_root))
        import torch
        from qualification.hcsn_differentiable.contract import GridSpec
        from qualification.hcsn_differentiable.network import TrainablePhysics
        from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
        from qualification.hcsn_differentiable.regenerative import _decay, basis_perpetual_value, perpetual_value
        from qualification.hcsn_differentiable.value import perpetual_basis_value
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        report["torch"] = torch.__version__
        physical = spec["physics"]
        if physical["trainable"]:
            raise ValueError("this admission only covers frozen physical parameters")
        physics_module = TrainablePhysics(mu=physical["mu"], sigma=physical["sigma"],
            log_boundary=physical["log_boundary"], log_absolute_reset=physical["log_absolute_reset"],
            discount=physical["discount"]).double().requires_grad_(False)
        params = physics_module()
        report["actual_physics_hex"] = {name: float(value).hex() for name, value in zip(
            ("log_boundary", "mu", "sigma", "absolute_reset", "discount"), params.tensors())}
        grid = GridSpec(**spec["grid"])
        operator = DifferentiableDistributionOperator(grid)
        absolute_initial = math.exp(spec["initial_margin"] + physical["log_boundary"])
        prior = operator.initial_probability(absolute_initial, params.log_boundary)
        basis_u = basis_perpetual_value(grid, params)
        decay = _decay(params)
        mean = float(torch.log(params.mu.new_tensor(absolute_initial)) - params.log_boundary)
        std = grid.initial_log_std
        report["actual_initial_log_margin"] = mean
        log_g = (-decay * mean + 0.5 * (decay * std).square()
                 + torch.special.log_ndtr((mean - decay * std * std) / std)
                 - torch.special.log_ndtr(params.mu.new_tensor(mean / std)))
        g = torch.exp(log_g)
        reset = perpetual_value(torch.log(params.absolute_reset) - params.log_boundary, params,
                                 refractory=grid.refractory)
        reference = (0.4 * -torch.expm1(log_g) / params.discount + g
                     + g * torch.exp(-params.discount * grid.refractory) * reset.reset_value)
        scale = max(1., abs(float(reference)))
        report.update(continuum_reference=float(reference),
                      continuum_reconstructed_prior=float(prior @ basis_u),
                      initial_projection_scaled_error=abs(float(prior @ basis_u - reference)) / scale)
        tables, rewards, selected_values = {}, {}, {}
        with torch.no_grad():
            for tick in unique_global:
                check()
                row = {"gap_ticks": tick, "duration": tick / 10000000, "in_locked_smoke": tick in selected_ticks}
                try:
                    table = operator(*params.tensors()[:4], row["duration"], params.discount)
                    reward = 0.4 * table.rewards[:, 2] + table.rewards[:, 1]
                    defect = reward + torch.exp(-params.discount * row["duration"]) * (table.matrix @ basis_u) - basis_u
                    row.update(mass_error=float((table.matrix.sum(-1) - 1).abs().max()),
                               minimum_probability=float(table.matrix.min()),
                               one_interval_continuation_scaled_defect=float(defect.abs().max()) / max(1., float(basis_u.abs().max())))
                    row["interface_passed"] = (row["mass_error"] <= spec["limits"]["probability_mass_error"]
                                               and row["minimum_probability"] >= 0)
                    if tick in selected_ticks:
                        tables[tick], rewards[tick] = table, reward
                        if tick:
                            solved = perpetual_basis_value(operator, params, row["duration"])
                            value = float(prior @ solved.value)
                            selected_values[tick] = value
                            row.update(perpetual_scaled_error=abs(value - float(reference)) / scale,
                                       linear_solve_residual_estimate=float(solved.residual_error_estimate),
                                       reconstructed_row_perpetual_scaled_error=float((solved.value - basis_u).abs().max())
                                       / max(1., float(basis_u.abs().max())))
                    row["status"] = "measured"
                except Exception as error:
                    row.update(status="error", interface_passed=False, error=f"{type(error).__name__}: {error}")
                report["rows"].append(row)
                if len(report["rows"]) % 25 == 0:
                    event("gap_progress", completed=len(report["rows"]), total=len(unique_global))
            positive_selected = [tick for tick in selected_ticks if tick]
            # Predeclared order statistics plus the global maximum; selection uses gap metadata only.
            anchors = sorted({positive_selected[round(q * (len(positive_selected) - 1))] for q in (0, .5, 1)}
                             | {all_ticks[round(q * (len(all_ticks) - 1))] for q in (.95, .99, 1)})
            variants = {"space": replace(grid, active_cells=256), "phase": replace(grid, phase_cells=32),
                        "tail": replace(grid, endpoint=3.6, active_cells=192),
                        "time": grid, "quadrature": replace(grid, quadrature_order=64)}
            report["refinement"] = []
            for tick in anchors:
                check()
                duration = tick / 10000000
                base = perpetual_basis_value(operator, params, duration)
                base_value = float(prior @ base.value)
                observation = {"gap_ticks": tick, "baseline_perpetual_scaled_error": abs(base_value - float(reference)) / scale}
                for label, geometry in variants.items():
                    event("refinement_start", gap_ticks=tick, variant=label)
                    check()
                    alternate = DifferentiableDistributionOperator(geometry)
                    p = alternate.initial_probability(absolute_initial, params.log_boundary)
                    result = perpetual_basis_value(alternate, params, duration / 2 if label == "time" else duration)
                    observation[label + "_refinement_delta"] = abs(float(p @ result.value) - base_value) / scale
                report["refinement"].append(observation)
                event("refinement_complete", gap_ticks=tick)
            report["unconditioned_sequences"] = []
            schedules = [("A01_128", selection["A01"]["gap_ticks"]), ("D01_64", selection["D01"]["gap_ticks"])]
            schedules += [(f"A01_window_{index + 1}", selection["A01"]["gap_ticks"][32 * index:32 * (index + 1)]) for index in range(4)]
            for name, schedule in schedules:
                p, total, elapsed, drift = prior.clone(), params.mu.new_zeros(()), 0., 0.
                for tick in schedule:
                    total = total + math.exp(-physical["discount"] * elapsed) * (p @ rewards[tick])
                    p = p @ tables[tick].matrix
                    elapsed += tick / 10000000
                    drift = max(drift, abs(float(p.sum()) - 1))
                closing = total + math.exp(-physical["discount"] * elapsed) * (p @ basis_u)
                report["unconditioned_sequences"].append({"name": name, "events": len(schedule), "elapsed": elapsed,
                    "perpetual_continuation_scaled_error": abs(float(closing - reference)) / scale, "maximum_mass_drift": drift})
        selected_rows = [row for row in report["rows"] if row["in_locked_smoke"]]
        limits = spec["limits"]
        gates = {"all_global_gap_interfaces": all(row["interface_passed"] for row in report["rows"]),
                 "locked_gap_perpetual": all(row["status"] == "measured"
                    and (row["gap_ticks"] == 0 or (row["perpetual_scaled_error"] <= limits["combined_value_error"]
                    and row["linear_solve_residual_estimate"] <= limits["linear_solve_residual_estimate"])) for row in selected_rows),
                 "refinement_anchors": all(row["baseline_perpetual_scaled_error"] <= limits["combined_value_error"]
                    and all(row[label + "_refinement_delta"] <= limits[label + "_refinement_delta"] for label in variants)
                    for row in report["refinement"]),
                 "locked_unconditioned_sequences": all(row["perpetual_continuation_scaled_error"] <= limits["combined_value_error"]
                    and row["maximum_mass_drift"] <= limits["sequence_mass_drift"] for row in report["unconditioned_sequences"])}
        report.update(gates=gates, status="passed_locked_frozen_profile" if all(gates.values()) else "failed_numerical_admission")
        code = 0 if all(gates.values()) else 1
    except Exception:
        report.update(status="blocked_or_incomplete", detail=traceback.format_exc())
    finally:
        report.update(wall_seconds=time.perf_counter() - started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        try:
            report["source_after"] = source_hashes()
            report["source_unchanged"] = report.get("source_before") == report["source_after"] == manifest
        except Exception as error:
            report.update(source_unchanged=False, source_error=str(error))
        if not report["source_unchanged"]:
            report["status"], code = "source_changed_or_missing", 2
        event("finished", status=report["status"])
        events.close()
        save(args.output / "result.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output), "profile_sha256": report["profile_sha256"]}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
