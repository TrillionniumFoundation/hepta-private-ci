"""Separate service deadline risk from content forecasts in a controlled task.

The public task has independent binary-symmetric synthetic sensors and an
independent fast/slow feature worker. This is development support, not real AV,
and does not test necessity of an analytic or financial Put mechanism.
"""

import argparse
from dataclasses import asdict
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
    LogicalClock, RealClock, ReadResult, run_episode,
)
from experiments.hcsn_v8_execution_20261101.scheduler.planning import (
    Plan, Read, ServiceEstimate, choose_plan,
)

MODULE = "experiments.hcsn_v9_followup_20261101.risk.study"
HEAD_ID = "synthetic-independent-bsc-head-v1"
COSTS = CostWeights(observation=.02, elapsed_second=.005, deadline_miss=1.)
DEADLINE = 2.2
VIDEO_PLAN = Plan((Read(Modality.VIDEO, 1),))


def write(path, data):
    with Path(path).open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def posterior(content):
    likelihood = [1., 1.]
    for modality, accuracy in ((Modality.AUDIO, .7), (Modality.VIDEO, .95)):
        observation = content.observation(modality)
        if observation is not None:
            symbol = int(observation.raw[0])
            for target in (0, 1):
                likelihood[target] *= accuracy if symbol == target else 1 - accuracy
    total = sum(likelihood)
    return tuple(x / total for x in likelihood)


class Head:
    def evaluate(self, content):
        probabilities = posterior(content)
        return StopEvaluation(probabilities, CorrectnessValue(max(probabilities), HEAD_ID))


class Forecast:
    kind = BackendKind.DIRECT_HISTORY
    reader_id = "public-exact-synthetic-sensor-forecast-v1"

    def evaluate(self, content, state, plan):
        p = posterior(content)
        current = max(p)
        # Future correctness includes the identical .5 timeout fallback in both
        # arms. The independent risk penalty must not alter this content target.
        if plan == VIDEO_PLAN and content.video is None:
            success = sum(max(p[0] * (.95 if symbol == 0 else .05),
                              p[1] * (.95 if symbol == 1 else .05)) for symbol in (0, 1))
            current = .5 * success + .5 * current
        return CorrectnessValue(current, HEAD_ID)


class ServiceModel:
    def __init__(self, intervention="full"):
        if intervention not in ("full", "zero"):
            raise ValueError("Unknown risk intervention")
        self.intervention = intervention

    def estimate(self, content, plan, now, deadline):
        if plan == VIDEO_PLAN:
            # Both policies receive this public distribution; only its explicit
            # penalty input is intervened on. They cannot inspect sampled delay.
            duration = .5 * .12 + .5 * max(0., deadline - now)
            probability = .5
        else:
            duration, probability = max(0., deadline - now), 1.
        return ServiceEstimate(duration, probability if self.intervention == "full" else 0.,
                               plan.requested_reads)


def observation(step, clock, object_id, symbol):
    return PrefixObservation(step.identity, object_id, step.modality, step.prefix_end,
                             step.prefix_end, clock.now(), (float(symbol),), (float(symbol),),
                             "synthetic-independent-bsc-v1", (0., step.prefix_end))


