"""Qualify the actual verifier-feedback execution on controlled and natural tasks."""
import time

from binding_campaign_utils import write
from binding_protocol import score_binding_probabilities
from retention_data import natural_metrics
from revision_execution import execute_revision


def feedback_panel(root, name, model, verifier, provenance, cases, bank, mode, *, binding):
    """Measure the exact real/zero three-Reader/two-verifier closed loop, not forward()."""
    if mode not in ("real", "zero"):
        raise ValueError("registered feedback qualification execution required")
    probabilities, physical = [], []
    for start in range(0, len(cases), 16):
        selected = cases[start:start + 16]
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        batch = bank.batch(selected)
        prep = dict(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall)
        result = execute_revision(batch.features(), model, verifier, mode=mode,
            verifier_provenance=provenance, case_ids=[c.case_id for c in selected],
            source_sha256s=[c.source_hash for c in selected])
        probabilities.extend(row[1] for row in result["probabilities"])
        physical.append(dict(case_ids=[c.case_id for c in selected],
            feature_preparation=prep, execution=result))
    metrics = (score_binding_probabilities if binding else natural_metrics)(cases, probabilities)
    write(root, name + ".json", dict(metrics=metrics, probabilities=probabilities,
        case_ids=[c.case_id for c in cases], physical_batches=physical, mode=mode,
        execution="actual_three_reader_two_frozen_verifier_steps", labels_entered_model=False,
        threshold_selected=False, costs=dict(
            cpu_ns=sum(row["feature_preparation"]["cpu_ns"]+row["execution"]["cost"]["cpu_ns"] for row in physical),
            wall_ns=sum(row["feature_preparation"]["wall_ns"]+row["execution"]["cost"]["wall_ns"] for row in physical),
            callback_costs_nested=True, formula_flops=None, individual_case_latency=False)))
    return metrics
