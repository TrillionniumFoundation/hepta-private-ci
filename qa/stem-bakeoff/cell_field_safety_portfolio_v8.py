"""Fixed old-first portfolio of two bounded actual-old searches.

Each attempt starts at the same complete origin with the same intended block.
Failed prefixes are never spliced. Every attempted search remains paid and
recorded, including errors. Only a complete zero-slack certificate is returned.
"""

import time

import numpy as np

from cell_field_repair_v7 import repair_sequence as single_ray
from cell_field_safety_v8 import repair_sequence as joint


def repair_sequence(state, train, old_panels, candidate, old_anchors, *, horizon=8,
                    dt=.02, action_bound=4.):
    began, cpu, before = time.perf_counter_ns(), time.process_time_ns(), state.digest()
    if state.protocol["sampler"] != "full_batch":
        raise ValueError("the shared portfolio requires the exact full-batch context")
    intended = np.asarray(candidate, dtype=np.float64).copy()
    anchors = np.asarray(old_anchors, dtype=np.float64).copy()
    attempts, selected, selected_name = [], None, None
    for name, function in (("single_ray_v7", single_ray), ("joint_actual_old_v8", joint)):
        result = function(state, train, old_panels, intended.copy(), anchors.copy(),
            horizon=horizon, dt=dt, action_bound=action_bound)
        attempts.append({"filter": name, "record": result["record"]})
        if state.digest() != before:
            raise RuntimeError("portfolio attempt mutated the shared complete origin")
        selected, selected_name = result, name
        if result["record"]["certified"]:
            break
    record = {key: value for key, value in selected["record"].items() if key != "step_records"}
    record.update(schema="hepta.cell-field-fixed-portfolio.v8", selected_filter=selected_name,
        attempts=attempts, attempt_order=["single_ray_v7", "joint_actual_old_v8"],
        step_record_location="each attempt retains its complete original step_records",
        verified_optimizer_steps=sum(a["record"]["verified_optimizer_steps"] for a in attempts),
        panel_head_evaluations=sum(a["record"]["panel_head_evaluations"] for a in attempts),
        discarded_safe_prefix_steps=sum(a["record"]["prospective_safe_steps"]
            for a in attempts if not a["record"]["certified"]),
        counter_scope="summed original receipts; legacy exceptional partial head batches/failed advance calls can be lower bounds; CPU includes all attempts and every nested error remains ineligible",
        cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began,
        scope="fixed old-first searches; no cross-attempt path splice; all failed work paid; no held-out or global feasibility claim")
    return {**selected, "record": record}
