"""Frozen-source confirmation; paired seeds, causal reads and complete cost logs."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from contract import PROTOCOL
from contract import ROOT
from contract import true_model
from control.controller import plan
from data import EvidenceWorld
from data import sequences
from inference import Estimator
from inference import sequence_predictions
from training import digest_data


def validate_freeze(folder):
    payload = json.loads((folder / "FREEZE.json").read_text())
    for name, expected in payload["source_sha256"].items():
        path = ROOT.parent / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source changed after freeze: {path}")
    for name, expected in payload["fit_sha256"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Fit changed after freeze: {name}")
    if "native_library_sha256" in payload:
        binary = ROOT / "native/evidence/build/libhcsn_native.so"
        if hashlib.sha256(binary.read_bytes()).hexdigest() != payload["native_library_sha256"]:
            raise ValueError("Native library changed after freeze")
    return payload


def episode_run(core, control, checkpoint, shared, world, times):
    start, wall_start = time.process_time(), time.perf_counter()
    world.reset()
    count = world.count
    state = Estimator(core, count, shared, times, checkpoint)
    initialize_cpu = time.process_time() - start
    active = np.ones(count, dtype=bool)
    budget = np.full(count, PROTOCOL["read_budget"])
    utility, correct = np.zeros(count), np.zeros(count)
    history = np.full((count, 3), -1, dtype=int)
    acquired = np.full((count, 3), -1, dtype=int)
    latent_at_answer = np.full(count, -1, dtype=int)
    timing = {"initialization": initialize_cpu, "controller": 0.0,
              "state_update": 0.0, "world_read_and_recovery": 0.0,
              "answer_scoring": 0.0}
    for step in range(3):
        rows = np.flatnonzero(active)
        if not len(rows):
            break
        actions = np.full(count, -1, dtype=int)
        tick = time.process_time()
        if control == "fixed_read":
            actions[rows] = 3 if step < 2 else np.argmax(
                state.p[rows] @ shared["answer_rewards"], axis=1)
        else:
            for j, dt in enumerate(times):
                for remaining in range(3):
                    selected = rows[(world.dt_indices[step, rows] == j) &
                                    (budget[rows] == remaining)]
                    if not len(selected):
                        continue
                    actions[selected] = plan(
                        state.p[selected], state.transitions[j], shared["emission"],
                        shared["answer_rewards"], shared["read_cost"],
                        horizon=3-step, budget=remaining, dt=dt,
                    ).action
        timing["controller"] += time.process_time() - tick
        history[rows, step] = actions[rows]
        terminal = rows[actions[rows] < 2]
        tick = time.process_time()
        reward, accuracy = world.answer(terminal, actions[terminal])
        utility[terminal] += reward
        correct[terminal] = accuracy
        latent_at_answer[terminal] = world.hidden[terminal]
        active[terminal] = False
        timing["answer_scoring"] += time.process_time() - tick
        advance = rows[actions[rows] >= 2]
        if not len(advance):
            continue
        tick = time.process_time()
        world.advance(step, advance)
        dt_indices = world.dt_indices[step, advance]
        utility[advance] -= 0.01 * np.asarray(times)[dt_indices]
        read = advance[actions[advance] == 3]
        tokens = np.zeros(count, dtype=int)
        observed = np.zeros(count, dtype=bool)
        tokens[read] = world.read(step, read)
        observed[read] = True
        acquired[read, step] = tokens[read]
        utility[read] -= world.model["read_cost"][world.hidden[read]]
        budget[read] -= 1
        timing["world_read_and_recovery"] += time.process_time() - tick
        tick = time.process_time()
        for j, dt in enumerate(times):
            selected = advance[dt_indices == j]
            if len(selected):
                state.update(selected, j, dt, tokens[selected], observed[selected])
        timing["state_update"] += time.process_time() - tick
    cpu = time.process_time() - start
    if active.any() or np.any(budget < 0):
        raise AssertionError("Incomplete episode or budget violation")
    if world.read_calls != np.sum(history == 3) or np.any((acquired >= 0) != (history == 3)):
        raise AssertionError("Unrequested payload access")
    return {
        "core": core, "control": control, "utility": utility.tolist(),
        "accuracy": correct.tolist(), "mean_utility": float(utility.mean()),
        "mean_accuracy": float(correct.mean()), "actions": history.tolist(),
        "acquired_tokens": acquired.tolist(), "latent_at_answer_for_scoring_only": latent_at_answer.tolist(),
        "read_calls": world.read_calls, "advance_calls": world.advance_calls,
        "recovery_read_calls": world.recovery_read_calls,
        "inference_cpu_seconds": cpu, "inference_wall_seconds": time.perf_counter()-wall_start,
        "cpu_components": timing,
        "native_parity_scope": "Checked independently in native/evidence/contract_01; no duplicate debug propagation is charged as inference.",
    }


def sequence_score(predicted, data):
    content = predicted.reshape(*predicted.shape[:-1], 2, -1).sum(-1)
    accuracy = (content.argmax(-1) == data["labels"]).mean(axis=1)
    ce = -(data["posterior"] * np.log(np.maximum(predicted, 1e-12))).sum(-1).mean(axis=1)
    marginal = data["posterior"].reshape(*predicted.shape[:-1], 2, -1).sum(-1)
    brier = ((content - marginal) ** 2).sum(-1).mean(axis=1)
    return {"accuracy": accuracy.tolist(), "posterior_ce": ce.tolist(),
            "posterior_content_brier": brier.tolist(),
            "mean_accuracy": float(accuracy.mean()), "mean_posterior_ce": float(ce.mean()),
            "mean_posterior_content_brier": float(brier.mean())}


def confirm(folder, development=False):
    torch.set_num_threads(1)
    frozen = None if development else validate_freeze(folder)
    seeds = [PROTOCOL["development_seed"]] if development else PROTOCOL["seeds"]
    output = folder / ("DEVELOPMENT_EVALUATION.json" if development else "CONFIRMATION.json")
    if output.exists():
        raise FileExistsError("Never overwrite outcomes")
    all_results = []
    true = true_model()
    for seed in seeds:
        fits = {name: json.loads((folder / "fits" / f"{seed}_{name}.json").read_text())
                for name in PROTOCOL["cores"]}
        chosen = min(PROTOCOL["cores"][1:], key=lambda n: fits[n]["selected_validation"]["posterior_ce"])
        if frozen is not None and frozen["ordinary_choices"][str(seed)] != chosen:
            raise AssertionError("Post-confirmation selection")
        shared = {k: np.asarray(v) for k, v in fits["hx_distribution"]["shared_model"].items()}
        for domain, times in [("iid", PROTOCOL["iid_dt"]), ("ood", PROTOCOL["ood_dt"])]:
            data_seed = seed + (400000 if domain == "iid" else 500000)
            data = sequences(data_seed, PROTOCOL["confirmation_sequences_per_domain"],
                             true, times, PROTOCOL["sequence_length"])
            world = EvidenceWorld(data_seed+1000000, PROTOCOL["confirmation_episodes_per_domain"], true, times)
            row = {"seed": seed, "domain": domain, "ordinary_choice": chosen,
                   "sequence_data_sha256": digest_data(data), "sequence": {}, "arms": {},
                   "fits": {n: {k: p[k] for k in ["fit_cpu_seconds", "preparation_cpu_seconds",
                              "parameter_count", "selected_update"]} for n, p in fits.items()}}
            predictions = {}
            for core in [*PROTOCOL["cores"], "generic_hmm", "true_bayes"]:
                checkpoint = folder / "fits" / f"{seed}_{core}.json"
                parameters = true if core == "true_bayes" else shared
                tick = time.process_time()
                prediction = sequence_predictions(core, data, parameters, times, checkpoint)
                predictions[core] = prediction
                row["sequence"][core] = {**sequence_score(prediction, data),
                                         "cpu_seconds": time.process_time()-tick}
            row["generic_hmm_torch_parity_max"] = float(np.max(np.abs(
                predictions["hx_distribution"] - predictions["generic_hmm"])))
            # Paired A/B/C/D plus both unreduced ordinary cores, same planner.
            definitions = {"A": (chosen, "fixed_read"), "B": (chosen, "finite_horizon_value"),
                           "C": ("hx_distribution", "fixed_read"),
                           "D": ("hx_distribution", "finite_horizon_value"),
                           "GRU": ("gru", "finite_horizon_value"),
                           "SSM": ("continuous_diagonal_ssm", "finite_horizon_value"),
                           "HMM": ("generic_hmm", "finite_horizon_value"),
                           "ORACLE": ("true_bayes", "finite_horizon_value")}
            # Alternate timing order by fit to reduce a systematic warm-cache bias.
            ordered = list(definitions)
            if seed % 4 == 1:
                ordered.reverse()
            for arm in ordered:
                core, controller = definitions[arm]
                parameters = true if core == "true_bayes" else shared
                checkpoint = folder / "fits" / f"{seed}_{core}.json"
                result = episode_run(core, controller, checkpoint, parameters, world, times)
                owner = core if core in fits else "hx_distribution"
                own_fit = fits[owner]["fit_cpu_seconds"] + fits[owner]["preparation_cpu_seconds"]
                calibration = (fits["hx_distribution"]["fit_cpu_seconds"]
                               + fits["hx_distribution"]["preparation_cpu_seconds"])
                if core == "true_bayes":
                    own_fit, calibration = 0.0, 0.0
                fit_cost = own_fit + (calibration if core in PROTOCOL["cores"][1:] else 0.0)
                result["encoder_fit_cpu_seconds"] = own_fit
                result["shared_controller_calibration_cpu_seconds"] = calibration
                result["calibration_fit_reused_by_encoder"] = core not in PROTOCOL["cores"][1:]
                result["fit_and_preparation_cpu_seconds"] = fit_cost
                result["amortized_cpu_per_episode"] = (
                    result["inference_cpu_seconds"] / world.count
                    + fit_cost / PROTOCOL["training_amortization_episodes"])
                result["equal_shared_charge_cpu_per_episode"] = (
                    result["inference_cpu_seconds"] / world.count
                    + (own_fit + calibration) / PROTOCOL["training_amortization_episodes"])
                result["cost_scope"] = ("Measured CPU includes causal actor/planner/reads/world and fitted-model preparation; "
                                        "shared-model calibration also disclosed separately. No production/GPU claim.")
                row["arms"][arm] = result
            all_results.append(row)
            print(json.dumps({"seed": seed, "domain": domain, "choice": chosen,
                              "D_minus_B": row["arms"]["D"]["mean_utility"]-row["arms"]["B"]["mean_utility"],
                              "parity": row["generic_hmm_torch_parity_max"]}), flush=True)
    payload = {"schema": "hcsn-r12-confirmation-v1", "development": development,
               "freeze_sha256": None if frozen is None else hashlib.sha256((folder/"FREEZE.json").read_bytes()).hexdigest(),
               "results": all_results}
    output.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=ROOT / "evidence")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    print(confirm(args.folder, args.development))
