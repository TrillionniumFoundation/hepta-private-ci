"""Post-hoc diagnosis on all existing fit23 OOD worlds; no editing or selection."""
import argparse
import copy
import gc
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_io import canonical, identity, read, save, sha, verify_manifest
from vendor import planning as p


TERMINALS = (0, 4, 5)
ACTION_NAMES = ("STOP", "WAIT", "READ", "REPAIR", "SUBMIT_0", "SUBMIT_1")


class Actor:
    def __init__(self, ctx, world, theta):
        self.ctx, self.world, self.theta, self.cache = ctx, world, theta, {}

    def at(self, state):
        key = canonical(state)
        if key not in self.cache:
            hidden, _bank = self.world.feature(state)
            scores, belief = self.ctx.predicted(self.theta, hidden)
            mask = self.ctx.legal(self.world.public, state)
            action = int(np.where(mask, scores, -np.inf).argmax())
            self.cache[key] = (action, scores, belief, hidden)
        return self.cache[key]


class PolicyValue:
    def __init__(self, ctx, public, actor, oracle, terminal_mode):
        self.ctx, self.public, self.actor = ctx, public, actor
        self.oracle, self.terminal_mode, self.values, self.qs = oracle, terminal_mode, {}, {}

    def value(self, state):
        key = canonical(state)
        if key not in self.values:
            self.values[key] = self.q(state, self.actor.at(state)[0])
        return self.values[key]

    def q(self, state, action):
        key = (canonical(state), action)
        if key not in self.qs:
            if not self.ctx.legal(self.public, state)[action]:
                raise ValueError("illegal counterfactual action")
            if action == 0:
                result = 0.
            elif action in (4, 5):
                probability = self.oracle.posterior(state)
                if self.terminal_mode == "training":
                    result = 1 - 2 * probability if action == 4 else 2 * probability - 1
                else:
                    correct = 1 - probability if action == 4 else probability
                    result = 2 * correct - 1
            else:
                result = 0.
                for probability, outcome in self.ctx.outcomes(self.public, state, action, self.oracle):
                    if probability:
                        after = self.ctx.successor(self.public, state, action, outcome)
                        result += probability * (self.value(after) - (after["charges"] - state["charges"]))
            self.qs[key] = float(result)
        return self.qs[key]


