"""Offline representation probes on every retained training posterior.

All risk comparisons use the pinned finite candidate as the reference. These
probes neither certify its continuum accuracy nor implement a faster network.
Content SVD is an oracle re-encoding of saved states, not recurrent deployment.
"""

import time
STARTED, CPU_STARTED = time.perf_counter(), time.process_time()

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from qualification.hcsn_boundary_audit import audit_trained_gradients as admission_helpers
from qualification.hcsn_boundary_audit.audit_trained_gradients import admit, checked_bytes
from qualification.hcsn_boundary_factorial.run import ARMS, source_identity
from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator, _first_hit


def capture_audit_sources(paths=None):
    """Pin this audit and its admission helper before reading experiment inputs."""
    if paths is None:
        paths = (Path(__file__), Path(admission_helpers.__file__))
    return {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in paths}


def verify_audit_sources(identities):
    current = capture_audit_sources(identities)
    if current != identities:
        raise ValueError("audit or admission helper source changed during the audit")
    return current


def content_rank(content, rank):
    """Return the best Frobenius approximation; never alter probability."""
    left, singular, right = np.linalg.svd(content, full_matrices=False)
    return (left[..., :rank] * singular[..., None, :rank]) @ right[..., :rank, :]


def operator_rank(matrix, rank):
    """Unrepaired truncated SVD; negative entries and mass loss stay visible."""
    left, singular, right = np.linalg.svd(matrix, full_matrices=False)
    return (left[:, :rank] * singular[None, :rank]) @ right[:rank]


def transition_defects(reference, approximation, active):
    """Check both phase destinations and release from phase source rows."""
    difference = np.abs(approximation - reference)
    return dict(maximum_row_mass_defect=float(np.abs(approximation.sum(1) - 1).max()),
        minimum_entry=float(approximation.min()),
        maximum_phase_destination_row_l1_error=float(difference[:, active:].sum(1).max()),
        maximum_phase_source_row_l1_error=float(difference[active:, :].sum(1).max()))


def error_record():
    return dict(count=0, absolute_sum=0., maximum_absolute=0., signed_sum=0.,
                reference_sum=0., approximation_sum=0., worst_case=None)


def record_errors(record, reference, approximation, context):
    reference, approximation = np.asarray(reference), np.asarray(approximation)
    error = approximation - reference
    if not np.isfinite(error).all():
        raise FloatingPointError("nonfinite approximation error")
    index = int(np.argmax(np.abs(error)))
    maximum = float(np.abs(error).reshape(-1)[index])
    if maximum > record["maximum_absolute"]:
        record["maximum_absolute"] = maximum
        record["worst_case"] = dict(context, flattened_index=index,
            reference=float(reference.reshape(-1)[index]),
            approximation=float(approximation.reshape(-1)[index]))
    record["count"] += error.size
    record["absolute_sum"] += float(np.abs(error).sum())
    record["signed_sum"] += float(error.sum())
    record["reference_sum"] += float(reference.sum())
    record["approximation_sum"] += float(approximation.sum())


def finish_errors(record):
    if record["count"]:
        record["mean_absolute"] = record["absolute_sum"] / record["count"]
        record["mean_signed"] = record["signed_sum"] / record["count"]
    return record


