"""Independent mathematical and native-receipt checks for progression v2.

The references below rebuild dynamics from public task parameters. They do not
call the candidate Model.solve, its edge/reward arrays, matrix exponentials, or
candidate policy-gradient code to obtain reference values and first-hit laws.
This is qualification of finite declared tasks, not architectural efficacy.
"""
import argparse
from dataclasses import replace
from functools import lru_cache
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.stats import poisson

from ..task_policy_v2_20261031.planner import OneRead
from ..task_value_factorial_20261030.task import Bellman, metadata
from ..value_boundary_v2_20261031.campaign import declared_protocol
from ..value_boundary_v2_20261031.model import Contract, Model


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def posterior(contract, job, evidence):
    ratio = contract.reliability[job]/(1-contract.reliability[job])
    odds = ratio**evidence
    return odds/(1+odds)


def envelope(contract):
    return [(j,b,m) for j in reversed(range(len(contract.reliability)))
            for b in range(contract.budget+1)
            for m in range(-(contract.budget-b),contract.budget-b+1)]


def valid(contract, state):
    j,b,m = state
    p = posterior(contract,j,m)
    return np.array([True,b>0,max(p,1-p)>=contract.minimum_confidence])


def normalize(contract, states, logits):
    probabilities = np.zeros_like(logits)
    for index,state in enumerate(states):
        mask = valid(contract,state)
        value = np.exp(logits[index,mask]-max(logits[index,mask]))
        probabilities[index,mask] = value/value.sum()
    return probabilities


def independent_values(contract, probabilities=None):
    states = envelope(contract)
    policy = None if probabilities is None else dict(zip(states,probabilities))
    delta = contract.deadline_rate
    survived_recovery = (contract.recovery_rate/(contract.recovery_rate+delta))**contract.recovery_phases
    mean_recovery_time_before_deadline = (1-survived_recovery)/delta

    @lru_cache(None)
    def values(j,b,m):
        state = (j,b,m)
        belief = posterior(contract,j,m)
        q = [0.,-math.inf,-math.inf]
        if valid(contract,state)[2]:
            q[2] = 2*max(belief,1-belief)-1-contract.fire_cost
            if j+1 < len(contract.reliability):
                q[2] += survived_recovery*values(j+1,b,0)-contract.time_cost*mean_recovery_time_before_deadline
        if b:
            rate, reliability = contract.arrival_rate[j],contract.reliability[j]
            read_survival = rate/(rate+delta)
            positive = belief*reliability+(1-belief)*(1-reliability)
            continuation = positive*values(j,b-1,m+1)+(1-positive)*values(j,b-1,m-1)
            q[1] = read_survival*(continuation-contract.query_cost[j])-contract.time_cost/(rate+delta)
        if policy is None:
            return max(q)
        return sum(weight*value for weight,value in zip(policy[state],q) if weight)

    return np.array([values(*state) for state in states])


def independent_hit(contract, states, probabilities, state, horizon):
    """Uniformized event-count recursion; Poisson tails, no matrix exponential."""
    policy = dict(zip(states,probabilities))
    job = state[0]
    rate, delta = contract.arrival_rate[job],contract.deadline_rate
    clock_rate = rate+delta
    mass = {state:float(policy[state][1])}
    probability = float(policy[state][2])
    for count in range(1,state[1]+1):
        future, new_hit = {},0.
        for current,weight in mass.items():
            j,b,m = current
            belief = posterior(contract,j,m)
            reliability = contract.reliability[j]
            positive = belief*reliability+(1-belief)*(1-reliability)
            for increment,observation_probability in ((1,positive),(-1,1-positive)):
                target = (j,b-1,m+increment)
                reached = weight*rate/clock_rate*observation_probability
                new_hit += reached*policy[target][2]
                future[target] = future.get(target,0.)+reached*policy[target][1]
        probability += new_hit*poisson.sf(count-1,clock_rate*horizon)
        mass = {key:value for key,value in future.items() if value}
    return float(probability)


