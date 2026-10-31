"""Exact finite plan-probability gradients from frozen actual-output labels."""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from ..v6.data import Observation, Target
from ..v6.neural import PROFILES, parameter_hash
from ..v6.plan_training import finite_ndu_loss
from .data import VIEWS, make_batch
from .plans import ControlledSnapshot, PLANS, PlanHead
from .sources import canonical, digest


def fit_plan_head(base, corpus, labeler, training_profile, seed, directory, *, fit_pairs=512,
                  steps=400, scenarios=4, risk_aversion=2.):
    """Equal data/initialization/steps for mean-plan imitation and finite CE.

    The conditional scenarios are declared latent noise. They are not calibrated
    true-world events. Outcomes are detached quantized-output observations; only
    the content gate receives these exact finite-probability gradients.
    """
    if (training_profile not in PROFILES or fit_pairs < 2 or 2 * fit_pairs > len(corpus.splits["train"])
            or steps < 1 or scenarios < 2 or risk_aversion <= 0):
        raise ValueError("Invalid actual-output plan training registration")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    base.verify_integrity()
    labeler.verify_integrity()
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    count = fit_pairs * len(VIEWS)
    utilities = torch.empty(count, len(PLANS), scenarios, dtype=torch.float64)
    features = torch.empty(count, 96)
    cases = []
    event_digest = hashlib.sha256()
    batch_seed = int(seed) * 1000003 + 2789
    with (directory / "actual-output-labels.jsonl").open("w") as stream:
        for view_index, view in enumerate(VIEWS):
            batch = make_batch(corpus, "train", fit_pairs, batch_seed, view=view, offset=0)
            cases.extend({"pair": pair, "view": view, "source_ids": batch.source_ids[pair]}
                         for pair in range(fit_pairs))
            for start in range(0, fit_pairs, 64):
                stop = min(start + 64, fit_pairs)
                ids = torch.arange(view_index * fit_pairs + start, view_index * fit_pairs + stop)
                observation = Observation(*(value[start:stop] for value in
                                            (batch.observation.pixels, batch.observation.mask,
                                             batch.observation.text_tokens)))
                target = Target(*(value[start:stop] for value in
                                  (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                for scenario in range(scenarios):
                    noise_seed = seed * 1000033 + scenario * 104729 + start
                    initial = base.encode(observation, noise_seed=noise_seed)
                    context = base.state_features(initial)[:, -96:].detach().clone()
                    if scenario == 0:
                        features[ids] = context
                    elif not torch.equal(features[ids], context):
                        raise ValueError("Plan conditioning changed across latent-noise scenarios")
                    for plan_index, plan in enumerate(PLANS):
                        state = initial
                        for action in plan:
                            state = base.step(state, action)
                        observations = labeler.label(base, state, target)
                        utilities[ids, plan_index, scenario] = torch.tensor(
                            [item["utility"] for item in observations], dtype=torch.float64)
                        for row_index, observed in zip(ids.tolist(), observations):
                            raw = canonical({"case_index": row_index, "plan_index": plan_index,
                                             "scenario": scenario, "noise_seed": noise_seed,
                                             "utility": observed["utility"],
                                             "raw_sha256": observed["raw_sha256"]}) + b"\n"
                            event_digest.update(raw)
                            stream.write(raw.decode())
    enumeration_wall = time.perf_counter_ns() - start_wall
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed + 65537)
        gate = PlanHead()
    initial_gate = parameter_hash(gate)
    mean_best = utilities.mean(2).argmax(1)
    optimizer = torch.optim.Adam(gate.parameters(), lr=.005)
    rng = torch.Generator().manual_seed(seed + 131071)
    schedule, histories, gradient_max = hashlib.sha256(), [], 0.
    with torch.no_grad():
        initial_ce = -finite_ndu_loss(gate(features), utilities, risk_aversion).mean().item()
    for step in range(steps):
        ids = torch.randperm(count, generator=rng)[:128]
        logits = gate(features[ids])
        objective = (F.cross_entropy(logits, mean_best[ids]) if training_profile == "supervised" else
                     finite_ndu_loss(logits, utilities[ids], risk_aversion).mean())
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        gradient_max = max(gradient_max, sum(float(parameter.grad.abs().sum())
                                            for parameter in gate.parameters() if parameter.grad is not None))
        optimizer.step()
        schedule.update(ids.numpy().tobytes())
        histories.append(float(objective.detach()))
    with torch.no_grad():
        logits = gate(features)
        choices = logits.argmax(1)
        ce = -(torch.logsumexp(-risk_aversion * utilities, 2) - math.log(scenarios)) / risk_aversion
        mixture_ce = -finite_ndu_loss(logits, utilities, risk_aversion).mean().item()
        deployment_ce = ce[torch.arange(count), choices].mean().item()
    metadata = {"content_plan_training_profile": training_profile,
                "metric_contract": asdict(labeler.contract), "metric_contract_sha256": labeler.contract_sha256,
                "latent_scenarios": scenarios, "risk_aversion": risk_aversion}
    result = ControlledSnapshot(base, gate, metadata)
    evidence = {
        "schema": "hepta.ndu-v7.actual-output-plan-training.v1", "profile": training_profile,
        "seed": seed, "fit_pairs": fit_pairs, "views": VIEWS, "cases": count,
        "base_snapshot_sha256": base.fingerprint, "snapshot_sha256": result.fingerprint,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "source_case_sha256": digest(cases), "source_cases": cases,
        "metric_contract": asdict(labeler.contract), "metric_contract_sha256": labeler.contract_sha256,
        "initial_gate_sha256": initial_gate, "final_gate_sha256": result._gate_sha256,
        "optimizer_updates": steps, "schedule_sha256": schedule.hexdigest(),
        "gate_gradient_abs_sum_max": gradient_max, "objective_history": histories,
        "utility_table": utilities.tolist(), "scenarios": scenarios, "risk_aversion": risk_aversion,
        "initial_mixture_ce": initial_ce, "final_mixture_ce": mixture_ce,
        "deployment_argmax_ce": deployment_ce, "finite_empirical_oracle_ce": ce.max(1).values.mean().item(),
        "mean_risk_oracle_plan_disagreement": float((mean_best != ce.argmax(1)).float().mean()),
        "plan_selection_counts": torch.bincount(choices, minlength=len(PLANS)).tolist(),
        "actual_output_labels_file_sha256": event_digest.hexdigest(),
        "gradient_scope": "exact finite plan probabilities; actual-output utilities detached",
        "risk_scope": "registered empirical latent-noise scenarios, not calibrated world events",
        "argmax_deployment_equals_training_mixture": False,
        "reward_or_base_parameters_updated": False,
        "costs": {"encoder_examples": count * scenarios,
                  "action_examples": 2 * count * len(PLANS) * scenarios,
                  "decoded_scored_endpoints": count * len(PLANS) * scenarios,
                  "gate_training_examples": steps * min(128, count),
                  "enumeration_wall_ns": enumeration_wall,
                  "total_wall_ns": time.perf_counter_ns() - start_wall,
                  "total_cpu_ns": time.process_time_ns() - start_cpu},
    }
    base.verify_integrity()
    labeler.verify_integrity()
    (directory / "evidence.json").write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return result, evidence
