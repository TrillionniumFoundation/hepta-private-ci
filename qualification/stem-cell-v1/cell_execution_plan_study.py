"""Precommit finite-work plans on calibration inputs, then measure new inputs.

Called by the existing population study. No new model/data loader or authority.
"""
from dataclasses import asdict
from pathlib import Path
import time

import torch

from cell_execution_plan import MAX_FOLDED_BYTES, _binding, calibrate, choose, execute
from development_study_data import write_once
from development_tensors import parameter_digest

SCOPE = "fa5c847ec8e591afa47c303f4e8cc7da17a8e798a5c6f94f2b351966b57bc091"


def study_plan(bank, calibration_features, measured_features, fids, cids, output):
    """Compare finite counts 1/4/16 and zero/64 MiB extra compiled storage.

    Only layouts match; measured feature values were not used to fit cost
    estimates. Calibration cost is charged ONCE outside the six episodes.
    No held-out task labels enter this function. Repeats are timing experiments,
    not independent outcome observations. No latency-tail or energy claims.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    total = time.perf_counter_ns()
    try:
        if torch.is_grad_enabled():
            raise ValueError("timing study requires disabled autograd")
        binding = _binding(bank, calibration_features, fids, cids, SCOPE)
        if binding != _binding(bank, measured_features, fids, cids, SCOPE):
            raise ValueError("calibration and measured layouts must match")
        if torch.equal(calibration_features, measured_features):
            raise ValueError("new-value measurement must not reuse calibration inputs")
        write_once(output/"PLAN.json", {"binding": binding, "passes": [1, 4, 16],
            "compiled_budgets_bytes": [0, MAX_FOLDED_BYTES], "production_authorized": False})
        profile, observation = calibrate(bank, calibration_features, fids, cids, scope_digest=SCOPE)
        write_once(output/"calibration.json", observation)
        write_once(output/"profile.json", asdict(profile))
        plans = [choose(profile, passes=n, compiled_byte_budget=b)
                 for n in (1, 4, 16) for b in (0, MAX_FOLDED_BYTES)]
        write_once(output/"choices-before-execution.json", plans)
        reports = []
        # Independent equation check outside each measured executor invocation.
        reference = bank(measured_features[fids], cids)
        if not torch.isfinite(reference).all():
            raise ValueError("nonfinite original reference")
        for i, plan in enumerate(plans):
            logits, report = execute(bank, measured_features, fids, cids, profile,
                passes=plan["passes"], compiled_byte_budget=plan["compiled_byte_budget"],
                scope_digest=SCOPE)
            if report["plan"] != plan:
                raise ValueError("execution changed the precommitted plan")
            error = float((logits-reference).abs().max())
            if error > 1e-4 or not torch.equal(logits.argmax(1), reference.argmax(1)):
                raise ValueError("selected path changed the learned decision")
            report.update(max_abs_logit_error=error, argmax_reversals=0)
            write_once(output/f"episode-{i}.json", report)
            reports.append(report)
        result = {"schema": "hepta.stem.finite-plan-study.v1", "parameter_digest": parameter_digest(bank),
            "profile_calibration_wall_ns_charged_once": profile.calibration_wall_ns,
            "episode_count": len(reports), "episodes": reports,
            "total_study_wall_ns": time.perf_counter_ns()-total,
            "task_quality_change_claimed": False, "new_encoder_calls": 0,
            "source_scope_is_caller_declared_not_authenticated": True,
            "estimated_times_are_not_guarantees": True, "production_authorized": False}
        write_once(output/"result.json", result)
        return result
    except Exception as error:
        write_once(output/"FAILED.json", {"error_type": type(error).__name__, "message": str(error)})
        raise
