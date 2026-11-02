"""Exhaust every reachable policy history in the fixed R14 finite task.

This extends sampled replay coverage, not scientific confirmation. It does not
certify arbitrary beliefs, models, longer horizons or global rounding bounds.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from threadpoolctl import threadpool_limits

from ..task_aligned_r14_20261101.models import GenericHMM, restore
from ..task_aligned_r14_20261101.task import TaskModel
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP
from .attainability import FIELDS, NUMERICAL_TOLERANCE, R14_FREEZE, R14_SOURCE, digest, exact_episode, schedule_support
from .planner import BatchedBeliefDP


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


class ComparedPlanner:
    def __init__(self, common):
        prices = dict(reset_cost=common.reset_cost, latency_price=common.latency_price)
        self.reference, self.batched = ExactBeliefDP(common, **prices), BatchedBeliefDP(common, **prices)
        self.calls, self.max_error, self.actions = 0, 0., Counter()
        self.transcript = hashlib.sha256()
        self.worst = None

    def __getattr__(self, name):
        return getattr(self.reference, name)

    def choose(self, belief, schedule, budget=2):
        old = self.reference.action_values(belief, schedule, budget)
        new = self.batched.action_values(belief, schedule, budget)
        if tuple(old) != tuple(new):
            raise ArithmeticError("Legal-action order differs")
        error = max(abs(old[key] - new[key]) for key in old)
        action = self.reference.choose(belief, schedule, budget)
        selected = self.batched.choose(belief, schedule, budget)
        witness = dict(belief=np.asarray(belief).tolist(), schedule=list(schedule), budget=int(budget),
                       reference_q=old, batched_q=new, reference_action=action, batched_action=selected)
        if not np.isfinite(list(new.values())).all() or error > NUMERICAL_TOLERANCE or action != selected:
            raise ArithmeticError("Reachable-policy discrepancy: " + canonical(witness).decode())
        self.calls += 1
        self.actions[action] += 1
        self.transcript.update(canonical(witness))
        if self.worst is None or error > self.max_error:
            self.max_error, self.worst = error, witness
        return selected


def audit(run, reference_path, replay_freeze_path, output):
    started, wall = time.process_time(), time.perf_counter()
    run, reference_path, replay_freeze_path, output = map(Path, (run, reference_path, replay_freeze_path, output))
    records_path = output.with_name(output.stem + ".records.json.gz")
    if output.exists() or records_path.exists():
        raise FileExistsError("Retain previous audit evidence")
    freeze_path = run / "FREEZE.json"
    protocol_path = HERE.parent / "task_aligned_r14_20261101/PROTOCOL.json"
    if digest(freeze_path) != R14_FREEZE:
        raise ValueError("R14 candidate freeze identity differs")
    freeze, protocol = json.loads(freeze_path.read_text()), json.loads(protocol_path.read_text())
    previous, replay = json.loads(reference_path.read_text()), json.loads(replay_freeze_path.read_text())
    if (freeze["source_commit"] != R14_SOURCE or digest(protocol_path) != freeze["protocol_sha256"]
            or previous["fit_seeds"] != protocol["fit_seeds"] or not previous["complete_registered_fit_set"]
            or previous["frozen_candidate_sha256"] != R14_FREEZE
            or previous["diagnostic_source_sha256"] != digest(HERE / "attainability.py")):
        raise ValueError("Prior complete enumeration or original protocol identity differs")
    seals = {str(ROOT / name): sha for name, sha in freeze["sources"].items()}
    seals.update({str(ROOT / name): sha for name, sha in replay["sources"].items()})
    for path in (freeze_path, protocol_path, reference_path, replay_freeze_path, Path(__file__)):
        seals[str(path)] = digest(path)

    def verify():
        for name, expected in seals.items():
            if digest(name) != expected:
                raise ValueError("Sealed source/input changed: " + name)

    def training_file(seed, name):
        relative = str(Path(str(seed)) / name)
        path = run / relative
        if relative not in freeze["artifacts"] or digest(path) != freeze["artifacts"][relative]:
            raise ValueError("Frozen checkpoint differs: " + relative)
        seals[str(path)] = digest(path)
        return json.loads(path.read_text())

    verify()
    world, records, global_worst = TaskModel(), [], None
    if world.identity != previous["world_identity"]:
        raise ValueError("Actual task world differs")
    for seed in protocol["fit_seeds"]:
        training = training_file(seed, "TRAINING.json")
        selected = freeze["selected_ordinary"][str(seed)]
        if training["selected_ordinary"] != selected or training["status"] != "completed":
            raise ValueError("Original candidate selection differs")
        common = restore(training_file(seed, "common_model.json")["model"]).build_cell()
        ordinary = GenericHMM(common) if selected == "generic_hmm" else restore(training_file(seed, selected + ".json")["final_model"])
        hx = restore(training_file(seed, "hx_distribution.json")["final_model"])
        for domain in ("iid", "ood"):
            old_fit = next(row for row in previous["domains"][domain]["fits"] if row["seed"] == seed)
            support = schedule_support(protocol[domain + "_durations"], protocol["horizon"])
            if [tuple(row["schedule"]) for row in old_fit["schedules"]] != list(support):
                raise ValueError("Prior schedule support differs")
            for schedule, old_row in zip(support, old_fit["schedules"]):
                for arm, actor in (("B", ordinary), ("D", hx)):
                    checked = ComparedPlanner(common)
                    result = exact_episode(world, actor, checked, schedule, protocol["read_budget"])
                    errors = {key: abs(result[key] - old_row[arm][key]) for key in FIELDS}
                    if (max(errors.values()) > NUMERICAL_TOLERANCE or checked.calls != result["nodes"]
                            or any(result[key] != old_row[arm][key] for key in ("nodes", "leaves", "first_action"))):
                        raise ArithmeticError("Prior full-episode expectation or history topology differs")
                    record = dict(seed=seed, domain=domain, arm=arm, schedule=list(schedule), result=result,
                                  expectation_errors=errors, q_max_error=checked.max_error,
                                  decisions_checked=checked.calls, action_histogram=dict(checked.actions),
                                  decision_transcript_sha256=checked.transcript.hexdigest(),
                                  guarded_fallbacks=checked.batched.reference_fallbacks)
                    records.append(record)
                    if global_worst is None or checked.max_error > global_worst["error"]:
                        global_worst = dict(seed=seed, domain=domain, arm=arm, schedule=list(schedule),
                                            error=checked.max_error, decision=checked.worst)
            print(json.dumps(dict(seed=seed, domain=domain, cases_complete=len(records))), flush=True)
    verify()
    expected_count = len(protocol["fit_seeds"]) * 2 * 27 * 2
    if len(protocol["fit_seeds"]) != 8 or len(records) != expected_count or expected_count != 864:
        raise ValueError("Incomplete registered audit coverage")
    raw = canonical(records)
    output.parent.mkdir(parents=True, exist_ok=True)
    with records_path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    report = dict(schema="hcsn.r15.reachable-planner-exhaustive.v1", cases=len(records),
                  decision_nodes_checked=sum(row["decisions_checked"] for row in records),
                  terminal_histories=sum(row["result"]["leaves"] for row in records),
                  q_max_error=max(row["q_max_error"] for row in records), worst_q_witness=global_worst,
                  expectation_max_error=max(max(row["expectation_errors"].values()) for row in records),
                  all_actions_equal=True, all_topologies_equal=True, prior_expectations_match=True,
                  original_candidate_sha256=R14_FREEZE, original_source_commit=R14_SOURCE,
                  world_identity=world.identity, seals=seals, seals_unchanged=True,
                  records_file=records_path.name, records_file_sha256=digest(records_path),
                  records_content_sha256=hashlib.sha256(raw).hexdigest(), numerical_tolerance=NUMERICAL_TOLERANCE,
                  threadpool_limit=1, guard_is_rigorous_rounding_bound=False,
                  new_confirmation_opened=False, scientific_acceptance_changed=False,
                  scope="All positive-probability actual-policy histories, 8 frozen fits x 2 domains x 27 schedules x B/D; no probability pruning",
                  limits="Fixed finite R14 task only, not arbitrary beliefs/models, longer horizons, continuum accuracy, or new efficacy confirmation. CPU is diagnostic work, not a speed comparison.",
                  cpu_seconds=time.process_time()-started, wall_seconds=time.perf_counter()-wall)
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode()) >= 500000 or records_path.stat().st_size >= 500000:
        raise ValueError("Audit artifact exceeds publication size policy")
    with output.open("x") as stream:
        stream.write(encoded)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--replay-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        report = audit(args.run, args.reference, args.replay_freeze, args.output)
    print(json.dumps({key: report[key] for key in ("cases", "decision_nodes_checked", "q_max_error", "expectation_max_error", "seals_unchanged")}, sort_keys=True))


if __name__ == "__main__":
    main()