def audit(pilot, summary_sha256):
    audit_sources_before = capture_audit_sources()
    identities = {}
    summary, _, _ = admit(pilot, summary_sha256, identities)
    config = summary["configuration"]
    runs = summary["runs"]
    expected = {(seed, arm) for seed in config["seeds"] for arm in ARMS}
    actual = {(run["seed"], run["arm"]) for run in runs}
    if len(runs) != len(expected) or actual != expected or any(
            run["status"] != "completed" or not run["complete_training_trace"] for run in runs):
        raise ValueError("the complete declared factorial roster and traces are required")
    data = json.loads(checked_bytes(pilot / "DATA.json", summary["data_sha256"], identities))
    episodes = {row["id"]: row for row in data["train"]}
    grid = GridSpec(**config["grid"])
    operator = DifferentiableDistributionOperator(grid)
    horizons = sorted({float(dt) for row in data["train"] for dt in row["dt"] if dt > 0})
    if not horizons or max(horizons) > grid.refractory:
        raise ValueError("observed training gaps must match the candidate domain")
    k, c, active = grid.state_count, config["width"], grid.active_count
    centers = np.array([(a + b) / 2 for a, b in zip(grid.active_edges[:-1], grid.active_edges[1:])]
                       + [grid.endpoint + 1 / grid.tail_rate])
    risk_errors = {str(h): error_record() for h in horizons}
    content_errors = {str(r): dict(frobenius=error_record(), summed_content=error_record(),
        probability_exact=True, probability_and_content_bytes=8 * (k + r * (k + c)),
        dense_probability_and_content_bytes=8 * k * (1 + c)) for r in range(1, c)}
    operator_errors = {str(r): dict(second_interval_event_probability_error=error_record(),
        maximum_row_mass_defect=0., minimum_entry=0., maximum_phase_destination_row_l1_error=0.,
        maximum_phase_source_row_l1_error=0.,
        negative_entry_count=0, matrix_applications=0, stored_scalar_count=2 * k * r,
        dense_stored_scalar_count=k * k) for r in (4, 8, 12) if r < k}
    coverage = dict(trace_records=0, posterior_positions=0, maximum_mass_defect=0.,
        minimum_probability=1., first_cell_minimum=1., first_cell_maximum=0.,
        tail_minimum=1., tail_maximum=0., refractory_minimum=1., refractory_maximum=0.,
        boundary_minimum=None, boundary_maximum=None, observed_dt=horizons,
        minimum_positive_probability=None)
    table_cache = {}
    unique_parameters = set()
    physical_fixed = None
    with torch.no_grad():
        for run in runs:
            context = dict(seed=run["seed"], arm=run["arm"])
            directory = pilot / f"seed{run['seed']}-{run['arm']}"
            retained = json.loads(checked_bytes(directory / "result.json", None, identities))
            if retained != run:
                raise ValueError("arm report differs from pinned summary")
            raw = checked_bytes(directory / "training.jsonl", run["training_trace_sha256"], identities)
            rows = [json.loads(line) for line in raw.splitlines()]
            if len(rows) != config["updates"] or len(rows) != run["training_forward_calls"]:
                raise ValueError("training trace count differs from the full planned run")
            for step, row in enumerate(rows):
                if row["step"] != step or row["episode_id"] != run["training_schedule"][step]:
                    raise ValueError("trace step or schedule identity differs")
                episode = episodes[row["episode_id"]]
                if row["dt"] != [episode["dt"]] or row["valid_mask"] != [[True] * len(episode["dt"])]:
                    raise ValueError("trace clocks or masks differ from the pinned data")
                p = np.array([state["probability"][0] for state in row["states"]])
                content = np.array([state["content_mass"][0] for state in row["states"]])
                if p.shape != (len(episode["dt"]), k) or content.shape != (len(p), k, c):
                    raise ValueError("unexpected complete posterior/content dimensions")
                if not np.isfinite(p).all() or not np.isfinite(content).all() or p.min() < 0:
                    raise ValueError("invalid retained posterior")
                defect = float(np.abs(p.sum(-1) - 1).max())
                if defect > 2e-6:
                    raise ValueError("retained posterior is outside the model mass contract")
                parameters = row["physical_parameters"]
                key = tuple(float(parameters[name]) for name in
                            ("log_boundary", "mu", "sigma", "absolute_reset", "discount"))
                if physical_fixed is None:
                    physical_fixed = key[1:]
                if key[1:] != physical_fixed or not np.isfinite(key).all():
                    raise ValueError("a supposedly fixed physical parameter changed")
                unique_parameters.add(key)
                location = dict(context, step=step, episode_id=row["episode_id"])
                coverage["trace_records"] += 1
                coverage["posterior_positions"] += len(p)
                coverage["maximum_mass_defect"] = max(coverage["maximum_mass_defect"], defect)
                coverage["minimum_probability"] = min(coverage["minimum_probability"], float(p.min()))
                positive = p[p > 0]
                old = coverage["minimum_positive_probability"]
                coverage["minimum_positive_probability"] = min(float(positive.min()), old) if old else float(positive.min())
                for label, values in (("first_cell", p[:, 0]), ("tail", p[:, grid.active_cells]),
                                      ("refractory", p[:, active:].sum(-1))):
                    coverage[label + "_minimum"] = min(coverage[label + "_minimum"], float(values.min()))
                    coverage[label + "_maximum"] = max(coverage[label + "_maximum"], float(values.max()))
                for label, fn in (("minimum", min), ("maximum", max)):
                    old = coverage["boundary_" + label]
                    coverage["boundary_" + label] = fn(key[0], old) if old is not None else key[0]
                for rank, entry in content_errors.items():
                    reduced = content_rank(content, int(rank))
                    record_errors(entry["frobenius"], np.zeros(len(p)),
                                  np.linalg.norm(reduced - content, axis=(1, 2)), location)
                    record_errors(entry["summed_content"], content.sum(1), reduced.sum(1), location)
                tensors = [torch.tensor(value, dtype=torch.float64) for value in key]
                occupancy = p[:, :active].sum(-1)
                mean_margin = np.divide(p[:, :active] @ centers, occupancy,
                                        out=np.ones(len(p)), where=occupancy > 0)
                for horizon in horizons:
                    table_key = key + (horizon,)
                    if table_key not in table_cache:
                        table = operator(*tensors[:4], horizon, tensors[4])
                        table_cache[table_key] = (table.matrix.numpy(), table.risk.numpy())
                    matrix, risk = table_cache[table_key]
                    full = p @ risk
                    atom = _first_hit(torch.tensor(mean_margin), horizon, tensors[1], tensors[2]).numpy()
                    reduced = occupancy * atom + p[:, active:] @ risk[active:]
                    record_errors(risk_errors[str(horizon)], full, reduced, location)
                    if horizon == horizons[-1]:
                        for rank, entry in operator_errors.items():
                            reduced_matrix = operator_rank(matrix, int(rank))
                            entry["matrix_applications"] += 1
                            entry["negative_entry_count"] += int((reduced_matrix < -1e-14).sum())
                            for name, value in transition_defects(matrix, reduced_matrix, active).items():
                                entry[name] = min(entry[name], value) if name == "minimum_entry" else max(entry[name], value)
                            record_errors(entry["second_interval_event_probability_error"], (p @ matrix) @ risk,
                                          (p @ reduced_matrix) @ risk, location)
    if source_identity() != summary["source_after"]:
        raise ValueError("executing source changed during the audit")
    for path, digest in identities.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError("an input changed during the audit")
    for entry in risk_errors.values():
        finish_errors(entry)
    for entry in content_errors.values():
        finish_errors(entry["frobenius"])
        finish_errors(entry["summed_content"])
    for entry in operator_errors.values():
        finish_errors(entry["second_interval_event_probability_error"])
        entry["distinct_parameter_matrices"] = len(unique_parameters)
        entry["matrix_count_scope"] = "One application per retained episode/update trace at the largest observed dt; identical physical-parameter matrices are counted repeatedly."
        entry["negative_entry_count_scope"] = "Summed over matrix applications, including repeated matrices; not a count of unique negative coefficients."
        entry["eligible_without_repairs"] = (entry["minimum_entry"] >= -1e-14
            and entry["maximum_row_mass_defect"] <= 5e-11
            and entry["maximum_phase_destination_row_l1_error"] <= 5e-11
            and entry["maximum_phase_source_row_l1_error"] <= 5e-11)
    audit_sources_after = verify_audit_sources(audit_sources_before)
    return dict(schema="hcsn-offline-representation-probes-v3", status="completed",
        reference="pinned finite QPR candidate; not an independent continuum reference",
        source_identity=summary["source_after"], input_identities=identities,
        audit_sha256=audit_sources_before[str(Path(__file__).resolve())],
        audit_sources_before=audit_sources_before, audit_sources_after=audit_sources_after,
        audit_sources_unchanged=audit_sources_before == audit_sources_after,
        coverage=coverage, physical_fixed=dict(zip(("mu", "sigma", "absolute_reset", "discount"), physical_fixed)),
        unique_physical_parameters=len(unique_parameters), constructed_tables=len(table_cache),
        risk_probe_scope="Cartesian product of every saved posterior and every distinct positive observed training dt; not only the actual next dt of that saved posterior.",
        risk_posterior_horizon_pairs=coverage["posterior_positions"] * len(horizons),
        mean_margin_risk=risk_errors, exact_probability_content_svd=content_errors,
        transition_svd_at_largest_observed_dt=operator_errors,
        no_normalization_or_clipping=True, recurrent_compressed_training=False,
        observed_kernel_speedup=None, scientific_admission="HOLD_NO_GO",
        low_noise_tested=False, longer_than_refractory_tested=False,
        independent_continuum_accuracy_established=False,
        limitations=["All saved posteriors are training visits, not a new test source.",
            "Risk probes cross every saved posterior with all observed positive dt values; averaging is over positions, not equal-weight episodes or unseen sequences.",
            "Mean-margin collapse retains active occupancy and every refractory coefficient.",
            "Content SVD re-encodes each dense saved state independently; repeated compression may accumulate error.",
            "Transition SVD compares the second interval event probability (p P) r without observations or survival conditioning; it is not a first-hit CDF over two intervals.",
            "Matrix application and negative-entry counts include repeated physical-parameter matrices; distinct_parameter_matrices reports unique parameter keys at the chosen dt.",
            "Probability and first-hit preservation do not by themselves qualify task quality or reset/phase semantics."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.output.exists():
        parser.error("preserve earlier attempts by choosing a fresh output")
    report = audit(args.pilot, args.summary_sha256)
    report.update(wall_seconds=time.perf_counter() - STARTED, cpu_seconds=time.process_time() - CPU_STARTED)
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "coverage", "wall_seconds", "cpu_seconds")}))


if __name__ == "__main__":
    main()
