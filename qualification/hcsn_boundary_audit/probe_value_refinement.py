"""Retrospective refinement diagnosis for one pinned worst continuation case.

Refinement exactly splits the recorded uniform active and phase cells, keeping
the initial reconstructed probability law fixed. It does not retrain a model,
qualify a whole domain, or create an optimized production kernel.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import mpmath as mp
import torch

from qualification.hcsn_boundary_audit.audit_trained_gradients import checked_bytes
from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
from qualification.hcsn_differentiable.training_domain import read_trace, source_hashes
from qualification.hcsn_differentiable.training_domain_audit import _reference
from qualification.hcsn_differentiable.value import perpetual_basis_value


def main():
    started, cpu_started = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh output and preserve previous attempts")
    torch.set_num_threads(1)
    identities = {}
    audit = json.loads(checked_bytes(args.audit, args.audit_sha256, identities))
    checked_bytes(args.trace, audit["trace_sha256"], identities)
    source_before = source_hashes()
    checked_bytes(Path(__file__), None, identities)
    checked_bytes(Path(__file__).with_name("audit_trained_gradients.py"), None, identities)
    header, visits, footer, digest = read_trace(args.trace)
    if (digest != audit["trace_sha256"] or header["sources"] != source_before
            or footer["sources_after"] != source_before or not footer["source_unchanged"]
            or footer["truncated"] or not audit["complete_retained_coverage"]):
        raise ValueError("complete matching source-bound audit and sidecar required")
    chosen = max(audit["visits"], key=lambda item: item.get("maximum_scaled_value_error", -1))
    if chosen["status"] == "error":
        raise ValueError("choose a completed numerical comparison")
    visit = visits[chosen["index"]]
    if visit["index"] != chosen["index"] or visit["model_sha256"] != chosen["model_sha256"]:
        raise ValueError("case identity does not match the pinned audit")
    grid = GridSpec(**visit["grid"])
    p = torch.tensor(visit["posterior"], dtype=torch.float64)
    if p.shape != (1, grid.state_count) or len(visit["dt"]) != 1 or visit["dt"][0] <= 0:
        raise ValueError("this diagnostic requires one posterior and positive fixed gap")
    original = p[0]
    duration = visit["dt"][0]
    values = [visit["parameters"][name] for name in
              ("log_boundary", "mu", "sigma", "absolute_reset", "discount")]
    params = PhysicalParameters(*(torch.tensor(value, dtype=torch.float64) for value in values))
    config = visit["operator"]
    if not config["reset_enabled"]:
        raise ValueError("the continuum reference requires regeneration")
    rows = []
    # The first pair isolates quadrature order at the original basis resolution.
    plan = ((1, grid.quadrature_order), (1, 64), (2, 32), (4, 32), (8, 32), (16, 32))
    with mp.workdps(80), torch.no_grad():
        baseline_reference = float(mp.fsum(mp.mpf(float(w)) * value for w, value in zip(original,
            _reference(grid, values, mp.mpf(config["active_reward"]), mp.mpf(config["hit_reward"])))))
        for factor, order in plan:
            settings = asdict(grid)
            settings.update(active_cells=grid.active_cells * factor,
                            phase_cells=grid.phase_cells * factor, quadrature_order=order)
            fine = GridSpec(**settings)
            lifted = torch.cat((original[:grid.active_cells].repeat_interleave(factor) / factor,
                original[grid.active_cells: grid.active_count],
                original[grid.active_count:].repeat_interleave(factor) / factor))
            assert lifted.shape == (fine.state_count,)
            assert float((lifted.sum() - original.sum()).abs()) <= 2e-15
            independent = float(mp.fsum(mp.mpf(float(w)) * value for w, value in zip(lifted,
                _reference(fine, values, mp.mpf(config["active_reward"]), mp.mpf(config["hit_reward"])))))
            if abs(independent - baseline_reference) > 2e-12:
                raise ValueError("refinement changed the initial reconstructed continuum law")
            operator = DifferentiableDistributionOperator(fine, active_reward=config["active_reward"],
                hit_reward=config["hit_reward"], terminal_reward=config["terminal_reward"], reset_enabled=True)
            t, cpu = time.perf_counter(), time.process_time()
            solution = perpetual_basis_value(operator, params, duration)
            wall, cpu = time.perf_counter() - t, time.process_time() - cpu
            value = float(lifted @ solution.value)
            error = abs(value - independent) / max(1., abs(independent))
            rows.append(dict(grid=settings, state_count=fine.state_count, fixed_dt=duration,
                projected_value=value, continuum_value=independent, scaled_value_error=error,
                meets_original_one_percent_limit=error <= audit["limits"]["scaled_value_error"],
                continuum_initial_law_difference=abs(independent - baseline_reference),
                bellman_residual_maximum=float(solution.bellman_residual.abs().max()),
                rounded_residual_error_estimate=float(solution.residual_error_estimate),
                matrix_build_and_solve_wall_seconds=wall, matrix_build_and_solve_cpu_seconds=cpu,
                dense_transition_scalars=fine.state_count**2,
                hypothetical_width4_probability_content_bytes=8 * fine.state_count * 5))
    if source_hashes() != source_before or any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != value
                                              for path, value in identities.items()):
        raise ValueError("source or evidence changed during the diagnostic")
    report = dict(schema="hcsn-retrospective-value-refinement-v1", status="completed",
        selection="maximum scaled error in the supplied pinned audit, selected retrospectively after that audit completed",
        case=chosen, source_identity=source_before, input_identities=identities, rows=rows,
        original_limit=audit["limits"]["scaled_value_error"], numerical_domain_qualified=False,
        training_repeated=False, task_quality_measured=False, optimized_runtime_claim=False,
        cost_scope="one uncached transition/reward build plus dense Bellman solve per row; no network training; shared host",
        scientific_admission="HOLD_NO_GO", wall_seconds=time.perf_counter()-started,
        cpu_seconds=time.process_time()-cpu_started)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status":report["status"],"rows":rows,"wall_seconds":report["wall_seconds"]}))


if __name__ == "__main__":
    main()
