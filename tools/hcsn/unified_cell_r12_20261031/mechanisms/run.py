"""Development-only action mechanisms in the actual finite R12 model."""

import hashlib
import itertools
import json
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import expm
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from contract import as_numpy, emission_matrix, model_terms, true_model
from control.controller import marginalization_diagnostics, plan
from data import EvidenceWorld, sequences
from evaluation import episode_run

SPEC = json.loads((HERE / "SPEC.json").read_text())


def copied(model):
    return {key: value.copy() for key, value in model.items()}


def descriptors_and_beliefs(model, family):
    n, width = len(model["grid"]), len(model["Q"])//2
    descriptors, beliefs = [], []
    for low, high in itertools.combinations(range(n), 2):
        if family == "factorized":
            for weight in SPEC["correlated_content_weights"]:
                for orientation in (0, 1):
                    joint = np.zeros((2, width))
                    a, b = (low, high) if orientation == 0 else (high, low)
                    joint[0, a], joint[1, b] = weight, 1-weight
                    descriptors.append([low, high, weight, orientation])
                    beliefs.append(joint.ravel())
        else:
            for mixing in SPEC["distance_mixture_weights"]:
                phase = np.zeros(width)
                phase[low], phase[high] = mixing, 1-mixing
                for weight in SPEC["independent_content_weights"]:
                    descriptors.append([low, high, mixing, weight])
                    beliefs.append((np.array([weight, 1-weight])[:, None]*phase).ravel())
    return descriptors, np.array(beliefs)


def project(beliefs, model, family):
    width, n = len(model["Q"])//2, len(model["grid"])
    joint = beliefs.reshape(-1, 2, width)
    content = joint.sum(axis=2)
    phases = joint.sum(axis=1)
    if family == "mean_compressed":
        assert np.all(phases[:, n:] == 0)
        distance = phases[:, :n] @ model["grid"]
        low = np.clip(np.searchsorted(model["grid"], distance, side="right")-1, 0, n-1)
        high = np.minimum(low+1, n-1)
        weight = (distance-model["grid"][low])/(model["grid"][1]-model["grid"][0])
        weight = np.where(high == low, 0, weight)
        phases = np.zeros_like(phases)
        phases[np.arange(len(phases)), low] = 1-weight
        phases[np.arange(len(phases)), high] += weight
    return (content[:, :, None]*phases[:, None, :]).reshape(beliefs.shape)


def projection_search(model, family):
    descriptors, beliefs = descriptors_and_beliefs(model, family)
    projected = project(beliefs, model, family)
    width, n = len(model["Q"])//2, len(model["grid"])
    original_joint, projected_joint = beliefs.reshape(-1, 2, width), projected.reshape(-1, 2, width)
    content_error = float(abs(original_joint.sum(2)-projected_joint.sum(2)).max())
    phase_original, phase_projected = original_joint.sum(1), projected_joint.sum(1)
    distance_error = float(abs((phase_original[:, :n]-phase_projected[:, :n]) @ model["grid"]).max())
    assert content_error < 1e-14 and distance_error < 1e-14
    traces, witness, maximum = [], None, -1.0
    for dt in SPEC["times"]:
        P = expm(model["Q"]*dt)
        for start in range(0, len(beliefs), 128):
            end = min(start+128, len(beliefs))
            actual = plan(beliefs[start:end], P, model["emission"], model["answer_rewards"],
                          model["read_cost"], horizon=SPEC["horizon"], budget=SPEC["read_budget"], dt=dt)
            approximation = plan(projected[start:end], P, model["emission"], model["answer_rewards"],
                                 model["read_cost"], horizon=SPEC["horizon"], budget=SPEC["read_budget"], dt=dt)
            regret = actual.value-actual.qvalues[np.arange(end-start), approximation.action]
            for k in range(end-start):
                index = start+k
                traces.append([index, dt, int(actual.action[k]), int(approximation.action[k]), float(regret[k])])
                if regret[k] > maximum:
                    maximum = float(regret[k])
                    witness = {"catalog_index": index, "descriptor": descriptors[index], "dt": dt,
                        "belief": beliefs[index].tolist(), "projected_belief": projected[index].tolist(),
                        "full_q": actual.qvalues[k].tolist(), "projected_q": approximation.qvalues[k].tolist(),
                        "full_action": int(actual.action[k]), "projected_action": int(approximation.action[k]),
                        "one_decision_regret": maximum,
                        "content_probabilities": original_joint[index].sum(1).tolist(),
                        "distance_mean": float(phase_original[index, :n] @ model["grid"])}
    return {"family": family, "catalog_descriptors": descriptors, "belief_count": len(beliefs),
        "comparison_count": len(traces), "content_marginal_error": content_error,
        "distance_mean_error": distance_error,
        "phase_marginal_error": float(abs(phase_original-phase_projected).max()),
        "action_change_count": sum(row[2] != row[3] for row in traces),
        "positive_regret_count": sum(row[4] > 1e-8 for row in traces),
        "max_one_decision_regret": maximum, "witness": witness,
        "trace_columns": ["catalog_index", "dt", "full_action", "projected_action", "one_decision_regret"],
        "trace": traces,
        "regret_scope": "One projected action evaluated by full-model Q, followed by optimal continuation; not the value of an entire projected-policy episode.",
        "reachability_scope": "Constructed valid probability laws; not asserted reachable under the experimental prior and sensor."}