def mathematical_checks():
    rng = np.random.default_rng(6203119)
    rows = []
    for declaration in declared_protocol()["contracts"]:
        contract = Contract(**declaration["contract"])
        model = Model(contract)
        states = envelope(contract)
        if states != list(model.states):
            raise AssertionError("Candidate finite state envelope differs from independent enumeration")
        optimum = independent_values(contract)
        candidate = model.solve()
        qvi_error = float(np.max(np.abs(candidate["value"]-optimum)))
        logits = rng.normal(0,.7,(len(states),3))
        probabilities = normalize(contract,states,logits)
        expected = independent_values(contract,probabilities)
        proposed = model.solve(probabilities)
        value_error = float(np.max(np.abs(expected-proposed["value"])))
        gradient_errors = []
        for _ in range(4):
            direction = rng.normal(size=logits.shape)
            direction /= np.linalg.norm(direction)
            epsilon = 1e-5
            up = independent_values(contract,normalize(contract,states,logits+epsilon*direction))[model.start]
            down = independent_values(contract,normalize(contract,states,logits-epsilon*direction))[model.start]
            finite = (up-down)/(2*epsilon)
            analytic = float(np.sum(direction*proposed["logit_gradient"]))
            gradient_errors.append(abs(finite-analytic))
        hit_errors, derivative_errors = [],[]
        subset = [states[model.start],(0,contract.budget-1,1),(1,contract.budget-2,0)]
        for state in subset:
            for horizon in (0.,1e-5,.2,1.,9.):
                actual = model.first_fire_policy(probabilities,state,horizon)
                reference = independent_hit(contract,states,probabilities,state,horizon)
                hit_errors.append(abs(actual["probability"]-reference))
            for rate_direction,deadline_direction in ((1.,0.),(0.,1.)):
                epsilon = 1e-5
                rate_up,rate_down = list(contract.arrival_rate),list(contract.arrival_rate)
                rate_up[state[0]] += epsilon*rate_direction
                rate_down[state[0]] -= epsilon*rate_direction
                up = replace(contract,arrival_rate=tuple(rate_up),deadline_rate=contract.deadline_rate+epsilon*deadline_direction)
                down = replace(contract,arrival_rate=tuple(rate_down),deadline_rate=contract.deadline_rate-epsilon*deadline_direction)
                finite = (independent_hit(up,states,probabilities,state,.9)-independent_hit(down,states,probabilities,state,.9))/(2*epsilon)
                actual = model.first_fire_policy(probabilities,state,.9,rate_direction,deadline_direction)["derivative"]
                derivative_errors.append(abs(actual-finite))
        row = dict(contract=declaration["name"],states=len(states),qvi_error=qvi_error,
            randomized_value_error=value_error,maximum_logit_gradient_error=max(gradient_errors),
            first_fire_checks=len(hit_errors),maximum_first_fire_error=max(hit_errors),
            first_fire_derivative_checks=len(derivative_errors),maximum_first_fire_derivative_error=max(derivative_errors))
        row["passed"] = (qvi_error<2e-12 and value_error<2e-12 and max(gradient_errors)<2e-8
                         and max(hit_errors)<2e-12 and max(derivative_errors)<2e-8)
        rows.append(row)
    return rows


def independent_one_read(meta, confusion, multiplier, latency_price, state):
    """Enumerate one-read plans and both observations, without candidate helpers."""
    deadline = meta["deadline"]
    def elapsed(tick,steps):
        return sum(meta["duration"][tick:min(tick+steps,deadline)])
    def expected_answer_after_read(job,tick,budget,belief):
        r = meta["reliability"][job][tick]
        law = r*confusion+(1-r)*confusion[::-1]
        probability = (1-belief)*law[0]+belief*law[1]
        after = np.divide(belief*law[1],probability,out=np.full(2,.5),where=probability>0)
        terminal = [max(0.,abs(2*p-1)-latency_price*elapsed(tick+1,2)
                        +value(job+1,tick+3,budget-1,.5)) for p in after]
        return float(probability@terminal)-multiplier*meta["price"][job][tick]-latency_price*elapsed(tick,1)
    @lru_cache(None)
    def value(job,tick,budget,belief):
        if job>=2 or tick>=deadline:
            return 0.
        candidates = [0.,abs(2*belief-1)-latency_price*elapsed(tick,2)+value(job+1,tick+2,budget,.5)]
        if budget:
            for t in range(tick,deadline-1):
                candidates.append(expected_answer_after_read(job,t,budget,belief)-latency_price*elapsed(tick,t-tick))
        return max(candidates)
    job,tick,budget,belief = state
    q = np.array([0.,-np.inf,-np.inf,-np.inf])
    if job>=2 or tick>=deadline:return q
    if tick+1<deadline:
        q[1] = value(job,tick+1,budget,belief)-latency_price*elapsed(tick,1)
        if budget:q[2] = expected_answer_after_read(job,tick,budget,belief)
    q[3] = abs(2*belief-1)-latency_price*elapsed(tick,2)+value(job+1,tick+2,budget,.5)
    return q


