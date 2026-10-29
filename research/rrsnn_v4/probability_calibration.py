"""Check conditional marked-event/censoring probabilities of the finite CTMC.

This is a numerical consistency experiment on a separate development workload.
Outcomes come from the declared stochastic model, not biology or a production
future window. It cannot establish external predictive calibration.
"""

from pathlib import Path
import argparse
import gzip
import json

import numpy as np
import torch

from .evaluate import evaluate, load_policy, validate_selection
from .prepare_data import sha, write_once
from .run_evaluation import validated_selection
from .task import Oracle, make_scenario


ROOT = Path(__file__).resolve().parent
SEEDS = (101, 211, 307, 401, 503)
EPISODES = 128
SCENARIO_SEED = 88104001
ACTOR_SEED = 88105001
QUERY_SEED = 88106001
Z_SANITY_LIMIT = 4.0


class SurvivalProbe(torch.nn.Module):
    is_stochastic = True

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.records = []
        self.step_index = 0

    def initial_state(self, batch_size, rng):
        return self.model.initial_state(batch_size, rng)

    def step(self, state, observation, dt_elapsed, rng, event_mask=True,
             record_spikes=False):
        elapsed = np.broadcast_to(np.asarray(dt_elapsed, dtype=float), state.time.shape).copy()
        q, _ = self.model.operator.generator(state.drift.double(), state.boundary.double())
        killed = q.clone()
        top, refractory = self.model.operator.grid_size-1, self.model.operator.grid_size
        killed[..., top, refractory] = 0.0  # Keep the original diagonal: killing.
        transition = torch.matrix_exp(killed*torch.as_tensor(elapsed)[:, None, None, None])
        survival = transition.sum(-1).gather(-1, torch.from_numpy(state.indices)[..., None]).squeeze(-1)
        probabilities = 1.0-survival.detach().numpy()
        if probabilities.min() < -2e-12 or probabilities.max() > 1+2e-12:
            raise FloatingPointError("Invalid killed-chain probability")
        probabilities = np.clip(probabilities, 0., 1.)
        next_state, output = self.model.step(state, observation, dt_elapsed, rng,
                                           event_mask, record_spikes)
        interval_counts = (output["actual_counts"]-output["immediate_counts"]).numpy()
        if (interval_counts < 0).any():
            raise AssertionError("Observation remaps cannot exceed total pulse count")
        for row in np.flatnonzero(elapsed > 0):
            for unit in range(state.indices.shape[1]):
                self.records.append({"scenario": int(row), "step": self.step_index,
                    "unit": unit, "elapsed": float(elapsed[row]),
                    "starting_state": int(state.indices[row, unit]),
                    "event_probability": float(probabilities[row, unit]),
                    "observed_any_interval_spike": int(interval_counts[row, unit] > 0),
                    "interval_spikes": int(interval_counts[row, unit])})
        self.step_index += 1
        return next_state, output


def summarize(records):
    if not records:
        raise ValueError("Calibration summary requires at least one prediction")
    p = np.asarray([r["event_probability"] for r in records])
    y = np.asarray([r["observed_any_interval_spike"] for r in records])
    if not np.isfinite(p).all() or not ((0 <= p) & (p <= 1)).all():
        raise ValueError("Calibration probabilities must be finite and in [0, 1]")
    if not np.isfinite(y).all() or not np.isin(y, (0, 1)).all():
        raise ValueError("Calibration observations must be binary")
    contradictions = int((((p == 0) & (y == 1)) | ((p == 1) & (y == 0))).sum())
    variance = float(np.sum(p*(1-p)))
    residual_sum = float(np.sum(y-p))
    z = float(residual_sum/np.sqrt(variance)) if variance else (None if contradictions else 0.)
    bins = []
    for index in range(10):
        keep = (p >= index/10) & ((p < (index+1)/10) if index < 9 else (p <= 1))
        if keep.any():
            bins.append({"lower": index/10, "upper": (index+1)/10,
                         "n": int(keep.sum()), "predicted_mean": float(p[keep].mean()),
                         "observed_frequency": float(y[keep].mean())})
    return {"interval_unit_predictions": len(records), "observed_events": int(y.sum()),
            "predicted_events": float(p.sum()), "mean_probability": float(p.mean()),
            "observed_frequency": float(y.mean()), "brier": float(np.mean((y-p)**2)),
            "expected_brier_under_declared_model": float(np.mean(p*(1-p))),
            "ece_10_equal_width_bins": float(sum(b["n"]*abs(b["predicted_mean"]-b["observed_frequency"]) for b in bins)/len(records)),
            "no_spike_right_censored_intervals": int((y == 0).sum()),
            "martingale_residual_standardized": z, "predictable_variance_sum": variance,
            "deterministic_probability_contradictions": contradictions,
            "predeclared_4sigma_sanity_passed": bool(not contradictions and z is not None and abs(z) <= Z_SANITY_LIMIT), "bins": bins}


