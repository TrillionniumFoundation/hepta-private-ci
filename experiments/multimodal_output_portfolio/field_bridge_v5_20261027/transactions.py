"""Matched 48-step decisions with explicit 48- or 8-step guard transactions."""

from ..field_bridge_20261027.adapters import frozen_base_hash
from ..field_bridge_v3_20261027.learning import (
    guarded_block, hard_panel, restore, schedule, snapshot, state_identity, update,
)
from ..field_bridge_v3_20261027.training_common import configuration, object_hash, require


def execute(context, model, optimizer, start, action_index, schedule_id, grain, journal):
    """Keep accepted prefixes; rejection restores only the current transaction.

    Each attempted microstep consumes its scheduled time and actual compute even
    on rejection or a zero multiplier. The decision action stays fixed for all
    six subtransactions. Exceptions restore the active slice and abort the path.
    """
    p = configuration(context.protocol)
    require(type(grain) is int and grain in (8, 48), "Unregistered transaction grain")
    require(type(start) is int and start in range(0, 288, 48), "Invalid decision clock")
    require(type(action_index) is int and 0 <= action_index < 4, "Invalid action")
    if grain == 48:
        before, before_cost = state_identity(model, optimizer), context.costs.snapshot()
        try:
            receipt = guarded_block(context, model, optimizer, start, action_index, schedule_id)
        except BaseException as error:
            journal.append({"kind": "transaction_exception", "start": start, "grain": grain,
                "error_type": type(error).__name__, "before": before,
                "after": state_identity(model, optimizer), "resources": context.costs.since(before_cost)})
            raise
        journal.append({"kind": "transaction", "grain": grain, "receipt": receipt})
        return [receipt]
    receipts = []
    for offset in range(start, start + 48, grain):
        costs, saved = context.costs, snapshot(model, optimizer)
        before_cost, base = costs.snapshot(), frozen_base_hash(model)
        costs.add("transaction_snapshots")
        rows = schedule(context.seed, schedule_id, offset, grain, context.protocol)
        journal.append({"kind": "transaction_start", "start": offset, "end": offset + grain,
                        "before": saved["identity"], "schedule_sha256": object_hash(rows)})
        information = []
        try:
            for row in rows:
                adapt, clean = context.batches(row)
                information.append(update(model, context.original, optimizer, adapt, clean,
                    context.action, p["multipliers"][action_index], row["noise_seed"],
                    context.protocol, costs))
            candidate = state_identity(model, optimizer)
            guard = hard_panel(model, context.guard, {"reward": context.observers["reward"]},
                context.action, context.protocol, costs, "candidate_guard")
            delta = float((guard["values"]["reward"] - context.baseline_guard["values"]["reward"]).mean())
            accepted = delta >= p["guard_min_delta"]
            if accepted:
                costs.add("accepted_blocks")
            else:
                restore(model, optimizer, saved)
                costs.add("rejected_blocks")
                costs.add("discarded_gradient_microsteps", grain)
            require(frozen_base_hash(model) == base, "Frozen base changed")
            if action_index == 0:
                require(state_identity(model, optimizer) == saved["identity"], "Zero action changed optimizer")
        except BaseException as error:
            restore(model, optimizer, saved)
            journal.append({"kind": "transaction_exception", "start": offset,
                "error_type": type(error).__name__, "completed_microsteps": len(information),
                "after": state_identity(model, optimizer), "resources": costs.since(before_cost)})
            raise
        receipt = {"start": offset, "end": offset + grain, "action_index": action_index,
            "multiplier": p["multipliers"][action_index], "schedule_id": schedule_id,
            "schedule_sha256": object_hash(rows), "before": saved["identity"], "candidate": candidate,
            "after": state_identity(model, optimizer), "accepted": accepted, "guard_delta": delta,
            "guard_values": guard["values"]["reward"].tolist(),
            "guard_output_sha256": guard["output_sha256"], "first_gradient": information[0],
            "last_gradient": information[-1], "clock_advances_on_rejection": True,
            "resources": costs.since(before_cost)}
        journal.append({"kind": "transaction", "grain": grain, "receipt": receipt})
        receipts.append(receipt)
    return receipts