def planning_checks():
    from ..task_policy_v2_20261031.campaign import protocol
    spec = protocol()
    rng = np.random.default_rng(6203123)
    rows = []
    for index in range(32):
        confusion = np.array([[.81,.19],[.08,.92]]) if index%2 else np.array([[.97,.03],[.03,.97]])
        meta = metadata(rng,f"audit_environment_{index}",spec)
        planner = OneRead(meta,confusion,spec["multiplier"],spec["latency_price"])
        teacher = Bellman(meta,confusion,spec["multiplier"],spec["latency_price"])
        errors,violations = [],[]
        for _ in range(16):
            state = (int(rng.integers(2)),int(rng.integers(meta["deadline"])),
                     int(rng.integers(meta["budget"]+1)),float(rng.uniform(.01,.99)))
            own = planner.q(*state)
            reference = independent_one_read(meta,confusion,spec["multiplier"],spec["latency_price"],state)
            exact = np.asarray(teacher.q(*state))
            legal = np.isfinite(reference)
            if not np.array_equal(legal,np.isfinite(own)):
                raise AssertionError("Candidate and independent legality differ")
            errors.append(float(np.max(np.abs(own[legal]-reference[legal]))))
            violations.append(max(0.,float(np.max(own[legal]-exact[legal]))))
        rows.append(dict(environment=index,states=16,max_value_error=max(errors),
                         max_lower_bound_violation=max(violations),passed=max(errors)<2e-12 and max(violations)<2e-12))
    return rows


def native_receipts():
    base = HERE.parent/"native_task_bridge_20261031"
    report_path = base/"qualification_dev03/task_parity_cached/REPORT.json"
    rows_path = base/"qualification_dev03/task_parity_cached/ROLLOUTS.json.gz"
    report = json.loads(report_path.read_text())
    rows = json.loads(gzip.decompress(rows_path.read_bytes()))
    errors,child = [],[]
    for row in rows:
        expected_child = sum(x["child_process_usage"]["user_cpu_seconds"]+
                             x["child_process_usage"]["system_cpu_seconds"] for x in row["native_process_accounting"])
        errors.append(abs(expected_child-row["native_child_cpu_seconds"]))
        errors.append(abs(row["parent_cpu_seconds"]+expected_child-row["complete_cpu_seconds"]))
        child.append(expected_child)
        for trace in row["traces"]:
            receipt = trace["native_receipt"]
            if receipt is not None:
                if (receipt["native_physics_executed"] or receipt["production_activation"]
                        or receipt["authority"] != "DENY_ALL"):
                    raise AssertionError("Native fixture exceeded declared authority/scope")
    comparisons = []
    grouped = {}
    for row in rows:grouped.setdefault((row["split"],row["session_id"]),{})[row["backend"]]=row
    if len(grouped)*2 != len(rows):
        raise AssertionError("Duplicate or incomplete backend case identity")
    for key,pair in grouped.items():
        left,right = pair["python"],pair["native"]
        equal = all(left[name]==right[name] for name in ("score","counts","task_elapsed","failure","final_cell_snapshot"))
        equal &= [t["action"] for t in left["traces"]]==[t["action"] for t in right["traces"]]
        comparisons.append(equal)
    scope = {row["backend"]:[] for row in rows}
    for row in rows:
        if row["split"] != "failed_read":scope[row["backend"]].append(row["complete_cpu_seconds"])
    return dict(rollouts=len(rows),pairs=len(comparisons),all_semantic_pairs_equal=all(comparisons),
        reads=sum(r["counts"]["packet_file_reads"] for r in rows),
        decoder_calls=sum(r["counts"]["content_invocations"] for r in rows),
        summed_child_cpu=sum(child),reported_child_cpu=report["total_native_child_cpu_seconds"],
        maximum_parent_plus_child_record_difference=max(errors),
        mean_normal_cpu={k:float(np.mean(v)) for k,v in scope.items()},
        cpu_arithmetic_scope="Enclosing parent CPU fields are sampled successively, so allow 10 microseconds of measurement-call overhead",
        passed=all(comparisons) and max(errors)<1e-5
                and abs(sum(child)-report["total_native_child_cpu_seconds"])<1e-10)


def main(out):
    wall,cpu = time.perf_counter(),time.process_time()
    mathematical = mathematical_checks()
    planning = planning_checks()
    native = native_receipts()
    sources = [HERE/"independent_checks.py"]
    for package in ("task_policy_v2_20261031","value_boundary_v2_20261031","recurrent_owner_v2_20261031","native_task_bridge_20261031"):
        sources.extend((HERE.parent/package).glob("*.py"))
        sources.extend((HERE.parent/package).glob("*.rs"))
    result = dict(schema="hcsn.progression.independent-audit.v1",passed=all(r["passed"] for r in mathematical+planning) and native["passed"],
        mathematical=mathematical,one_read=planning,native=native,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        scope="Independent finite recurrence, event-count/Poisson first-event law, full logit FD, one-read plan enumeration and native raw receipts. No confirmation efficacy assessed here.")
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("x") as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(passed=result["passed"],mathematical_contracts=len(mathematical),planning_states=sum(r["states"] for r in planning),native=native)))
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    raise SystemExit(0 if main(args.out) else 1)
