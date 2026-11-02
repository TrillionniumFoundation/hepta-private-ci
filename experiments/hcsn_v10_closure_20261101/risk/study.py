"""Bounded flush reservation with separate service timeout/output-miss risks.

Known synthetic sensor/worker laws are used only for execution qualification.
This is not a fitted AV head or an analytic-core benefit experiment.
"""

import argparse
from dataclasses import asdict
import difflib
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, CorrectnessValue, CostWeights, Modality,
    PrefixObservation, StopEvaluation, VisibleContent,
)
from experiments.hcsn_v8_execution_20261101.scheduler.execution import (
    ReadResult as OldReadResult, run_episode as old_run,
)
from experiments.hcsn_v8_execution_20261101.scheduler.planning import (
    Plan, Read, ServiceEstimate, choose_plan,
)
from .execution import FinalizationBudget, LogicalClock, RealClock, ReadResult, run_episode

MODULE = "experiments.hcsn_v10_closure_20261101.risk.study"
HEAD_ID = "synthetic-bsc-v10-public-law"
COSTS = CostWeights(observation=.02, elapsed_second=.005, deadline_miss=1.)
HARD_DEADLINE = 2.4
BUDGET = FinalizationBudget()
VIDEO = Plan((Read(Modality.VIDEO, 1),))
ARMS = ("old_full", "old_zero", "reserve_full", "reserve_zero",
        "reserve_fixed_old_zero", "old_zero_fixed_reserve")
REPO = Path(__file__).resolve().parents[3]


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pause(clock, seconds):
    clock.wait_until(clock.now() + seconds)


def posterior(content):
    probability = [1., 1.]
    for modality, accuracy in ((Modality.AUDIO, .72), (Modality.VIDEO, .96)):
        observation = content.observation(modality)
        if observation is not None:
            for label in (0, 1):
                probability[label] *= accuracy if observation.raw[0] == label else 1-accuracy
    return tuple(p/sum(probability) for p in probability)


class Head:
    def __init__(self, clock, delay=.015):
        self.clock, self.delay = clock, delay

    def evaluate(self, content):
        pause(self.clock, self.delay)
        probabilities = posterior(content)
        return StopEvaluation(probabilities, CorrectnessValue(max(probabilities), HEAD_ID))


class Forecast:
    kind = BackendKind.DIRECT_HISTORY
    reader_id = "v10-public-law-content-fallback"

    def evaluate(self, content, state, plan):
        probabilities = posterior(content)
        current = max(probabilities)
        if plan == VIDEO and content.video is None:
            after_success = sum(max(probabilities[0] * (.96 if x == 0 else .04),
                                    probabilities[1] * (.96 if x == 1 else .04)) for x in (0, 1))
            current = .5 * after_success + .5 * current
        return CorrectnessValue(current, HEAD_ID)


class ServiceModel:
    """Public law: .5 service timeout; output risk follows execution contract.

The reserve output-risk statement is conditional on the explicitly bounded
head, serialization, sink and scheduling guard. It is not an OS hard guarantee.
"""
    def __init__(self, contract, zero=False):
        self.contract, self.zero = contract, zero
        self.records = []

    def estimate(self, content, plan, now, service_deadline):
        service_timeout = .5
        output_miss = .5 if self.contract == "old" else 0.
        duration = .5 * .08 + .5 * max(0., service_deadline-now)
        self.records.append({"plan": plan.identity, "service_timeout_probability": service_timeout,
            "output_deadline_miss_probability_before_intervention": output_miss,
            "output_deadline_miss_probability_used": 0. if self.zero else output_miss,
            "service_deadline": service_deadline, "conditional_bounded_finalization": self.contract == "reserve"})
        return ServiceEstimate(duration, 0. if self.zero else output_miss, plan.requested_reads)


def packet(step, clock, world, symbol):
    return PrefixObservation(step.identity, world["id"], step.modality, step.prefix_end,
        step.prefix_end, clock.now(), (float(symbol),), (float(symbol),), "synthetic-bsc-v10", (0., step.prefix_end))


