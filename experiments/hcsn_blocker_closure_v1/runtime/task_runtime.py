"""Execute a specified task's Bellman policy through the real native owner.

The posterior model and QVI are mathematical controls, not a trained HCSN
content encoder. Native STOP terminates one decision episode. A distinct owner
episode starts only after the simulated refractory delay and task reset.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
from scipy.linalg import solve

from experiments.hcsn_free_boundary_v1.native_bridge import MANIFEST, Signals, UPSTREAM
from ..oracle.finite_qvi import evaluate_policy, solve_policy
from ..oracle.task_model import build_posterior_task, conditional_generators
from .hardware import hardware_inventory


CONFIG = dict(nodes=17, evidence=1., rho=.2, cost=.04, fire_cost=.1,
              reset=.5, tau=.5, phases=2)
ARMS = ("task_qvi", "best_fixed_threshold", "fixed_confidence_0.8",
        "always_fire", "reset_omitted")
SEEDS = tuple(range(1031001, 1031033))
CYCLES = 4
MAX_TICKS = 512
REPOSITORY = Path(__file__).resolve().parents[3]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    paths = [Path(__file__), Path(__file__).with_name("measure.py"),
             Path(__file__).with_name("hardware.py")]
    paths += list(Path(__file__).parents[1].joinpath("oracle").glob("*.py"))
    paths += [REPOSITORY / "experiments/hcsn_free_boundary_v1" / name for name in
              ("native_bridge.py", "restore_native.py", "native_vendor/adapter.py", "native_vendor/MANIFEST.json")]
    return {str(path.relative_to(REPOSITORY)): sha(path) for path in sorted(paths)}


def protocol(preflight=False):
    return {
        "schema": "hcsn-task-bound-native-protocol.v1",
        "status": "written_before_episode_randomness_is_drawn",
        "config": CONFIG,
        "arms": ARMS,
        "seeds": [1030999] if preflight else SEEDS,
        "cycles": 2 if preflight else CYCLES,
        "preflight": preflight,
        "maximum_native_ticks_per_cycle": MAX_TICKS,
        "objective": {
            "name": "discounted-regenerative-posterior-classification",
            "firing_reward": "1{chosen_class == hidden_label} - fire_cost",
            "active_running_reward": "-cost integrated in continuous model time",
            "refractory": "Sum of phases independent Exp(phases/tau) waits; zero reward and no reads",
            "reset": "Observable grid index drawn with problem.reset; independent label Bernoulli(grid[index])",
            "discount": "exp(-rho * elapsed model time)",
            "infinite_horizon_estimator": "Four observed cycles plus exact policy continuation at the end of the final refractory period; observed-only rewards reported separately",
        },
        "native_message": "0.05 + 0.9*tanh(Q_keep - max(Q_fire)) for task QVI; fixed threshold controls use signed grid-boundary margin",
        "classification": "Native STOP chooses timing; Python chooses the declared Bayes class from the same posterior. Labels are revealed only for scoring after action.",
        "strong_threshold_control": "Exhaustive symmetric grid thresholds, selected by known-law exact policy value, ties choose the lower threshold. No heldout selection.",
        "reset_intervention": "New task data always reset independently. Only the controller posterior is retained at its previous firing state; this is a state-reset ablation, not a different label law.",
        "rng_coupling": "Same seed per arm; draws consumed according to actual actions. Paths are not asserted identical after actions diverge.",
        "native_authority": "DENY_ALL",
        "controller_training": False,
        "model_time_is_wall_time": False,
        "no_energy_proxy": True,
        "gates": ["binary_and_source_identity", "all_native_actions_match_declared_policy",
                  "post_STOP_and_refractory_read_rejection", "exact_retry_does_not_reexecute",
                  "reset_and_omitted_reset_first_cycle_match", "actual_later_state_and_actions_diverge",
                  "all_processes_exit_zero", "no_tick_limit_or_simulation_truncation"],
        "nonclaims": ["trained HCSN task-optimality", "architecture superiority", "GPU acceleration",
                      "direct joules", "foundation-model scale", "biological real-time simulation"],
        "sources": source_identity(),
    }


def policy_tables(problem):
    optimum = solve_policy(problem)
    candidates = []
    for threshold in problem.grid[problem.grid >= .5]:
        action = np.where(problem.grid >= .5, 2, 1)
        action = np.where(np.maximum(problem.grid, 1-problem.grid) < threshold, 0, action)
        value = evaluate_policy(problem, action)
        candidates.append((float(problem.reset@value), float(threshold), action, value))
    best = max(candidates, key=lambda row: (row[0], -row[1]))
    value_gap = optimum["values"][0]-optimum["values"][1:].max(0)
    result = {"task_qvi": dict(action=optimum["action"], value=optimum["value"], gap=value_gap),
              "reset_omitted": dict(action=optimum["action"], value=optimum["value"], gap=value_gap)}
    for arm, threshold in (("best_fixed_threshold", best[1]), ("fixed_confidence_0.8", .8),
                           ("always_fire", .5)):
        confidence = np.maximum(problem.grid, 1-problem.grid)
        action = np.where(problem.grid >= .5, 2, 1)
        action = np.where(confidence < threshold, 0, action)
        if np.any(action == 0):
            edge = .5*(confidence[action == 0].max()+confidence[action != 0].min())
            gap = edge-confidence
        else:
            edge, gap = None, -np.ones(len(action))
        result[arm] = dict(action=action, value=evaluate_policy(problem, action),
                           gap=gap, threshold=threshold, strict_grid_boundary=edge)
    stale_reward = .5-CONFIG["fire_cost"]
    stale_value = stale_reward/(1-problem.delay_discount)
    action = optimum["action"]
    matrix = problem.rho*np.eye(len(action))-problem.generator
    rhs = problem.running.copy()
    fired = np.flatnonzero(action)
    matrix[fired] = np.eye(len(action))[fired]
    rhs[fired] = problem.rewards[action[fired]-1, fired]+problem.delay_discount*stale_value
    result["reset_omitted"]["value"] = solve(matrix, rhs)
    result["reset_omitted"]["stale_tail_value"] = stale_value
    table = {arm: {key: value.tolist() if isinstance(value, np.ndarray) else value
                   for key, value in row.items()} for arm, row in result.items()}
    return result, table, [dict(threshold=row[1], reset_value=row[0]) for row in candidates]


def native_profile(model_digest, objective_digest, arm):
    kernel = dict(width=5, top_k=1, temporal_decay_q24=0, activity_decay_q24=0,
                  target_activity_q24=0, threshold_rate_q24=0, threshold_min_q24=0,
                  threshold_max_q24=0, eligibility_decay_q24=0)
    return UPSTREAM.make_profile(
        ["task_continuation_advantage"],
        [[1, 0, 0, 0], [-1, 0, 0, 0], [0, .1, 0, 0], [0, 0, .1, 0], [0, 0, 0, .1]],
        [-.05, .05, -4, -4, -4], [[1, -1, 0, 0, 0], [0]*5, [0]*5], [0, -8, 0],
        source_model_digest=model_digest, objective_digest=objective_digest,
        arm_id=arm, kernel=kernel, maximum_ticks=MAX_TICKS)


class TaskOwner:
    """An exact native process; each reset opens a distinct durable episode."""

    def __init__(self, root, binary, model_digest, objective_digest, arm, seed):
        self.root, self.arm, self.seed = Path(root), arm, seed
        self.bridge = UPSTREAM.NativeBridge(binary, root, expected_binary_sha256=MANIFEST["binary_sha256"])
        identity = self.bridge.identity
        if (identity["owner_authority"] != "DENY_ALL" or identity["source_commit"] != MANIFEST["native_base_commit"]
                or identity["source_manifest_digest"] != MANIFEST["source_manifest_sha256"]):
            self.bridge.close()
            raise ValueError("Native identity or authority mismatch")
        try:
            value = native_profile(model_digest, objective_digest, arm)
            path, self.profile_digest = UPSTREAM.save_profile(self.root / "profiles", value)
            self.bridge.load_profile(path, self.profile_digest)
        except Exception as error:
            cost = self.bridge.close()
            write_json(self.root / "INITIALIZATION_FAILURE.json",
                       dict(error_type=type(error).__name__, error=str(error), native_execution=cost))
            raise
        self.phase, self.decisions = "inactive", 0

    def open_cycle(self, cycle):
        case = f"task-{self.arm.replace('_', '-')}-{self.seed}-c{cycle}"
        receipt = self.bridge.open(case, self.seed, self.profile_digest)
        if receipt["status"]["step"] != 0 or receipt["status"]["terminal"]:
            raise AssertionError("A reset reused a terminal native episode")
        self.phase = "active"
        return receipt

    def decide(self, gap, context):
        if self.phase != "active":
            raise RuntimeError("No read outside the active task phase")
        message = .05+.9*math.tanh(float(gap))
        if abs(UPSTREAM.quantize(message)-UPSTREAM.quantize(.05)) < 16:
            raise ValueError("Task action is unresolved at native Q24 precision")
        packet = Signals(message, 0., 0., 0.).packet()
        before = dict(self.bridge.current)
        evidence = UPSTREAM.digest(context)
        event_id = f"{before['case']}.e{before['step']+1}"
        result = self.bridge.tick(packet, evidence_digest=evidence, event_id=event_id)
        if result["owner_authority"] != "DENY_ALL" or result["native_abstain"]:
            raise AssertionError("Native owner did not execute the declared shadow policy")
        self.decisions += 1
        self.last_request = dict(command="Tick", observation=dict(event_id=event_id,
            step=before["step"]+1, checkpoint=before["checkpoint"], features=packet, evidence_digest=evidence))
        if result["effective_action"] == "stop":
            self.phase = "terminal"
        return dict(message=message, message_q24=UPSTREAM.quantize(message), native=result)

    def close_cycle(self):
        before = self.bridge.rpc({"command": "Status"})
        count = self.bridge.counters["actual_kernel_calls"]
        duplicate = self.bridge.rpc(self.last_request)
        after = self.bridge.rpc({"command": "Status"})
        if before != after or count != self.bridge.counters["actual_kernel_calls"] or not duplicate["duplicate_event_ignored"]:
            raise AssertionError("Idempotent native retry failed")
        forbidden = dict(command="Tick", observation=dict(event_id=f"{self.bridge.current['case']}.forbidden",
            step=before["step"]+1, checkpoint=before["checkpoint"], features=Signals(.9, 0., 0., 0.).packet(),
            evidence_digest=UPSTREAM.digest("intentional-post-STOP-contract-probe")))
        refusal = self.bridge.rpc(forbidden, allow_error=True)
        if refusal.get("ok", True) or "Terminal episode" not in refusal["error"] or self.bridge.rpc({"command": "Status"}) != before:
            raise AssertionError("Native STOP permitted a new read")
        rejected = []
        for phase in ("terminal", "refractory"):
            self.phase = phase
            calls = self.decisions
            try:
                self.decide(1., {"contract_probe": phase})
            except RuntimeError as error:
                rejected.append(str(error) == "No read outside the active task phase" and self.decisions == calls)
            else:
                rejected.append(False)
        if not all(rejected):
            raise AssertionError("Python task phase allowed an observation after STOP")
        self.bridge.close_owner()
        return dict(retry_preserved_state=True, native_terminal_refusal=refusal,
                    task_phase_read_rejections=rejected)


def trial(problem, tables, arm, seed, cycles, binary, root, model_digest, objective_digest):
    started, cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(seed)
    conditional = conditional_generators(problem)
    transitions = np.eye(len(problem.grid))[None, :, :]+conditional/problem.rate
    if transitions.min() < -1e-12:
        raise ValueError("Conditional uniformization is invalid")
    transitions = np.maximum(transitions, 0)
    transitions /= transitions.sum(2, keepdims=True)
    owner = TaskOwner(root, binary, model_digest, objective_digest, arm, seed)
    elapsed, observed_return, retained_index = 0., 0., None
    rows, trace, correct, observations = [], [], 0, 0
    try:
        for cycle in range(cycles):
            physical = int(rng.choice(len(problem.grid), p=problem.reset))
            label = int(rng.random() < problem.grid[physical])
            belief = retained_index if arm == "reset_omitted" and retained_index is not None else physical
            initial_belief, initial_physical = belief, physical
            opened = owner.open_cycle(cycle)
            episode_start, reads = elapsed, 0
            for step in range(MAX_TICKS):
                expected = int(tables[arm]["action"][belief])
                context = dict(cycle=cycle, controller_state=belief, model_time=elapsed)
                result = owner.decide(tables[arm]["gap"][belief], context)
                actual = result["native"]["effective_action"]
                if actual != ("keep" if expected == 0 else "stop"):
                    raise AssertionError("Actual native action differs from the task policy")
                trace.append(dict(cycle=cycle, step=step, controller_state=belief,
                                  model_time=elapsed, expected_action=expected, **result))
                if expected:
                    chosen = expected-1
                    reward = float(chosen == label)-CONFIG["fire_cost"]
                    observed_return += math.exp(-problem.rho*elapsed)*reward
                    correct += int(chosen == label)
                    retained_index = belief
                    break
                hold = float(rng.exponential(1/problem.rate))
                next_index = int(rng.choice(len(problem.grid), p=transitions[label, physical]))
                old_discount = math.exp(-problem.rho*elapsed)
                elapsed += hold
                observed_return += -CONFIG["cost"]*(old_discount-math.exp(-problem.rho*elapsed))/problem.rho
                physical, belief = next_index, next_index
                reads += 1
                observations += 1
            else:
                raise AssertionError("Native observation limit reached; no truncated result is accepted")
            guards = owner.close_cycle()
            refractory = rng.exponential(problem.tau/problem.phases, size=problem.phases)
            elapsed += float(refractory.sum())
            rows.append(dict(cycle=cycle, initial_controller_state=int(initial_belief),
                initial_physical_state=initial_physical, final_controller_state=int(belief),
                hidden_label_scoring_only=label, chosen_class=chosen, realized_reward=reward,
                observations=reads, active_model_time=elapsed-float(refractory.sum())-episode_start,
                refractory_phase_durations=refractory.tolist(), open_receipt=opened, guards=guards))
        tail_index = int(rng.choice(len(problem.grid), p=problem.reset))
        tail = tables[arm]["stale_tail_value"] if arm == "reset_omitted" else float(tables[arm]["value"][tail_index])
        returned = observed_return+math.exp(-problem.rho*elapsed)*tail
    finally:
        native_cost = owner.bridge.close()
    if native_cost["exit_code"] != 0:
        raise AssertionError("Actual native child failed")
    raw = {"cycles": rows, "decisions": trace, "native_cost": native_cost}
    trace_path = Path(root) / "TRACE.json.gz"
    with gzip.open(trace_path, "wt", encoding="utf-8") as stream:
        json.dump(raw, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return dict(arm=arm, seed=seed, cycles=cycles, correct=correct, observations=observations,
        actual_native_ticks=owner.decisions, model_time=elapsed, observed_discounted_return=observed_return,
        model_based_tail=math.exp(-problem.rho*elapsed)*tail, infinite_horizon_estimate=returned,
        expected_policy_value=float(problem.reset@tables[arm]["value"]),
        trace_file=str(trace_path.relative_to(Path(root).parents[1])), trace_sha256=sha(trace_path),
        task_phase_guards_passed=True, action_agreement=True, native_process_exit_code=native_cost["exit_code"],
        native_execution=native_cost, python_self_cpu_seconds=time.process_time()-cpu,
        whole_trial_cpu_seconds=time.process_time()-cpu+native_cost["child_cpu_seconds"],
        whole_trial_wall_seconds=time.perf_counter()-started,
        persistent_disk_bytes=sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file()),
        first_cycle_controller_trace=[row["controller_state"] for row in trace if row["cycle"] == 0],
        reset_states=[dict(controller=row["initial_controller_state"], physical=row["initial_physical_state"]) for row in rows])


def run(output, binary, preflight=False):
    preparation_cpu = time.process_time()
    declared = protocol(preflight)
    write_json(output / "PROTOCOL.json", declared)
    write_json(output / "HARDWARE.json", hardware_inventory())
    problem, _ = build_posterior_task(**CONFIG)
    tables, serialized, candidates = policy_tables(problem)
    write_json(output / "POLICY_TABLES.json", dict(policies=serialized, candidates=candidates,
        grid=problem.grid.tolist(), reset=problem.reset.tolist(), rho=problem.rho,
        generator=problem.generator.tolist(), running=problem.running.tolist(),
        rewards=problem.rewards.tolist(), delay_discount=problem.delay_discount))
    model_digest, objective_digest = sha(output / "POLICY_TABLES.json"), UPSTREAM.digest(declared["objective"])
    preparation = time.process_time()-preparation_cpu
    records = []
    for seed in declared["seeds"]:
        for arm in declared["arms"]:
            root = output / "native" / f"{arm}-{seed}"
            record = trial(problem, tables, arm, seed, declared["cycles"], binary, root, model_digest, objective_digest)
            records.append(record)
            write_json(output / "PARTIAL_RECORDS.json", records)
    reset_checks = []
    for seed in declared["seeds"]:
        rows = {row["arm"]: row for row in records if row["seed"] == seed}
        same = rows["task_qvi"]["first_cycle_controller_trace"] == rows["reset_omitted"]["first_cycle_controller_trace"]
        regular = all(row["controller"] == row["physical"] for row in rows["task_qvi"]["reset_states"])
        stale = all(row["controller"] != row["physical"] for row in rows["reset_omitted"]["reset_states"][1:])
        changed = rows["task_qvi"]["observations"] > rows["reset_omitted"]["observations"]
        reset_checks.append(dict(seed=seed, first_cycle_identical=same, normal_reset_fresh=regular,
                                 stale_state_retained=stale, subsequent_reads_changed=changed))
    summary = {}
    for arm in ARMS:
        group = [row for row in records if row["arm"] == arm]
        estimates = np.array([row["infinite_horizon_estimate"] for row in group])
        summary[arm] = dict(exact_policy_value=float(problem.reset@tables[arm]["value"]),
            empirical_mean=float(estimates.mean()), empirical_sample_sd=float(estimates.std(ddof=1)) if len(group)>1 else None,
            observed_only_mean=float(np.mean([row["observed_discounted_return"] for row in group])),
            accuracy=sum(row["correct"] for row in group)/sum(row["cycles"] for row in group),
            total_observations=sum(row["observations"] for row in group),
            actual_native_ticks=sum(row["actual_native_ticks"] for row in group),
            whole_trial_cpu_seconds=sum(row["whole_trial_cpu_seconds"] for row in group),
            whole_trial_wall_seconds=sum(row["whole_trial_wall_seconds"] for row in group))
    changed_sources = [path for path, identity in declared["sources"].items() if sha(REPOSITORY/path) != identity]
    checks = dict(native_action_and_phase_guards=all(row["action_agreement"] and row["task_phase_guards_passed"] for row in records),
                  all_children_exit_zero=all(row["native_process_exit_code"] == 0 for row in records),
                  actual_reset_intervention=all(all(value for key, value in row.items() if key != "seed") for row in reset_checks),
                  source_identity_unchanged=not changed_sources)
    result = dict(schema="hcsn-task-bound-native-result.v1", preflight=preflight, complete=len(records)==len(declared["seeds"])*len(ARMS),
        checks=checks, all_execution_gates_pass=all(checks.values()), records=records, summary=summary,
        reset_checks=reset_checks, preparation_self_cpu_seconds=preparation,
        self_cpu_seconds_at_result=time.process_time(),
        native_children_cpu_seconds=sum(row["native_execution"]["child_cpu_seconds"] for row in records),
        peak_python_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        changed_sources=changed_sources, protocol_sha256=sha(output/"PROTOCOL.json"),
        policy_tables_sha256=model_digest, objective_digest=objective_digest,
        runtime_binary_sha256=sha(binary), trained_network=False, analytic_task_control_only=True,
        joules_measured=None, gpu_executed=False, finite_grid_nodes=CONFIG["nodes"],
        terminal_tail_is_model_based=True,
        conclusion="Actual native execution of the specified regenerative task policy, including repeated resets and a causal reset omission. No trained-content or architecture-superiority claim.")
    write_json(output / "RESULT.json", result)
    print(json.dumps(dict(complete=result["complete"], checks=checks, summary=summary), sort_keys=True), flush=True)
    if not result["complete"] or not all(checks.values()):
        raise AssertionError("Task runtime acceptance failed; partial evidence retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    run(args.output, args.binary, args.preflight)


if __name__ == "__main__":
    main()