def diagnose_world(ctx, public, model, C, E, expected, tolerance, sign_tolerance):
    start = time.process_time()
    world = p.WorldPolicy(ctx, public, model, None)
    actor_C, actor_E = Actor(ctx, world, C), Actor(ctx, world, E)
    own = ctx.Oracle(public, p.OwnTableLaw(model, ctx), model.confusion)
    truth = ctx.Oracle(public, ctx.law, model.confusion)
    values = {(law, arm): PolicyValue(ctx, public, actor_C if arm == "C" else actor_E,
                                      own if law == "own" else truth,
                                      "training" if law == "own" else "evaluation")
              for law in ("own", "truth") for arm in ("C", "E")}
    initial = ctx.initial(public)
    initial_values = {law: {arm: values[law, arm].value(initial) for arm in ("C", "E")}
                      for law in ("own", "truth")}
    expected_error = max(abs(initial_values["truth"][arm] - expected["arms"][arm]["utility"]) for arm in ("C", "E"))
    if expected_error > tolerance:
        raise ArithmeticError("post-hoc evaluator differs from frozen scientific record")
    traces = {}
    def trace(state):
        key = canonical(state)
        if key in traces:
            return traces[key]
        a_C, q_C_head, belief_C, hidden = actor_C.at(state)
        a_E, q_E_head, belief_E, _hidden = actor_E.at(state)
        if a_C == a_E or belief_C != belief_E:
            raise ArithmeticError("only actual changed-action states with frozen Belief are traced")
        legal = ctx.legal(public, state)
        own_Q = [values["own", "C"].q(state, a) if legal[a] else 0. for a in range(6)]
        truth_Q = [values["truth", "C"].q(state, a) if legal[a] else 0. for a in range(6)]
        terminal = max(TERMINALS, key=lambda a: q_C_head[a])
        offset = float(q_C_head[terminal]) - own_Q[terminal]
        target = q_C_head.copy()
        for action in (1, 2, 3):
            target[action] = offset + own_Q[action]
        teacher = max((a for a, good in enumerate(legal) if good), key=lambda a: target[a])
        own_advantage = own_Q[a_E] - values["own", "C"].value(state)
        truth_advantage = truth_Q[a_E] - values["truth", "C"].value(state)
        # These are fixed-hidden linear contributions, not separate causal experiments.
        def row_change(action):
            return E[action - 1] - C[action - 1] if action in (1, 2, 3) else np.zeros(49)
        coordinates = row_change(a_E) - row_change(a_C)
        contributions = coordinates * hidden
        actual_margin_shift = float((q_E_head[a_E] - q_E_head[a_C]) - (q_C_head[a_E] - q_C_head[a_C]))
        residual = abs(float(contributions.sum()) - actual_margin_shift)
        target_residual = abs(float(target[a_E] - target[a_C]) - own_advantage)
        if residual > tolerance or target_residual > tolerance:
            raise ArithmeticError("head linear or anchor/advantage identity failed")
        important = sorted(range(49), key=lambda i: (-abs(contributions[i]), i))[:5]
        record = dict(state=state, state_sha256=sha(key.encode()),
            C_action=a_C, E_action=a_E, C_action_name=ACTION_NAMES[a_C], E_action_name=ACTION_NAMES[a_E],
            legal=legal, C_head_scores=q_C_head, E_head_scores=q_E_head,
            frozen_belief=belief_C, own_terminal_posterior=own.posterior(state), evaluator_terminal_posterior=truth.posterior(state),
            own_Q_following_C=own_Q, evaluator_Q_following_C=truth_Q,
            anchored_own_target=target, anchored_teacher_action=teacher,
            own_one_step_C_advantage_of_E_action=own_advantage,
            evaluator_one_step_C_advantage_of_E_action=truth_advantage,
            own_full_suffix_E_minus_C=values["own", "E"].value(state) - values["own", "C"].value(state),
            evaluator_full_suffix_E_minus_C=values["truth", "E"].value(state) - values["truth", "C"].value(state),
            violates_own_incumbent_policy_improvement=own_advantage < -sign_tolerance,
            own_positive_preference_reversed_by_evaluator=own_advantage > sign_tolerance and truth_advantage < -sign_tolerance,
            E_disagrees_with_anchored_teacher=teacher != a_E,
            hidden_with_bias=hidden, linear_head_margin_contributions=contributions,
            actual_head_margin_shift=actual_margin_shift,
            linear_identity_residual=residual, target_advantage_identity_residual=target_residual,
            top_absolute_linear_coordinates=[dict(index=i, kind="bias" if i == 48 else "learned_hidden_coordinate",
                hidden_value=float(hidden[i]), changed_margin_coefficient=float(coordinates[i]),
                contribution=float(contributions[i])) for i in important],
            own_E_unnormalized_reach=0., evaluator_E_unnormalized_reach=0.,
            first_common_prefix_evaluator_reach=0.)
        traces[key] = record
        return record
    performance = {}
    for law, oracle in (("own", own), ("truth", truth)):
        total, visits, terminal_mass = 0., 0, 0.
        def visit(state, reach):
            nonlocal total, visits, terminal_mass
            visits += 1
            a_E = actor_E.at(state)[0]
            a_C = actor_C.at(state)[0]
            advantage = values[law, "C"].q(state, a_E) - values[law, "C"].value(state)
            total += reach * advantage
            if a_E != a_C:
                record = trace(state)
                key = "own_E_unnormalized_reach" if law == "own" else "evaluator_E_unnormalized_reach"
                record[key] += reach
            elif advantage != 0.:
                raise ArithmeticError("same incumbent action has nonzero incumbent advantage")
            if a_E in TERMINALS:
                terminal_mass += reach
                return
            for probability, outcome in ctx.outcomes(public, state, a_E, oracle):
                if probability:
                    visit(ctx.successor(public, state, a_E, outcome), reach * probability)
        visit(initial, 1.)
        difference = initial_values[law]["E"] - initial_values[law]["C"]
        residual = abs(total - difference)
        if residual > tolerance or abs(terminal_mass - 1) > 2e-11:
            raise ArithmeticError("unnormalized E-occupancy performance-difference identity failed")
        performance[law] = dict(initial_E_minus_C=difference, sum_E_reach_times_C_advantage=total,
                                residual=residual, visited_tree_nodes=visits, terminal_mass=terminal_mass)
    first_total, first_events = 0., 0
    def common_prefix(state, reach):
        nonlocal first_total, first_events
        a_C, a_E = actor_C.at(state)[0], actor_E.at(state)[0]
        if a_C != a_E:
            record = trace(state)
            record["first_common_prefix_evaluator_reach"] += reach
            first_total += reach * record["evaluator_full_suffix_E_minus_C"]
            first_events += 1
            return
        if a_C not in TERMINALS:
            for probability, outcome in ctx.outcomes(public, state, a_C, truth):
                if probability:
                    common_prefix(ctx.successor(public, state, a_C, outcome), reach * probability)
    common_prefix(initial, 1.)
    first_residual = abs(first_total - performance["truth"]["initial_E_minus_C"])
    if first_residual > tolerance:
        raise ArithmeticError("first-divergence full-suffix partition failed")
    records = list(traces.values())
    # Exclusive categories only for summing the evaluator-law global difference.
    categories = {name: dict(state_count=0, evaluator_E_expected_visit_count=0., evaluator_advantage_contribution=0.)
                  for name in ("own_target_violation", "own_positive_evaluator_negative", "other")}
    for row in records:
        name = ("own_target_violation" if row["violates_own_incumbent_policy_improvement"] else
                "own_positive_evaluator_negative" if row["own_positive_preference_reversed_by_evaluator"] else "other")
        row["exclusive_diagnostic_category"] = name
        weight = row["evaluator_E_unnormalized_reach"]
        categories[name]["state_count"] += 1
        categories[name]["evaluator_E_expected_visit_count"] += weight
        categories[name]["evaluator_advantage_contribution"] += weight * row["evaluator_one_step_C_advantage_of_E_action"]
    if abs(sum(row["evaluator_advantage_contribution"] for row in categories.values()) - performance["truth"]["initial_E_minus_C"]) > tolerance:
        raise ArithmeticError("exclusive category sum lost performance-difference mass")
    return dict(world_id=public["id"], public_sha256=sha(canonical(public).encode()),
        initial_values=initial_values, frozen_record_utility_max_error=expected_error,
        performance_difference=performance,
        first_divergence_partition=dict(events=first_events, full_suffix_weighted_sum=first_total, residual=first_residual),
        changed_state_records=records, exclusive_categories=categories,
        cpu_seconds=time.process_time() - start,
        scope="Post-hoc fixed-world policy comparison; local one-step counterfactual, full-suffix partition and unnormalized E-occupancy global identity are distinct.")


