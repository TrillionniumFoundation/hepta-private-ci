"""Read the frozen E5 material plan and emit a prospective two-axis design (no runner).

Usage: python e5_scale_design.py NEXT_TRAINING_PLAN.json [--cells 1 2 4]
The input is the exact NEXT_TRAINING_PLAN.json from hepta-private-ci/PR 6836.
Only the public plan is read. This program does not allocate or submit work.
"""

import argparse
import hashlib
import json
from pathlib import Path


PLAN_COMMIT = "8288481188abb2d01b4248f6cad635a375e13229"
PLAN_PATH = "qualification/cell-e5-material-adapter-20261120/NEXT_TRAINING_PLAN.json"
PLAN_SHA256 = "f803383cbc70456d92799b78e96d70dff62cbfd84d13a4c1f1c34d9450c32e26"


def read_plan(path):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != PLAN_SHA256:
        raise ValueError("E5 source plan digest differs from the registered input")
    return json.loads(data)


def propose(plan, cell_counts):
    """Cell counts are simultaneous worker slots, independent of the user count."""
    if any(type(count) is not int or count < 1 for count in cell_counts):
        raise ValueError("worker counts must be positive integers")
    cells = sorted(set(cell_counts))
    if len(cells) < 2 or cells[0] != 1:
        raise ValueError("include a serial baseline and at least one larger count")
    points = []
    comparisons = []
    for source_point in plan["points"]:
        regime = source_point["regime"]
        users = source_point["source_count"]
        units = source_point["proposed_optimizer_updates_if_unit_binding_accepted"]
        # One proposed logical update sees at most one user's material.
        feasible = units >= users
        if regime == "fixed_per_source":
            workers = cells
        elif regime == "fixed_total":
            workers = [1]
        else:
            raise ValueError("unknown source budget regime")
        for workers_count in workers:
            point_id = f"{regime}/u{users}/c{workers_count}"
            points.append(
                {
                    "id": point_id,
                    "regime": regime,
                    "proposed_users": users,
                    "proposed_parallel_cells": workers_count,
                    "proposed_units": units,
                    "max_distinct_users_if_enrolled": min(units, users),
                    "covers_every_user_under_unit_binding": feasible,
                }
            )
            if not feasible:
                continue
            if regime == "fixed_total" and users > 1:
                comparisons.append(
                    {
                        "estimate": "diversity",
                        "baseline": "fixed_total/u1/c1",
                        "treatment": point_id,
                    }
                )
            if regime == "fixed_per_source" and workers_count > 1:
                comparisons.append(
                    {
                        "estimate": "system",
                        "baseline": f"fixed_per_source/u{users}/c1",
                        "treatment": point_id,
                    }
                )
    return {
        "schema": "hepta.e5.prospective-human-cell-design.v1",
        "source_plan": {
            "commit": PLAN_COMMIT,
            "path": PLAN_PATH,
            "sha256": PLAN_SHA256,
        },
        "status": "PROPOSAL_ONLY",
        "scope": (
            "Proposed comparisons. Arms and replicates may share the existing "
            "authorized budget according to its terms. Before execution, account "
            "for their combined cost against the remaining allowance."
        ),
        "points": points,
        "proposed_comparisons": comparisons,
        "unbound_compute_fields_in_source_plan": [
            key
            for key, value in plan["compute_budget_required"].items()
            if value is None
        ],
        "unbound_verification_fields_in_source_plan": [
            key
            for key, value in plan["verification_budget_required"].items()
            if value is None
        ],
        "diversity_protocol": {
            "intervention": (
                "Keep one Cell and vary the number of distinct authenticated "
                "humans who contribute."
            ),
            "exposure": (
                "Verify each roster member contributed permitted material to a "
                "committed update. Record the distinct pseudonymous user count, "
                "exposure share per user, domain coverage and duplicate fraction."
            ),
            "design": (
                "Randomize nested user cohorts within domain strata across "
                "independent enrollment blocks. Freeze seeds and repeat counts."
            ),
            "control": (
                "Use the same parent, tokenizer, optimizer, hardware and update "
                "rule within each block. Evaluate on the same independent future "
                "tasks and retention panel."
            ),
            "compute": (
                "Freeze numeric caps and matching tolerances. Match realized "
                "training MACs (including attention, loss and recomputation), "
                "verification work and accelerator service seconds per arm. "
                "Record padded, prompt and target tokens, CPU seconds and joules. "
                "Exclude unmatched comparisons."
            ),
            "outcome": (
                "For each evaluation user, compute the difference in task success "
                "between candidate and frozen parent. Average equally over users "
                "and compare with the one-user arm. Include all assigned tasks "
                "and predeclare timeout handling."
            ),
            "uncertainty": (
                "Preregister paired uncertainty over independent training "
                "cohorts and held-out users, sample sizes and a retention "
                "noninferiority margin before outcomes."
            ),
        },
        "system_protocol": {
            "intervention": (
                "Vary the simultaneous Cell count within a fixed, authenticated "
                "user roster."
            ),
            "control": (
                "Use the same per-user token, compute and verification limits, "
                "exposure list, parent, hardware pool, offered load, task order "
                "and seeds. Randomize run order within blocks. Log each user's "
                "resource use including retries."
            ),
            "train_semantics": (
                "Freeze the same dependency graph, Cell update rule, "
                "synchronization and merge order for serial and parallel runs. "
                "Record committed candidate lineage and apply the same teacher-off "
                "quality and retention gates. A serial dependency chain permits "
                "one active update at a time."
            ),
            "overlap": (
                "Record distinct worker IDs and job start and finish on a common "
                "monotonic clock, or record clock-error bounds across hosts. "
                "Require sustained concurrency over the preregistered interval "
                "and report busy Cell-seconds at each concurrency level."
            ),
            "outcome": (
                "Divide the count of unique verified useful work IDs by elapsed "
                "batch seconds, from submission through drain. Include queueing, "
                "synchronization, verification and retries. Report speedup against "
                "serial, failures, p95 arrival-to-verdict latency and retention."
            ),
            "uncertainty": (
                "Repeat matched serial and parallel blocks and estimate paired "
                "speedup intervals across independent runs. Report devices per "
                "Cell, shared resources, workload skew and clock uncertainty."
            ),
        },
        "entry": (
            "Before a new run, verify the qualifying cross-user candidate, "
            "independent permissions and receipts, fresh sealed tasks and frozen "
            "cost limits. Confirm that the run fits the remaining authorized "
            "budget and available host capacity."
        ),
        "measurements": [],
        "observed_diversity_effect": None,
        "observed_system_speedup": None,
        "runs_authorized_by_this_design": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--cells", type=int, nargs="+", default=[1, 2, 4])
    args = parser.parse_args()
    try:
        result = propose(read_plan(args.plan), args.cells)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