class Service:
    mode = "controlled synthetic BSC payloads; independent public fast/slow worker law"

    def __init__(self, world, logical):
        self.world, self.logical = world, logical
        self.drained_payloads = 0

    def request(self, step, clock):
        symbol = self.world[step.modality.value]
        delay = .03 if step.modality == Modality.AUDIO else (.12 if self.world["fast"] else 1.4)
        target = max(float(step.prefix_end), clock.now()) + delay
        child = None
        if not self.logical:
            child = subprocess.Popen([sys.executable, "-m", MODULE, "worker", "--delay",
                str(max(0., target - clock.now())), "--symbol", str(symbol)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        owner = self

        class Pending:
            def wait_until(self, deadline, clock):
                if owner.logical:
                    clock.wait_until(min(target, deadline))
                    if target > deadline:
                        return None
                    return ReadResult(observation=observation(step, clock, owner.world["id"], symbol))
                try:
                    stdout, stderr = child.communicate(timeout=max(0., deadline - clock.now()))
                except subprocess.TimeoutExpired:
                    return None
                if child.returncode:
                    return ReadResult(error=f"worker exit {child.returncode}: {stderr[:128]}")
                received = json.loads(stdout)
                return ReadResult(observation=observation(step, clock, owner.world["id"], received["symbol"]))

            def drain(self, clock):
                if owner.logical:
                    clock.wait_until(target)
                else:
                    child.communicate(timeout=5)
                owner.drained_payloads += 1

        return Pending()


def initial_content(world):
    content = VisibleContent(world["id"], CacheBudget(1024, max_prefix_end=1, max_events=2))
    clock = LogicalClock()
    clock.wait_until(1.03)
    packet = observation(Read(Modality.AUDIO, 1), clock, world["id"], world["audio"])
    return content.accept(packet, clock.now())


def planned(world, intervention):
    content = initial_content(world)
    selected, receipt = choose_plan(content, None, Head(), Forecast(), ServiceModel(intervention),
                                    (VIDEO_PLAN,), 1.03, DEADLINE, COSTS)
    return selected, receipt


def run_world(world, arm, clock_mode):
    logical = clock_mode == "logical"
    intervention = "zero" if arm.startswith("zero") else "full"
    schedule = None
    if "_on_" in arm:
        source = arm.split("_on_")[1]
        selected, _ = planned(world, source)
        schedule = () if selected is None else (selected,)
    service = Service(world, logical)
    flushed = []
    clock = LogicalClock() if logical else RealClock()
    sink_file = None if logical else tempfile.TemporaryFile()

    def sink(data):
        flushed.append(data)
        if logical:
            clock.wait_until(clock.now() + .000001)
        else:
            sink_file.write(data)
            sink_file.flush()
            os.fsync(sink_file.fileno())

    started_wall, started_cpu = time.perf_counter(), time.process_time()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = run_episode(world["id"], CacheBudget(1024, max_prefix_end=1, max_events=2),
        Head(), Forecast(), ServiceModel(intervention), service, sink, clock=clock,
        deadline=DEADLINE, horizon=1, max_requests=2, max_decisions=1, costs=COSTS,
        fixed_plans=schedule)
    if sink_file is not None:
        sink_file.seek(0)
        if sink_file.read() != flushed[0]:
            raise RuntimeError("Actual flushed output differs from captured bytes")
        sink_file.close()
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    expected, _ = planned(world, intervention)
    correct = int(receipt["output"]["predicted_class"] == world["target"])
    timeout_penalty = receipt["deadline_penalty"]
    utility = correct - receipt["observation_fee"] - receipt["latency_fee"] - timeout_penalty
    return {"world_id": world["id"], "arm": arm, "clock_mode": clock_mode,
        "intervention": intervention, "expected_selected": None if expected is None else expected.identity,
        "receipt": receipt, "correct": correct, "scored_deadline_penalty": timeout_penalty,
        "net_utility": utility, "drained_payloads": service.drained_payloads,
        "flushed_output": json.loads(flushed[0]), "payloads_invariant_across_arms": True,
        "wall_seconds_including_drain": time.perf_counter() - started_wall,
        "own_cpu_seconds": time.process_time() - started_cpu,
        "waited_children_cpu_seconds": children_after.ru_utime + children_after.ru_stime
            - children_before.ru_utime - children_before.ru_stime}


def make_worlds():
    # Exact finite quadrature of independent BSC noise (audio .7, video .95),
    # balanced target and independent fast/slow service. Weight is explicit.
    worlds = []
    for target, audio_correct, video_correct, fast in itertools.product((0, 1), repeat=4):
        weight = .5 * (.7 if audio_correct else .3) * (.95 if video_correct else .05) * .5
        worlds.append({"id": f"synthetic-bsc-{len(worlds):02}", "target": target,
            "audio": target if audio_correct else 1-target,
            "video": target if video_correct else 1-target, "fast": bool(fast), "weight": weight})
    return worlds


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    sources = [Path(__file__), root / "hcsn_v8_execution_20261101/scheduler/planning.py",
               root / "hcsn_v8_execution_20261101/scheduler/execution.py",
               root / "hcsn_v7_support_20261101/content_interface/content_interface.py"]
    write(out / "PLAN.json", {"schema": "hcsn-v9-service-risk-development.v1",
        "source_sha256": {str(p.relative_to(root)): digest(p) for p in sources},
        "scope": "controlled_synthetic_service_risk_not_real_AV", "architecture_acceptance": False,
        "arms": ["full", "zero", "full_on_zero", "zero_on_full"],
        "intervention": "only explicit deadline_miss_probability; identical future correctness incl timeout, elapsed and read count",
        "public_law": {"audio_accuracy": .7, "video_accuracy": .95,
                       "video_fast_probability": .5, "fast_delay": .12, "slow_delay": 1.4},
        "deadline": DEADLINE, "costs": asdict(COSTS),
        "logical_worlds": make_worlds(), "real_world_ids": [f"synthetic-bsc-{i:02}" for i in (0, 3, 5, 6, 9, 10, 12, 15)],
        "real_world_selection": "before execution; even-parity half-fraction balances target/audio correctness/video correctness/service, descriptive unweighted subset",
        "real_arm_order": "Latin rotation of full,zero,full_on_zero,zero_on_full by world index modulo four",
        "logical_quadrature": "full joint factor enumeration; weighted by public independent sensor/noise/service law",
        "primary": "weighted logical and descriptive paired actual full-minus-zero net utility; fixed-action content invariance",
        "logical_timeout_scoring": "sink adds declared one microsecond flush; actual run uses measured flush",
        "limitations": ["fixed public sensor law", "untrained common head", "8 actual worlds only", "one optional read",
                        "not natural AV", "not Put-channel or analytic-core necessity", "no energy measurement"]})


def execute(out):
    plan = json.loads((out / "PLAN.json").read_text())
    root = Path(__file__).resolve().parents[2]
    for path, expected in plan["source_sha256"].items():
        if digest(root / path) != expected:
            raise RuntimeError("Source changed after freeze: " + path)
    began_wall, began_cpu = time.perf_counter(), time.process_time()
    rows = []
    with (out / "runs.jsonl").open("x") as stream:
        for mode in ("logical", "real"):
            for world_index, world in enumerate(plan["logical_worlds"]):
                if mode == "real" and world["id"] not in plan["real_world_ids"]:
                    continue
                offset = world_index % len(plan["arms"])
                arms = plan["arms"][offset:] + plan["arms"][:offset]
                for arm in arms:
                    row = run_world(world, arm, mode)
                    rows.append(row)
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    stream.flush()
    summary = {"scope": plan["scope"], "architecture_acceptance": False, "modes": {}}
    for mode in ("logical", "real"):
        selected = [r for r in rows if r["clock_mode"] == mode]
        by_key = {(r["world_id"], r["arm"]): r for r in selected}
        worlds = [w for w in plan["logical_worlds"] if (w["id"], "full") in by_key]
        weights = {w["id"]: w["weight"] if mode == "logical" else 1 / len(worlds) for w in worlds}
        means = {arm: sum(weights[w["id"]] * by_key[w["id"], arm]["net_utility"] for w in worlds) for arm in plan["arms"]}
        pairs = []
        for w in worlds:
            a, b = by_key[w["id"], "full"], by_key[w["id"], "zero"]
            fixed_zero, fixed_full = by_key[w["id"], "full_on_zero"], by_key[w["id"], "zero_on_full"]
            pairs.append({"world_id": w["id"], "full_minus_zero": a["net_utility"]-b["net_utility"],
                "requests_changed": a["receipt"]["requested_observations"] != b["receipt"]["requested_observations"],
                "fixed_zero_probabilities_equal": fixed_zero["receipt"]["output"]["probabilities"] == b["receipt"]["output"]["probabilities"],
                "fixed_full_probabilities_equal": fixed_full["receipt"]["output"]["probabilities"] == a["receipt"]["output"]["probabilities"]})
        summary["modes"][mode] = {"worlds": len(worlds), "runs": len(selected), "mean_net_utility": means,
            "full_minus_zero": means["full"]-means["zero"], "paired": pairs,
            "all_fixed_content_equal": all(p["fixed_zero_probabilities_equal"] and p["fixed_full_probabilities_equal"] for p in pairs),
            "timed_out_runs": sum(any(e["status"] == "timed_out" for e in r["receipt"]["events"]) for r in selected),
            "late_video_never_accepted": all("READ:video:1" not in r["receipt"]["output"]["accepted_event_ids"]
                for r in selected if any(e["status"] == "timed_out" for e in r["receipt"]["events"])),
            "own_cpu_seconds": sum(r["own_cpu_seconds"] for r in selected),
            "waited_children_cpu_seconds": sum(r["waited_children_cpu_seconds"] for r in selected)}
    summary.update(wall_seconds=time.perf_counter()-began_wall, own_cpu_seconds=time.process_time()-began_cpu,
                   plan_sha256=digest(out / "PLAN.json"), raw_sha256=digest(out / "runs.jsonl"))
    write(out / "SUMMARY.json", summary)
    print(json.dumps({mode: summary["modes"][mode]["full_minus_zero"] for mode in summary["modes"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute", "worker"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--delay", type=float)
    parser.add_argument("--symbol", type=int, choices=(0, 1))
    args = parser.parse_args()
    if args.command == "worker":
        if not 0 <= args.delay <= 5:
            raise ValueError("Worker delay out of bounds")
        time.sleep(args.delay)
        value = sum(math.sin(i * .0001)**2 for i in range(10000))
        print(json.dumps({"symbol": args.symbol, "actual_cpu_feature_work": value}), flush=True)
    elif args.command == "prepare":
        prepare(args.output)
    else:
        execute(args.output)


if __name__ == "__main__":
    main()
