"""Independent algebra, derivatives, stochastic clocks and real-effect checks.

Development qualification only. This module does not create a heldout campaign.
"""
import argparse
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.optimize import linprog

from .deployment import load_policy, write_policy
from .learn import fit_region
from .model import Contract, FIRE, Model, READ, STOP, softmax_policy
from .owner import Owner, PayloadBank, execute, semantic_trace


def independent_linear_program(contract, states):
    """Build Bellman inequalities directly, without Model rewards/edges."""
    count = len(states)
    lookup = {s:i for i, s in enumerate(states)}
    constraints, limits = [], []
    d, c, gamma = contract.deadline_rate, contract.time_cost, contract.recovery_rate
    beta = gamma/(gamma+d)
    recovery = c/(gamma+d)*sum(beta**k for k in range(contract.recovery_phases))
    for i, (job, budget, evidence) in enumerate(states):
        q = contract.reliability[job]
        odds = (q/(1-q))**evidence
        belief = odds/(1+odds)
        row = np.zeros(count)
        row[i] = -1
        reward = abs(2*belief-1)-contract.fire_cost
        if job+1 < len(contract.reliability):
            row[lookup[job+1, budget, 0]] = beta**contract.recovery_phases
            reward -= recovery
        if max(belief, 1-belief) >= contract.minimum_confidence:
            constraints.append(row)
            limits.append(-reward)
        if budget:
            rate = contract.arrival_rate[job]
            plus = belief*q+(1-belief)*(1-q)
            row = np.zeros(count)
            row[i] = -(rate+d)
            row[lookup[job, budget-1, evidence+1]] += rate*plus
            row[lookup[job, budget-1, evidence-1]] += rate*(1-plus)
            constraints.append(row)
            limits.append(rate*contract.query_cost[job]+c)
    result = linprog(np.ones(count), A_ub=np.asarray(constraints), b_ub=np.asarray(limits),
                     bounds=[(0, None)]*count, method="highs")
    if not result.success:
        raise ArithmeticError(result.message)
    return result.x


def independent_paths(contract, actions, states, seed, trials):
    """Ground-truth Monte Carlo; one deadline competes with all actual waits."""
    rng = np.random.default_rng(seed)
    lookup = {state:i for i, state in enumerate(states)}
    values, first_times, elapsed_times = [], [], []
    for _ in range(trials):
        truth = rng.integers(0, 2, len(contract.reliability))
        deadline = rng.exponential(1/contract.deadline_rate)
        job, budget, evidence, elapsed, utility = 0, contract.budget, 0, 0., 0.
        first = None
        while job < len(contract.reliability) and elapsed < deadline:
            selected = actions[lookup[job, budget, evidence]]
            action = int(rng.choice(3, p=selected)) if np.ndim(selected) else int(selected)
            if action == STOP:
                break
            if action == READ:
                waiting = rng.exponential(1/contract.arrival_rate[job])
                actual = min(waiting, deadline-elapsed)
                elapsed += actual
                utility -= contract.time_cost*actual
                if actual < waiting:
                    break
                utility -= contract.query_cost[job]
                observation = truth[job] if rng.random() < contract.reliability[job] else 1-truth[job]
                evidence += 2*observation-1
                budget -= 1
            else:
                if first is None:
                    first = elapsed
                utility += (1 if int(evidence >= 0) == truth[job] else -1)-contract.fire_cost
                job += 1
                evidence = 0
                if job == len(contract.reliability):
                    break
                for _ in range(contract.recovery_phases):
                    waiting = rng.exponential(1/contract.recovery_rate)
                    actual = min(waiting, deadline-elapsed)
                    elapsed += actual
                    utility -= contract.time_cost*actual
                    if actual < waiting:
                        break
        values.append(utility)
        elapsed_times.append(elapsed)
        first_times.append(first)
    return dict(values=values, first_fire_times=first_times, elapsed=elapsed_times)