class Service:
    mode = "controlled synthetic payloads; public fast/slow law; actual owned workers"

    def __init__(self, world, logical, result_type=ReadResult):
        self.world, self.logical, self.drains = world, logical, 0
        self.result_type = result_type

    def request(self, step, clock):
        symbol = self.world[step.modality.value]
        delay = .02 if step.modality == Modality.AUDIO else (.08 if self.world["fast"] else 1.8)
        target = max(float(step.prefix_end), clock.now()) + delay
        child = None
        if not self.logical:
            child = subprocess.Popen([sys.executable, "-m", MODULE, "worker", "--delay",
                str(max(0., target-clock.now())), "--symbol", str(symbol)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        owner = self

        class Pending:
            def wait_until(self, deadline, clock):
                if owner.logical:
                    clock.wait_until(min(target, deadline))
                    if target > deadline:
                        return None
                    return owner.result_type(observation=packet(step, clock, owner.world, symbol))
                try:
                    output, errors = child.communicate(timeout=max(0., deadline-clock.now()))
                except subprocess.TimeoutExpired:
                    return None
                if child.returncode:
                    return owner.result_type(error=f"worker failed: {errors[:128]}")
                decoded = json.loads(output)
                return owner.result_type(observation=packet(step, clock, owner.world, decoded["symbol"]))

            def drain(self, clock):
                if owner.logical:
                    clock.wait_until(target)
                else:
                    child.communicate(timeout=5)
                owner.drains += 1

        return Pending()


def select(world, contract, zero):
    clock = LogicalClock()
    clock.wait_until(1.02)
    content = VisibleContent(world["id"], CacheBudget(1024, max_prefix_end=1, max_events=2))
    content = content.accept(packet(Read(Modality.AUDIO, 1), clock, world, world["audio"]), clock.now())
    cutoff = HARD_DEADLINE-(BUDGET.reserve_seconds if contract == "reserve" else 0.)
    return choose_plan(content, None, Head(clock), Forecast(), ServiceModel(contract, zero),
                       (VIDEO,), clock.now(), cutoff, COSTS)[0]


def run_world(world, arm, mode, *, head_delay=.015, sink_delay=.015):
    contract = "old" if arm.startswith("old") else "reserve"
    zero = "zero" in arm
    fixed = None
    if arm == "reserve_fixed_old_zero":
        chosen = select(world, "old", True)
        fixed = () if chosen is None else (chosen,)
    elif arm == "old_zero_fixed_reserve":
        chosen = select(world, "reserve", False)
        fixed = () if chosen is None else (chosen,)
    clock = LogicalClock() if mode == "logical" else RealClock()
    head, model = Head(clock, head_delay), ServiceModel(contract, zero)
    service = Service(world, mode == "logical", OldReadResult if contract == "old" else ReadResult)
    flushed = []
    own_cpu, wall = time.process_time(), time.perf_counter()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    with tempfile.TemporaryFile() as sink_file:
        def sink(data):
            pause(clock, sink_delay)
            sink_file.write(data)
            sink_file.flush()
            os.fsync(sink_file.fileno())
            flushed.append(data)

        runner = old_run if contract == "old" else run_episode
        extra = {} if contract == "old" else {"finalization_budget": BUDGET}
        receipt = runner(world["id"], CacheBudget(1024, max_prefix_end=1, max_events=2),
            head, Forecast(), model, service, sink, clock=clock, deadline=HARD_DEADLINE,
            horizon=1, max_requests=2, max_decisions=1, costs=COSTS, fixed_plans=fixed, **extra)
        sink_file.seek(0)
        if sink_file.read() != flushed[0]:
            raise RuntimeError("Flushed bytes differ")
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    correct = int(receipt["output"]["predicted_class"] == world["target"])
    utility = correct-receipt["observation_fee"]-receipt["latency_fee"]-receipt["deadline_penalty"]
    return {"world_id": world["id"], "arm": arm, "clock_mode": mode, "contract": contract,
        "correct": correct, "net_utility": utility, "receipt": receipt, "public_risk_forecasts": model.records,
        "flushed_output": json.loads(flushed[0]), "drains": service.drains,
        "registered_head_delay": head_delay, "registered_sink_delay": sink_delay,
        "own_cpu_seconds": time.process_time()-own_cpu, "wall_seconds_including_drain": time.perf_counter()-wall,
        "children_cpu_seconds": child_after.ru_utime+child_after.ru_stime-children.ru_utime-children.ru_stime}


def worlds():
    result = []
    for target, a_correct, v_correct, fast in itertools.product((0, 1), repeat=4):
        result.append({"id": f"v10-new-bsc-{len(result):02}", "target": target,
            "audio": target if a_correct else 1-target, "video": target if v_correct else 1-target,
            "fast": bool(fast), "weight": .5*(.72 if a_correct else .28)*(.96 if v_correct else .04)*.5})
    return result


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).parent
    legacy = REPO / "experiments/hcsn_v8_execution_20261101/scheduler/execution.py"
    paths = [here/name for name in ("study.py", "execution.py", "test_study.py", "audit.py")]
    paths += [legacy, REPO/"experiments/hcsn_v8_execution_20261101/scheduler/planning.py",
              REPO/"experiments/hcsn_v7_support_20261101/content_interface/content_interface.py"]
    write(out/"PLAN.json", {"schema": "hcsn-v10-flush-reservation.v1",
        "baseline_commit": "8cc469fcb0e6527fac56e26b65baa3ae1c09c86b",
        "source_sha256": {str(p.relative_to(REPO)): sha(p) for p in paths},
        "source_derivation": "execution.py is isolated v8 executor copy plus explicit service cutoff/finalization-budget accounting",
        "head_accuracy": {"audio": .72, "video": .96}, "service_timeout_probability": .5,
        "content_value": "identical expected correctness includes half successful video and half current-content timeout fallback",
        "risk_target": "extra contract cost of actual final-output deadline miss, separate from lost content accuracy",
        "hard_deadline": HARD_DEADLINE, "finalization_budget": asdict(BUDGET), "costs": asdict(COSTS),
        "head_delay": .015, "sink_delay": .015, "arms": ARMS,
        "logical_worlds": worlds(), "real_world_ids": [f"v10-new-bsc-{i:02}" for i in (1, 2, 4, 7, 8, 11, 13, 14)],
        "real_selection": "predeclared odd-parity half-factor design, descriptive unweighted; not iid cohort",
        "order": "Latin rotation by world index modulo six",
        "stress_probes": [{"name": "slow_head_outside_contract", "head_delay": .45, "sink_delay": .015},
                          {"name": "slow_sink_outside_contract", "head_delay": .015, "sink_delay": .45}],
        "qualification": "all normal reserve actual runs timely and within declared finalization budgets; late workers excluded and drained after flush",
        "scope": "registered synthetic bounded head/sink execution; no arbitrary head/sink or scheduling hard guarantee",
        "architecture_acceptance": False, "real_AV_confirmation": False})
    diff = difflib.unified_diff(legacy.read_text().splitlines(keepends=True),
        (here/"execution.py").read_text().splitlines(keepends=True), fromfile="v8/execution.py", tofile="v10/execution.py")
    (out/"EXECUTOR_DIFF.patch").write_text("".join(diff))


def execute(out):
    plan = json.loads((out/"PLAN.json").read_text())
    for path, expected in plan["source_sha256"].items():
        if sha(REPO/path) != expected:
            raise RuntimeError("Source changed after freeze: "+path)
    with (out/"runs.jsonl").open("x") as stream:
        for mode in ("logical", "real"):
            for index, world in enumerate(plan["logical_worlds"]):
                if mode == "real" and world["id"] not in plan["real_world_ids"]:
                    continue
                offset = index % len(ARMS)
                for arm in ARMS[offset:]+ARMS[:offset]:
                    row = run_world(world, arm, mode)
                    stream.write(json.dumps(row, allow_nan=False)+"\n")
                    stream.flush()
    slow_world = dict(plan["logical_worlds"][0])
    with (out/"stress.jsonl").open("x") as stream:
        for probe in plan["stress_probes"]:
            row = run_world(slow_world, "reserve_fixed_old_zero", "real",
                            head_delay=probe["head_delay"], sink_delay=probe["sink_delay"])
            stream.write(json.dumps({"probe": probe["name"], **row}, allow_nan=False)+"\n")
            stream.flush()
    write(out/"EXECUTION_COMPLETE.json", {"runs_sha256": sha(out/"runs.jsonl"),
        "stress_sha256": sha(out/"stress.jsonl"), "plan_sha256": sha(out/"PLAN.json")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute", "worker"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--delay", type=float)
    parser.add_argument("--symbol", type=int, choices=(0, 1))
    args = parser.parse_args()
    if args.command == "worker":
        if not 0 <= args.delay <= 5:
            raise ValueError("Bounded worker delay required")
        time.sleep(args.delay)
        work = sum(math.sin(i*.0001)**2 for i in range(10000))
        print(json.dumps({"symbol": args.symbol, "actual_feature_work": work}), flush=True)
    elif args.command == "prepare":
        prepare(args.output)
    else:
        execute(args.output)


if __name__ == "__main__":
    main()
