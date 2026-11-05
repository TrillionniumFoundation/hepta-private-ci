"""Exact classical binary SPRT reference; distinct from Bayesian net-utility DP."""
from fractions import Fraction as F
import argparse
import hashlib
import json
import math
from pathlib import Path


def exact_sprt(p, delta):
    p, delta = F(p), F(delta)
    if not F(1, 2) < p < 1 or not 0 < delta < F(1, 2):
        raise ValueError("Require 1/2 < p < 1 and 0 < delta < 1/2")
    ratio, boundary = (1-p)/p, 1
    while ratio**boundary > delta:
        boundary += 1
    error = ratio**boundary/(1+ratio**boundary)
    count = F(boundary)*(1-2*error)/(2*p-1)
    increment = math.log(float(p/(1-p)))
    divergence = float(2*p-1)*increment
    required = float(1-2*delta)*math.log(float((1-delta)/delta))
    lower = required/divergence
    upper = (math.log(float(1/delta))+increment)/divergence
    return {"boundary": boundary, "error": error, "expected_queries": count,
            "log_likelihood_increment": increment, "kl_per_query": divergence,
            "required_information": required, "count_lower_bound": lower,
            "count_upper_bound": upper, "ratio_to_lower_bound": float(count)/lower}


def absorbing_chain(p, boundary):
    """Independent exact rational Thomas solve of transient Bellman equations."""
    p, q = F(p), 1-F(p)
    if not 0 < p < 1 or type(boundary) is not int or boundary < 1:
        raise ValueError("Invalid walk")
    size = 2*boundary-1

    def solve(rhs):
        diagonal, answer = [F(1)]*size, list(rhs)
        for i in range(1, size):
            multiplier = -q/diagonal[i-1]
            diagonal[i] -= multiplier*(-p)
            answer[i] -= multiplier*answer[i-1]
        answer[-1] /= diagonal[-1]
        for i in range(size-2, -1, -1):
            answer[i] = (answer[i]+p*answer[i+1])/diagonal[i]
        return answer[boundary-1]

    return solve([q]+[F(0)]*(size-1)), solve([F(1)]*size)


def deadline_walk(p, boundary, cap):
    p, q = F(p), 1-F(p)
    if not F(1, 2) < p < 1 or type(boundary) is not int or boundary < 1 or type(cap) is not int or cap < 0:
        raise ValueError("Invalid finite walk")
    alive, wrong, correct, count = {0: F(1)}, F(0), F(0), F(0)
    for _ in range(cap):
        count += sum(alive.values(), F(0))
        next_alive = {}
        for position, mass in alive.items():
            for step, probability in ((1, p), (-1, q)):
                successor, weight = position+step, mass*probability
                if successor == boundary:
                    correct += weight
                elif successor == -boundary:
                    wrong += weight
                else:
                    next_alive[successor] = next_alive.get(successor, F(0))+weight
        alive = next_alive
    unresolved = sum(alive.values(), F(0))
    forced_error = wrong+sum((mass for s, mass in alive.items() if s < 0), F(0))+alive.get(0, F(0))/2
    full_sample_error = sum((math.comb(cap, k)*p**k*q**(cap-k) for k in range((cap+1)//2)), F(0))
    if cap % 2 == 0:
        full_sample_error += F(math.comb(cap, cap//2), 2)*(p*q)**(cap//2)
    if wrong+correct+unresolved != 1:
        raise ArithmeticError("Lost stopped-path probability mass")
    return {"unresolved": unresolved, "forced_error": forced_error, "expected_queries": count,
            "optimal_full_cap_error": full_sample_error}


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("Evidence is immutable; use an empty destination")
    directory = Path(__file__).parent
    protocol_bytes = (directory/"binary_sprt.protocol.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    (destination/"protocol.json").write_bytes(protocol_bytes)
    p, fee, duration = (F(protocol[k]) for k in ("p_plus", "fee_per_query", "duration_per_query"))
    rows, deadlines = [], []
    for delta_text in protocol["deltas"]:
        delta = F(delta_text)
        row = exact_sprt(p, delta)
        error, count = absorbing_chain(p, row["boundary"])
        if (error, count) != (row["error"], row["expected_queries"]):
            raise ArithmeticError("Closed form and independent absorbing chain disagree")
        if not error <= delta or not row["count_lower_bound"]-1e-12 <= float(count) <= row["count_upper_bound"]+1e-12:
            raise ArithmeticError("Fixed-confidence or cost bounds failed")
        rows.append({"delta": delta_text, **row, "expected_cost": fee*count,
                     "expected_model_time": duration*count, "cost_lower_bound": float(fee)*row["count_lower_bound"],
                     "cost_upper_bound": float(fee)*row["count_upper_bound"], "independent_chain_equal": True})
        for cap in protocol["deadline_query_caps"]:
            finite = deadline_walk(p, row["boundary"], cap)
            deadlines.append({"delta": delta_text, "cap": cap, **finite,
                              "information_obstruction": cap*row["kl_per_query"] < row["required_information"],
                              "uniform_correctness_met": finite["forced_error"] <= delta,
                              "any_rule_obstruction_exact": finite["optimal_full_cap_error"] > delta})
    source = {name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
              for name in ("binary_sprt.py", "test_binary_sprt.py")}
    payload = {"schema": "ndu-identification.binary-sprt.v1", "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
               "source_sha256": source, "unlimited_rows": rows, "deadline_rows": deadlines,
               "arithmetic": "rational exact error/count/cost/time; float natural logs for information bounds",
               "fraction_fields": "exact rational strings; no Monte Carlo confidence intervals"}
    target = destination/"results.json"
    target.write_text(json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    print(json.dumps({"result": str(target), "unlimited_cells": len(rows), "deadline_cells": len(deadlines),
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