def main(args):
    start, wall = time.process_time(), time.perf_counter()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol = read(args.protocol)
    def timeout(*_args):
        raise TimeoutError("post-hoc diagnostic fixed resource cap reached")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(120)
    resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    try:
        verify_manifest(ROOT, protocol["source_files"])
        verify_manifest(ROOT, protocol["input_files"])
        main_protocol = read(ROOT / "PROTOCOL_FROZEN.json")
        verify_manifest(ROOT, main_protocol["source_files"])
        verify_manifest(ROOT, read(ROOT / "INPUT_MANIFEST.json")["files"])
        ctx = p.load_context(ROOT / "vendor/frozen_joint")
        scientific = ROOT / "execution_r1/run"
        C_model, E_model = [read(scientific / f"models/fit_23_{arm}.json.gz") for arm in ("C", "E")]
        C, E = ctx.head(C_model), ctx.head(E_model)
        recovered = copy.deepcopy(E_model)
        recovered["network"]["w2"][:3] = C_model["network"]["w2"][:3]
        recovered["network"]["b2"][:3] = C_model["network"]["b2"][:3]
        if recovered != C_model or not np.array_equal(C[3], E[3]):
            raise ValueError("diagnostic input is not the protected pure continuation edit")
        policy = ctx.NumpyPolicy(C_model)
        summaries, inventory, all_rows = {}, [], {}
        for split, count in (("validation", 16), ("test", 32)):
            worlds = read(scientific / f"worlds/{split}_23_ood.json.gz")["worlds"]
            scores = read(scientific / f"{split}_23_ood_RESULTS.json.gz")["records"]
            if len(worlds) != count or len(scores) != count:
                raise ValueError("all fixed48 OOD worlds required")
            rows = []
            for index, (public, expected) in enumerate(zip(worlds, scores)):
                if public["id"] != expected["world_id"]:
                    raise ValueError("world/result identity mismatch")
                row = diagnose_world(ctx, public, policy, C, E, expected,
                                     protocol["identity_tolerance"], protocol["sign_tolerance"])
                path = out / f"{split}_{index:03d}.json.gz"
                digest = save(path, row)
                inventory.append(dict(path=path.name, sha256=digest, world_id=public["id"], split=split, index=index))
                rows.append(row)
                gc.collect()
            summaries[split] = dict(world_count=count,
                mean_own_E_minus_C=float(np.mean([r["performance_difference"]["own"]["initial_E_minus_C"] for r in rows])),
                mean_evaluator_E_minus_C=float(np.mean([r["performance_difference"]["truth"]["initial_E_minus_C"] for r in rows])),
                changed_state_records=sum(len(r["changed_state_records"]) for r in rows),
                categories={category: {key: float(np.mean([r["exclusive_categories"][category][key] for r in rows]))
                    for key in ("state_count", "evaluator_E_expected_visit_count", "evaluator_advantage_contribution")}
                    for category in ("own_target_violation", "own_positive_evaluator_negative", "other")})
            all_rows[split] = rows
        if len(inventory) != 48:
            raise ArithmeticError("incomplete diagnostic population")
        # The illustration rule was fixed before executing this post-hoc diagnostic.
        worst = min(range(32), key=lambda i: all_rows["test"][i]["performance_difference"]["truth"]["initial_E_minus_C"])
        example = all_rows["test"][worst]
        checks = dict(max_frozen_record_utility_error=max(r["frozen_record_utility_max_error"] for rs in all_rows.values() for r in rs),
            max_own_performance_difference_residual=max(r["performance_difference"]["own"]["residual"] for rs in all_rows.values() for r in rs),
            max_evaluator_performance_difference_residual=max(r["performance_difference"]["truth"]["residual"] for rs in all_rows.values() for r in rs),
            max_first_divergence_partition_residual=max(r["first_divergence_partition"]["residual"] for rs in all_rows.values() for r in rs),
            max_linear_head_margin_residual=max((s["linear_identity_residual"] for rs in all_rows.values() for r in rs for s in r["changed_state_records"]), default=0.))
        result = dict(status="POSTHOC_DIAGNOSTIC_COMPLETE_NOT_CONFIRMATORY", protocol_sha256=sha(args.protocol.read_bytes()),
            main_protocol_sha256=sha((ROOT / "PROTOCOL_FROZEN.json").read_bytes()), complete_worlds=48,
            no_new_worlds_or_parameters=True, summary=summaries, identity_checks=checks, inventory=inventory,
            example=dict(rule=protocol["example_rule"], test_index=worst, world_id=example["world_id"],
                         file=f"test_{worst:03d}.json.gz", evaluator_E_minus_C=example["performance_difference"]["truth"]["initial_E_minus_C"]),
            qualification_unchanged_false=True, cpu_seconds=time.process_time() - start,
            wall_seconds=time.perf_counter() - wall,
            caveat="This explains fixed policies on the already exposed48 worlds; it is not new holdout evidence, a causal intervention on individual weights, a general law-error theorem or a repaired candidate.")
        verify_manifest(ROOT, protocol["source_files"])
        verify_manifest(ROOT, protocol["input_files"])
        save(out / "RESULTS.json", result)
        print(__import__("json").dumps(dict(summary=summaries, identity_checks=checks, complete_worlds=48,
                                           cpu_seconds=time.process_time() - start)), flush=True)
        return 0
    except BaseException as exc:
        save(out / "FAILED.json", dict(exception=type(exc).__name__, error=str(exc), traceback=traceback.format_exc(),
            cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
            scientific_qualification_unchanged_false=True))
        traceback.print_exc()
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    sys.exit(main(parser.parse_args()))
