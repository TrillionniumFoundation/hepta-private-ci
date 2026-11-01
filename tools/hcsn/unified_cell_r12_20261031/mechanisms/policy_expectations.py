"""Exact finite-model policy evaluation; no sampling or dataset generation."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import expm
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from contract import as_numpy, model_terms, true_model
from control.controller import plan


def expectation(truth, candidate, dt, horizon=3, budget=2):
    true_p = expm(truth["Q"]*dt)
    candidate_p = expm(candidate["Q"]*dt)
    bits = np.arange(len(truth["prior"]))//(len(truth["prior"])//2)

    def evaluate(reference_belief, actor_belief, remaining, reads):
        action = int(plan(actor_belief[None], candidate_p, candidate["emission"],
            candidate["answer_rewards"], candidate["read_cost"],
            horizon=remaining, budget=reads, dt=dt).action[0])
        if action < 2:
            return np.array([reference_belief @ truth["answer_rewards"][:, action],
                reference_belief @ (bits == action), 0., 0., 0.])
        reference_next, actor_next = reference_belief @ true_p, actor_belief @ candidate_p
        if action == 2:
            result = evaluate(reference_next, actor_next, remaining-1, reads)
            result[0] -= 0.01*dt
            result[4] += 1
            return result
        result = np.array([-0.01*dt-reference_next @ truth["read_cost"], 0., 1., 0., 0.])
        true_weights, model_weights = reference_next @ truth["emission"], actor_next @ candidate["emission"]
        for token, weight in enumerate(true_weights):
            if weight == 0:
                continue
            if model_weights[token] <= 0:
                raise ValueError("Candidate model rejects a possible true observation")
            posterior = reference_next*truth["emission"][:, token]/weight
            actor_posterior = actor_next*candidate["emission"][:, token]/model_weights[token]
            result += weight*evaluate(posterior, actor_posterior, remaining-1, reads-1)
        result[3] += true_weights[6]
        return result

    return evaluate(truth["prior"], candidate["prior"], horizon, budget)


def main():
    torch.set_num_threads(1)
    spec = json.loads((HERE/"SPEC.json").read_text())
    truth = true_model()
    candidates = {"full": truth}
    no_equity = {k: v.copy() for k, v in truth.items()}
    no_equity["answer_rewards"] -= no_equity["answer_rewards"].min(axis=1)[:, None]
    candidates["zero_equity_bonus"] = no_equity
    constant = {k: v.copy() for k, v in truth.items()}
    constant["read_cost"][:] = truth["prior"] @ truth["read_cost"]
    candidates["constant_read_cost"] = constant
    for recovery in (0.05, 1.0):
        with torch.no_grad():
            changed = as_numpy(model_terms(theta=torch.tensor(truth["theta"]), recovery=recovery))
        changed["emission"] = truth["emission"].copy()
        candidates[f"recovery_{recovery}"] = changed
    results = {}
    for name, candidate in candidates.items():
        rows = np.stack([expectation(truth, candidate, dt) for dt in spec["times"]])
        if name == "full":
            direct = np.array([plan(truth["prior"][None], expm(truth["Q"]*dt), truth["emission"],
                truth["answer_rewards"], truth["read_cost"], dt=dt).value[0] for dt in spec["times"]])
            np.testing.assert_allclose(rows[:, 0], direct, atol=2e-14, rtol=2e-14)
        else:
            assert np.all(rows[:, 0] <= np.array(results["full"]["by_dt"])[:, 0]+1e-13)
        results[name] = {"by_dt": rows.tolist(), "uniform_announced_dt_mean": rows.mean(axis=0).tolist()}
    base = np.array(results["full"]["uniform_announced_dt_mean"])
    for result in results.values():
        result["mean_utility_difference_from_full"] = float(np.array(result["uniform_announced_dt_mean"])[0]-base[0])
    sources = [Path(__file__), ROOT/"contract.py", ROOT/"control/controller.py", HERE/"SPEC.json"]
    payload = {"scope": "Exact evaluation of the declared finite model and policies; no samples, learned fits or confirmation outcomes.",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "development_outcomes_sha256": hashlib.sha256((HERE/"DEVELOPMENT_MECHANISMS.json").read_bytes()).hexdigest(),
        "times": spec["times"], "metric_columns": ["utility", "accuracy", "reads", "unavailable_reads", "waits"],
        "time_weighting": "Uniform over the three announced episode intervals, as in the declared generator.",
        "results": results, "formal_gain_acceptance": False}
    target = HERE/"EXACT_POLICY_EXPECTATIONS.json"
    if target.exists():
        raise FileExistsError("Do not overwrite mechanism evidence")
    target.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({name: row["mean_utility_difference_from_full"] for name, row in results.items()}))


if __name__ == "__main__":
    main()