def run(freeze_path, selection_path, publication_receipt):
    _, selected, _, publication = validated_selection(freeze_path, selection_path, publication_receipt)
    design_path = ROOT/"probability_calibration_design.json"
    design = json.loads(design_path.read_text())
    if design["source_sha256"] != sha(__file__) or design["scenario_seed"] != SCENARIO_SEED:
        raise ValueError("Calibration source/design changed after registration")
    torch.set_num_threads(1)
    rng = np.random.default_rng(SCENARIO_SEED)
    scenarios = [make_scenario(rng, split="train") for _ in range(EPISODES)]
    oracle = [Oracle(s).value(0, s.initial_live, s.budget) for s in scenarios]
    destination = ROOT/"results/probability_calibration"
    destination.mkdir(exist_ok=True)
    outputs, all_records = [], []
    with torch.no_grad():
        for seed in SEEDS:
            checkpoint = selected["rr_full"][seed]
            selection = validate_selection(checkpoint, selection_path, freeze_path)
            model, _ = load_policy(checkpoint, selection["training_protocol_sha256"])
            probe = SurvivalProbe(model)
            actor = evaluate(probe, scenarios, oracle_values=oracle, dataset="development",
                             training_seed=seed, latent_replay=0, latent_seed=ACTOR_SEED+seed,
                             query_seed_base=QUERY_SEED)
            if not actor["all_resource_invariants_passed"]:
                raise AssertionError("Calibration development path violates the task ledger")
            records = [{"training_seed": seed, **r} for r in probe.records]
            row = {"seed": seed, "checkpoint_sha256": sha(checkpoint), "summary": summarize(records)}
            path = destination/f"seed_{seed}.json.gz"
            payload = {"identity": {**publication, "source_sha256": sha(__file__),
                       "design_sha256": sha(design_path), "checkpoint_sha256": sha(checkpoint)},
                       "summary": row, "records": records}
            raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
            write_once(path, gzip.compress(raw, mtime=0))
            outputs.append({**row, "path": str(path.relative_to(ROOT)), "sha256": sha(path)})
            all_records.extend(records)
            print(json.dumps(row), flush=True)
    pooled = summarize(all_records)
    result = {"schema": "rrsnn.v4-conditional-event-calibration.1", "design_sha256": sha(design_path),
              "source_sha256": sha(__file__), "per_seed": outputs, "pooled": pooled,
              "all_predeclared_sanity_checks_passed": pooled["predeclared_4sigma_sanity_passed"] and all(r["summary"]["predeclared_4sigma_sanity_passed"] for r in outputs),
              "formula": "P(no marked top-to-refractory event before dt | current finite state) = e_i exp(Q_killed dt) 1; delete only the marked off-diagonal rate, retain original exit diagonal.",
              "observation_remap_spikes_excluded_from_interval_target": True,
              "right_censoring_included": True, "weights_changed": False,
              "scope": "Finite-model numerical consistency under its own generated outcomes; separate development workload, no heldout task-score reuse.",
              "qualification": "Standardized residual uses predictable Bernoulli variance for a conditional martingale sanity diagnostic, not an exact finite-sample normal test. ECE uses ten fixed bins. This is not independent real-world predictive or biological calibration.",
              "external_predictive_calibration_established": False, "activation_allowed": False}
    write_once(destination/"summary.json", (json.dumps(result, indent=2, allow_nan=False)+"\n").encode())
    return result


def validate_development():
    from .models import make_policy
    torch.set_num_threads(1)
    rejected = 0
    for invalid in ([], [{"event_probability": float("nan"), "observed_any_interval_spike": 0}],
                    [{"event_probability": -0.1, "observed_any_interval_spike": 0}],
                    [{"event_probability": 0.5, "observed_any_interval_spike": 2}]):
        try:
            summarize(invalid)
        except ValueError:
            rejected += 1
    assert rejected == 4
    contradiction = summarize([{"event_probability": 0., "observed_any_interval_spike": 1},
                               {"event_probability": 1., "observed_any_interval_spike": 0}])
    assert contradiction["deterministic_probability_contradictions"] == 2
    assert contradiction["martingale_residual_standardized"] is None
    assert not contradiction["predeclared_4sigma_sanity_passed"]
    deterministic = summarize([{"event_probability": 0., "observed_any_interval_spike": 0},
                               {"event_probability": 1., "observed_any_interval_spike": 1}])
    assert deterministic["predeclared_4sigma_sanity_passed"]
    time = torch.linspace(0., 2., 21, dtype=torch.float64)
    killed = torch.tensor([[-2., 0.], [3., -3.]], dtype=torch.float64)
    calculated = torch.matrix_exp(killed[None, :, :]*time[:, None, None]).sum(-1)
    expected = torch.stack((torch.exp(-2*time), 3*torch.exp(-2*time)-2*torch.exp(-3*time)), -1)
    error = float((calculated-expected).abs().max())
    assert error < 1e-12
    rng = np.random.default_rng(901990)
    scenarios = [make_scenario(rng) for _ in range(4)]
    oracle = [Oracle(s).value(0, s.initial_live, s.budget) for s in scenarios]
    torch.manual_seed(901991)
    model = make_policy("rr_full")
    probe = SurvivalProbe(model)
    with torch.no_grad():
        observed = evaluate(probe, scenarios, oracle_values=oracle, dataset="development",
                            training_seed=0, latent_seed=901992, query_seed_base=901993)
        reference = evaluate(model, scenarios, oracle_values=oracle, dataset="development",
                             training_seed=0, latent_seed=901992, query_seed_base=901993)
    assert observed["rows"] == reference["rows"]
    result = {"schema": "rrsnn.v4-calibration-probe-development.1", "all_passed": True,
              "two_state_closed_form_including_refractory_start_max_error": error,
              "invalid_input_rejections": rejected,
              "deterministic_contradictions_rejected_even_when_residuals_cancel": True,
              "correct_deterministic_predictions_accepted": True,
              "numerical_probe_does_not_change_actor": True, "development_episodes": 4,
              "production_checkpoint_opened": False, "summary": summarize(probe.records),
              "source_sha256": sha(__file__)}
    (ROOT/"probability_calibration_validation.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--publication-receipt", type=Path)
    parser.add_argument("--validate-development", action="store_true")
    args = parser.parse_args()
    if args.validate_development:
        print(json.dumps(validate_development()))
    elif args.freeze and args.selection and args.publication_receipt:
        run(args.freeze, args.selection, args.publication_receipt)
    else:
        parser.error("Provide all three identity arguments or --validate-development")