def summarize_episode(run, reference):
    history = np.array(run["actions"])
    reference_history = np.array(reference["actions"])
    utility_delta = np.array(run["utility"])-reference["utility"]
    return {"mean_utility": run["mean_utility"], "mean_accuracy": run["mean_accuracy"],
        "utility_difference_from_full": float(utility_delta.mean()),
        "episodes_with_changed_actions": int(np.any(history != reference_history, axis=1).sum()),
        "first_action_changes": int((history[:, 0] != reference_history[:, 0]).sum()),
        "action_counts": [int((history == action).sum()) for action in range(4)],
        "reads": run["read_calls"], "unavailable_recovery_reads": run["recovery_read_calls"],
        "available_reads": run["read_calls"]-run["recovery_read_calls"],
        "advances": run["advance_calls"], "episode_utility_differences": utility_delta.tolist()}


def episode_ablations(model):
    world = EvidenceWorld(SPEC["seed"], SPEC["episode_count"], model, SPEC["times"])

    def run(candidate):
        return episode_run("generic_hmm", "finite_horizon_value", None,
                           candidate, world, SPEC["times"])

    baseline = run(model)
    no_equity = copied(model)
    bonus = np.min(no_equity["answer_rewards"], axis=1)
    no_equity["answer_rewards"] -= bonus[:, None]
    constant = copied(model)
    constant_price = float(model["prior"] @ model["read_cost"])
    constant["read_cost"][:] = constant_price
    runs = {"full": baseline, "zero_equity_bonus": run(no_equity),
            "constant_read_cost": run(constant)}
    recovery_runs = {}
    for recovery in SPEC["recovery_means"]:
        if recovery == 0.35:
            recovery_runs[str(recovery)] = baseline
        else:
            with torch.no_grad():
                changed = as_numpy(model_terms(theta=torch.tensor(model["theta"]), recovery=recovery))
                changed["emission"] = emission_matrix().numpy()
            assert np.array_equal(changed["answer_rewards"], model["answer_rewards"])
            assert np.array_equal(changed["read_cost"], model["read_cost"])
            recovery_runs[str(recovery)] = run(changed)
    return {"seed": SPEC["seed"], "episodes": world.count,
        "constant_read_price": constant_price,
        "true_recovery_mean": 0.35,
        "environment_scope": "Actual world, payoff, read charges and hidden-state dynamics remain the true model; only the controller/filter candidate changes.",
        "finance": {name: {"summary": summarize_episode(result, baseline), "raw_episode": result}
                    for name, result in runs.items()},
        "recovery_misspecification": {name: {"summary": summarize_episode(result, baseline), "raw_episode": result}
                                     for name, result in recovery_runs.items()}}


def causal_monte_carlo(model):
    prefix = sequences(SPEC["seed"], SPEC["causal_prefix_count"], model, SPEC["times"],
                       SPEC["causal_prefix_length"])
    beliefs = prefix["posterior"][:, -1]
    result = marginalization_diagnostics(beliefs, expm(model["Q"]*SPEC["mc_future_dt"]),
        model["emission"], model["answer_rewards"], model["read_cost"],
        horizon=SPEC["horizon"], budget=SPEC["read_budget"], dt=SPEC["mc_future_dt"],
        mc_samples=SPEC["mc_samples"], repetitions=SPEC["mc_repetitions"], seed=SPEC["seed"])
    result["causal_inputs"] = {name: prefix[name].tolist() for name in ("dt", "tokens", "observed")}
    result["conditioning_scope"] = "Final true-model posterior from six causal development observations; fixed hypothetical future interval 0.45. No latent labels passed to the controller."
    return result


def main():
    torch.set_num_threads(1)
    torch.manual_seed(SPEC["seed"])
    output = HERE / "DEVELOPMENT_MECHANISMS.json"
    if output.exists():
        raise FileExistsError("Do not overwrite recorded development outcomes")
    sources = [ROOT / name for name in ("contract.py", "data.py", "inference.py", "evaluation.py",
                                       "control/controller.py", "PROTOCOL.json", "IMPLEMENTATION.json")]
    sources.extend([Path(__file__), HERE / "SPEC.json"])
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    model = true_model()
    projection = {name: projection_search(model, name) for name in ("factorized", "mean_compressed")}
    print(json.dumps({"stage": "projection", "max_regrets":
        {name: result["max_one_decision_regret"] for name, result in projection.items()}}), flush=True)
    episodes = episode_ablations(model)
    print(json.dumps({"stage": "episodes", "finance":
        {name: result["summary"]["utility_difference_from_full"] for name, result in episodes["finance"].items()}}), flush=True)
    monte_carlo = causal_monte_carlo(model)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != hashes[str(path.relative_to(ROOT))]
           for path in sources):
        raise RuntimeError("Sources changed during mechanism run; retain diagnostics and rerun a stable snapshot")
    payload = {"status": "development_mechanism_evidence", "specification": SPEC,
        "source_sha256": hashes, "formal_fit_or_confirmation_files_read": [],
        "model": {key: model[key].tolist() for key in ("theta", "grid", "prior", "Q", "emission", "answer_rewards", "read_cost")},
        "projections": projection, "episodes": episodes, "causal_monte_carlo": monte_carlo,
        "formal_gain_acceptance": False}
    output.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "actual_belief_mc_action_disagreement":
                     monte_carlo["action_disagreement_rate"]}), flush=True)


if __name__ == "__main__":
    main()