def qualify(out, trials=20000, real_sessions=24):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    begin, begin_cpu = time.perf_counter(), time.process_time()
    source_root = Path(__file__).resolve().parent
    source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_root.glob("*.py")}
    (out/"source").mkdir()
    for name in source:
        shutil.copyfile(source_root/name, out/"source"/name)
    checks, details = [], {}

    def check(name, passed, **fields):
        checks.append(dict(name=name, passed=bool(passed), **fields))

    contexts = [Contract(reliability=(.80, .86), arrival_rate=(2., 2.5),
        query_cost=(.03, .04), deadline_rate=.10),
        Contract(reliability=(.9, .67), arrival_rate=(3., 1.),
        query_cost=(.02, .16), deadline_rate=.3, recovery_rate=2.5),
        Contract(reliability=(.62, .86), arrival_rate=(1., 2.2), query_cost=(.08, .03),
                 deadline_rate=.2, time_cost=.05, recovery_rate=2.),
        Contract(reliability=(.8, .8), arrival_rate=(2., 2.), query_cost=(.01, .01),
                 deadline_rate=.05, time_cost=.01, recovery_rate=6.),
        Contract(reliability=(.55, .55), arrival_rate=(.5, .5), query_cost=(.8, .8),
                 deadline_rate=.5, time_cost=.1, recovery_rate=1.),
        Contract(reliability=(.68, .88), arrival_rate=(2.5, 2.), query_cost=(.02, .04),
                 deadline_rate=.08, recovery_rate=6., budget=6)]
    fits, programs = [], []
    for number, contract in enumerate(contexts):
        model = Model(contract)
        exact = model.solve()
        independent = independent_linear_program(contract, model.states)
        error = float(np.max(np.abs(independent-exact["value"])))
        check(f"qvi_linear_program_{number}", error < 2e-10, maximum_error=error)
        fits.append(fit_region(contract, 873100+number, updates=600))
        programs.append(dict(contract=contract.serializable(), states=model.states,
            exact_value=exact["value"].tolist(), actions=np.argmax(exact["policy"], axis=1).tolist(),
            initial_value=exact["initial_value"], linear_program=independent.tolist()))
        check(f"direct_task_fit_finite_{number}",
              np.isfinite(fits[-1]["soft_value"]+fits[-1]["hard_value"]),
              hard_optimality_gap=fits[-1]["hard_optimality_gap"],
              hard_bellman_residual=fits[-1]["hard_bellman_residual"],
              soft_maximum_gradient=fits[-1]["soft_maximum_gradient"])
        changes = np.diff([row["value"] for row in fits[-1]["trace"]])
        check(f"mirror_task_value_monotonic_{number}", np.all(changes >= -2e-12),
              smallest_recorded_improvement=float(np.min(changes)))
    model = Model(contexts[0])
    deployments = {}
    for kind in ("hard", "soft"):
        arguments = dict(actions=fits[0]["hard_actions"]) if kind == "hard" else dict(probabilities=np.asarray(fits[0]["probabilities"]))
        descriptor = write_policy(out, f"qualification_{kind}", model, **arguments)
        artifact, load_timing = load_policy(out, descriptor)
        probabilities = model.deterministic(artifact["actions"]) if kind == "hard" else np.asarray(artifact["probabilities"])
        value = model.solve(probabilities)["initial_value"]
        check(f"deployable_{kind}_artifact_roundtrip", abs(value-fits[0][f"{kind}_value"]) < 1e-14,
              value=value, descriptor=descriptor, load_timing=load_timing)
        deployments[kind] = descriptor
    rng = np.random.default_rng(873200)
    logits = rng.normal(0, .2, model.valid.shape)
    evaluated = model.solve(softmax_policy(model, logits))
    gradient = evaluated["logit_gradient"]
    directional = []
    for axis in range(3):
        direction = rng.normal(size=logits.shape)
        direction /= np.linalg.norm(direction)
        tangent = float(np.sum(gradient*direction))
        for epsilon in (1e-5, 2e-6):
            plus = model.solve(softmax_policy(model, logits+epsilon*direction))["initial_value"]
            minus = model.solve(softmax_policy(model, logits-epsilon*direction))["initial_value"]
            finite = (plus-minus)/(2*epsilon)
            error = abs(tangent-finite)
            check(f"complete_task_gradient_{axis}_{epsilon}", error < 2e-9,
                  analytic=tangent, finite_difference=finite, absolute_error=error)
            directional.append(dict(direction=direction.tolist(), epsilon=epsilon,
                                    analytic=tangent, finite_difference=finite))
    reference = model.solve()
    actions = np.argmax(reference["policy"], axis=1)
    for rate_direction, deadline_direction in ((1., 0.), (0., 1.)):
        horizon = 1.7
        result = model.first_fire(actions, (0, contexts[0].budget, 0), horizon,
                                  rate_direction, deadline_direction)
        epsilon = 1e-5
        plus = replace(contexts[0], arrival_rate=(contexts[0].arrival_rate[0]+epsilon*rate_direction,
                       contexts[0].arrival_rate[1]), deadline_rate=contexts[0].deadline_rate+epsilon*deadline_direction)
        minus = replace(contexts[0], arrival_rate=(contexts[0].arrival_rate[0]-epsilon*rate_direction,
                        contexts[0].arrival_rate[1]), deadline_rate=contexts[0].deadline_rate-epsilon*deadline_direction)
        finite = (Model(plus).first_fire(actions, (0, contexts[0].budget, 0), horizon)["probability"]-
                  Model(minus).first_fire(actions, (0, contexts[0].budget, 0), horizon)["probability"])/(2*epsilon)
        check(f"first_fire_frechet_{rate_direction}_{deadline_direction}",
              abs(finite-result["derivative"]) < 2e-9, finite_difference=finite, **result)
    mc = independent_paths(contexts[0], actions, model.states, 873300, trials)
    values = np.asarray(mc["values"])
    standard_error = float(values.std(ddof=1)/np.sqrt(trials))
    check("ground_truth_continuing_value", abs(float(values.mean())-reference["initial_value"]) < 6*standard_error+.001,
          trials=trials, analytic_value=reference["initial_value"], sample_mean=float(values.mean()), standard_error=standard_error)
    for horizon in (.2, 1., 3.):
        hits = sum(t is not None and t <= horizon for t in mc["first_fire_times"])
        empirical = hits/trials
        probability = model.first_fire(actions, (0, contexts[0].budget, 0), horizon)["probability"]
        se = np.sqrt(max(empirical*(1-empirical), 1/trials)/trials)
        check(f"ground_truth_first_fire_{horizon}", abs(probability-empirical) < 6*se+.001,
              analytic=probability, empirical=empirical, standard_error=float(se))
    soft_probabilities = softmax_policy(model, logits)
    soft_mc = independent_paths(contexts[0], soft_probabilities, model.states, 873301, trials)
    soft_value = model.solve(soft_probabilities)["initial_value"]
    soft_values = np.asarray(soft_mc["values"])
    soft_se = float(soft_values.std(ddof=1)/np.sqrt(trials))
    check("randomized_boundary_ground_truth_value", abs(soft_value-float(soft_values.mean())) < 6*soft_se+.001,
          analytic=soft_value, empirical=float(soft_values.mean()), standard_error=soft_se)
    for horizon in (0., .2, 1.):
        empirical = sum(t is not None and t <= horizon for t in soft_mc["first_fire_times"])/trials
        summary = model.first_fire_policy(soft_probabilities, (0, contexts[0].budget, 0), horizon)
        se = np.sqrt(max(empirical*(1-empirical), 1/trials)/trials)
        check(f"randomized_boundary_first_fire_{horizon}", abs(summary["probability"]-empirical) < 6*se+.001,
              empirical=empirical, standard_error=float(se), **summary)
    active_state = (0, contexts[0].budget-1, 1)
    atom = model.first_fire_policy(soft_probabilities, active_state, 0.)
    active_index = model.index[active_state]
    check("randomized_legal_boundary_initial_atom",
          abs(atom["initial_atom"]-soft_probabilities[active_index, FIRE]) < 1e-15
          and abs(atom["at_risk"]-soft_probabilities[active_index, READ]) < 1e-15
          and atom["initial_atom"] > 0, **atom)
    bank = PayloadBank(out/"finite_support")
    real = []
    for index in range(real_sessions):
        episode = bank.make_episode(out/"episodes", contexts[0], f"development_{index:04d}", 873400+index)
        ordinary = execute(episode, contexts[0], bank, actions, mode="ordinary_gate")
        analytic = execute(episode, contexts[0], bank, actions, mode="analytic_boundary")
        check(f"ordinary_analytic_pathwise_null_{index}", semantic_trace(ordinary) == semantic_trace(analytic))
        real.append(dict(episode=episode, ordinary=ordinary, analytic=analytic))
        if index < 6:
            ordinary_soft = execute(episode, contexts[0], bank, probabilities=soft_probabilities,
                                    rng_seed=882000+index, mode="ordinary_gate")
            analytic_soft = execute(episode, contexts[0], bank, probabilities=soft_probabilities,
                                    rng_seed=882000+index, mode="analytic_boundary")
            check(f"randomized_pathwise_null_{index}", semantic_trace(ordinary_soft) == semantic_trace(analytic_soft))
            real[-1].update(ordinary_soft=ordinary_soft, analytic_soft=analytic_soft)
    # Force one global deadline to fall inside the second recovery phase.
    episode = bank.make_episode(out/"episodes", contexts[0], "development_censored_recovery", 873999)
    owner = Owner(episode, contexts[0], bank)
    owner.clocks["deadline"] = .25
    owner.clocks["read_waits"][0][0] = .1
    owner.clocks["recovery_waits"][0] = [.1, .1]
    owner.act(READ)
    owner.act(FIRE)
    check("single_global_deadline_censors_recovery", owner.terminal and owner.elapsed == .25
          and owner.counts["READ"] == 1 and owner.counts["FIRE"] == 1
          and owner.counts["recovery_phases"] == 1 and owner.counts["deadline"] == 1,
          events=owner.events, score=owner.score())
    guarded = contexts[-1]
    episode = bank.make_episode(out/"episodes", guarded, "development_quality_guard", 874001)
    owner = Owner(episode, guarded, bank)
    before = (owner.state, owner.elapsed, list(owner.events))
    rejected = False
    try:
        owner.act(FIRE)
    except ValueError:
        rejected = True
    check("quality_guard_rejects_uninformed_submission_without_effect", rejected
          and before == (owner.state, owner.elapsed, owner.events))
    # A real model call followed by a support-contract failure remains charged.
    episode = bank.make_episode(out/"episodes", contexts[0], "development_failed_support", 874002)
    folder = Path(episode["folder"])
    target = folder/"job0_read0.json"
    original = target.read_bytes()
    (folder/"original_job0_read0.json").write_bytes(original)
    invalid_support = json.loads(original)
    invalid_support["symbols"][1] = (invalid_support["symbols"][1]+1) % 4
    target.write_text(json.dumps(invalid_support, sort_keys=True))
    clock_path = folder/"private_clocks.json"
    original_clocks = clock_path.read_bytes()
    (folder/"original_private_clocks.json").write_bytes(original_clocks)
    clocks = json.loads(original_clocks)
    clocks["deadline"] = 100.
    clocks["read_waits"][0][0] = .1
    clock_path.write_text(json.dumps(clocks, sort_keys=True))
    failed = execute(episode, contexts[0], bank, actions=actions, capture_failure=True)
    check("failed_support_retains_actual_decoder_charge_and_receipt", failed["failure"] is not None
          and failed["counts"]["decoder_calls"] == 1
          and failed["counts"]["successful_decoder_calls"] == 1
          and failed["counts"]["failed_reads"] == 1
          and failed["counts"]["support_check_reads"] == 1
          and failed["score"]["query_charge"] == contexts[0].query_cost[0]
          and "decoded" in failed["events"][0], result=failed,
          original_packet_sha256=hashlib.sha256(original).hexdigest(),
          altered_packet_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    details.update(context_programs=programs, direct_fits=fits, gradient_checks=directional,
                   monte_carlo=mc, randomized_monte_carlo=soft_mc,
                   support=bank.receipt, real_execution=real, deployment_roundtrip=deployments)
    source_after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_root.glob("*.py")}
    check("source_unchanged_during_qualification", source == source_after)
    result = dict(schema="hcsn.regenerative-evidence.development-qualification.v1", source=source,
        passed=all(row["passed"] for row in checks), checks=checks, **details,
        cpu_seconds=time.process_time()-begin_cpu, wall_seconds=time.perf_counter()-begin,
        scope="Development only; exact finite verified-support channel, exponential deadline, no heldout generalization claim",
        analytic_independent_task_advantage_claim=False,
        hard_boundary_derivative="Zero within each fixed finite active set; set changes are nonsmooth and explicitly outside the Frechet claim")
    path = out/"QUALIFICATION.json.gz"
    with path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(result, sort_keys=True, allow_nan=False).encode(), mtime=0))
    print(json.dumps(dict(passed=result["passed"], checks=len(checks),
        failed=[r["name"] for r in checks if not r["passed"]], output=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        hard_gaps=[r["hard_optimality_gap"] for r in fits])))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=20000)
    parser.add_argument("--real-sessions", type=int, default=24)
    arguments = parser.parse_args()
    if not qualify(arguments.out, arguments.trials, arguments.real_sessions)["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
