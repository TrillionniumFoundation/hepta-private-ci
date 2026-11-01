"""Numerical action-gap checks against a declared, finite finer reference.

The independent scenario grid was fixed before this script ran. It probes the
physical operator with R12's fixed seven-symbol emission, without SMS outcomes.
Computed fine-grid differences are not continuous-diffusion error bounds.
"""

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import contract
from controller import plan
from propagation.api import generator_numpy, make_grid
from propagation.bounds import action_certificate
from propagation.finite_volume import reset_numpy


def model_at_step(step, edges=None):
    theta = np.array(contract.PROTOCOL["baseline_financial_parameters"])
    edges = make_grid(inner_step=step) if edges is None else np.asarray(edges)
    boundary = contract.BRIDGE.HX.evaluate(theta, .2, coordinate="log_distance", mode="float64")[0][0]
    center = (edges[:-1]+edges[1:])/2
    model = generator_numpy(theta[2], theta[0]-theta[1]-theta[2]**2/2,
                            np.log(90/boundary), edges)
    outputs = np.array([contract.BRIDGE.HX.evaluate(theta, x,
                        coordinate="log_distance", mode="float64")[0] for x in center])
    n = len(center)
    equity = np.r_[outputs[:, 1], 0., 0.]
    bonus = .05*equity/(theta[8]+equity)
    rewards = np.tile(bonus, 2)[:, None]*np.ones((1, 2))
    rewards[:n+2, 0] += 1
    rewards[n+2:, 1] += 1
    cost = np.r_[.03+.03*np.maximum(theta[8]/theta[6]-outputs[:, 4], 0)/(theta[8]/theta[6]), .06, .06]
    return dict(**model, emission=contract.BRIDGE.emission_matrix(n_active=n).numpy(),
                answer_rewards=rewards, read_cost=np.tile(cost, 2))


def beliefs_for(model, contexts):
    rows = []
    for c in contexts:
        phase = np.r_[reset_numpy(c["mean"], c["width"], model["edges"]), 0., 0.]
        rows.append(np.r_[c["p0"]*phase, (1-c["p0"])*phase])
    return np.array(rows)


def compute(model, contexts, dt, cfg):
    return plan(beliefs_for(model, contexts), expm(dt*model["Q"]), model["emission"],
        model["answer_rewards"], model["read_cost"], horizon=cfg["horizon"],
        budget=cfg["budget"], time_cost=cfg["time_cost"], dt=dt)


def main():
    started = time.perf_counter()
    protocol = json.loads((ROOT/"VALIDATION_PROTOCOL.json").read_text())
    cfg = protocol["action_validation"]
    models = {step: model_at_step(step) for step in cfg["near_steps"]+[cfg["finite_reference_near_step"]]}
    contexts = [dict(mean=m, width=w, p0=p) for m in cfg["independent_initial_means"]
                for w in cfg["independent_initial_widths"]
                for p in cfg["independent_bit0_probabilities"]]
    witness = cfg["inherited_witness"]
    witness_context = dict(mean=witness["mean"], width=witness["width"], p0=witness["p_bit0"])
    records = []
    for dt in cfg["independent_dt"]+[witness["dt"]]:
        cc = contexts if dt != witness["dt"] else [witness_context]
        result = {step: compute(model, cc, dt, cfg) for step, model in models.items()}
        reference = result[cfg["finite_reference_near_step"]]
        for index, context in enumerate(cc):
            finer_q = reference.qvalues[index]
            per_grid = []
            first_accepted_step = None
            for step in cfg["near_steps"]:
                q = result[step].qvalues[index]
                observed_error = float(abs(q-finer_q).max())
                # This budget concerns the computed finite reference vector.
                finite_check = action_certificate(q,
                    {"difference_from_computed_finite_reference": observed_error},
                    tolerance=contract.PROTOCOL["tie_tolerance"])
                if finite_check["action_certified"] and first_accepted_step is None:
                    first_accepted_step = step
                continuum_check = action_certificate(q,
                    {"fv_spatial_value_error": None, "floating_arithmetic_value_error": None},
                    tolerance=contract.PROTOCOL["tie_tolerance"])
                action = int(result[step].action[index])
                per_grid.append(dict(near_step=step, n_active=len(models[step]["edges"])-1,
                    action=action, qvalues=q.tolist(), finite_reference_action=int(reference.action[index]),
                    computed_reference_action_regret=float(finer_q.max()-finer_q[action]),
                    finite_reference_gap_check=finite_check, continuum_gap_check=continuum_check))
            records.append(dict(**context, dt=dt, inherited_witness=dt == witness["dt"],
                finite_reference_n_active=len(models[cfg["finite_reference_near_step"]]["edges"])-1,
                finite_reference_qvalues=finer_q.tolist(),
                first_accepted_near_step_for_computed_finite_reference=first_accepted_step,
                per_grid=per_grid))
    inherited = []
    for n in (8, 64):
        old = contract.BRIDGE.true_model(n)
        old["edges"] = np.linspace(0, .8, n+1)
        r = compute(old, [witness_context], witness["dt"], cfg)
        inherited.append(dict(n_active=n, action=int(r.action[0]), qvalues=r.qvalues[0].tolist()))
    summaries = []
    independent = [r for r in records if not r["inherited_witness"]]
    for step in cfg["near_steps"]:
        part = [g for r in independent for g in r["per_grid"] if g["near_step"] == step]
        summaries.append(dict(near_step=step, contexts=len(part),
            disagreements=sum(g["action"] != g["finite_reference_action"] for g in part),
            maximum_computed_reference_regret=max(g["computed_reference_action_regret"] for g in part),
            maximum_computed_reference_q_difference=max(g["finite_reference_gap_check"]["value_error"] for g in part),
            accepted_against_computed_reference=sum(g["finite_reference_gap_check"]["action_certified"] for g in part),
            continuum_certificates=sum(g["continuum_gap_check"]["action_certified"] for g in part)))
    payload = dict(rows=records, summary=summaries, inherited_R12_witness=inherited,
        runtime_model_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                              for name in protocol["frozen_model_files"]},
        controller_sha256=hashlib.sha256((ROOT.parent/"controller.py").read_bytes()).hexdigest(),
        protocol_sha256=hashlib.sha256((ROOT/"VALIDATION_PROTOCOL.json").read_bytes()).hexdigest(),
        wall_seconds=time.perf_counter()-started,
        scope="Finite computed reference h=.00625 and expanded domain; Q-gap inequalities apply to those numerical vectors. Numerical comparisons are not a proved continuum FV bound, and all continuum certificates are explicitly withheld. This is an operator validation, not confirmation efficacy or SMS generalization.")
    path = ROOT/"ACTIONS.json"
    if path.exists():
        raise ValueError("Evidence is append-only")
    path.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"summary": summaries, "inherited_R12_witness": inherited,
                      "wall_seconds": payload["wall_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
