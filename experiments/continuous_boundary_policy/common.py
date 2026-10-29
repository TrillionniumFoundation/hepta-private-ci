"""Fixed supplemental protocol, identities, and non-overlapping cost clocks."""

from pathlib import Path
import resource
import time

from experiments.continuous_boundary_flow.common import canonical, save_json, sha

PACKAGE = Path(__file__).resolve().parent
PRIOR_COMMIT = "7bec42aa4f79432f4a724d5295c67f9d69ee5a8d"
SEEDS = [2203, 2207, 2213, 2221, 2237, 2239, 2243, 2251]
ARMS = [
    "fixed_margin",
    "learned_margin",
    "value_margin",
    "value_call",
    "dual_flow",
    "generic_gru",
    "dual_event",
    "elman_mlp",
    "native_sparse",
]
CONTROLS = ["dp", "always_keep", "always_repair", "always_stop"]
CANDIDATES = [
    {"learning_rate": 0.005, "fixed_boundary": 0.25, "native_ridge": 0.001},
    {"learning_rate": 0.02, "fixed_boundary": 0.65, "native_ridge": 0.01},
    {"learning_rate": 0.05, "fixed_boundary": 1.05, "native_ridge": 0.1},
]
PAIRS = [
    {"name": "boundary", "treatment": "value_margin", "control": "learned_margin"},
    {"name": "dual_channels", "treatment": "dual_flow", "control": "value_call"},
    {"name": "signed_structure", "treatment": "dual_flow", "control": "generic_gru"},
    {"name": "flow", "treatment": "dual_flow", "control": "dual_event"},
]
FEATURE_NAMES = [
    "x_scaled",
    "remaining_windows_scaled",
    "mu_scaled",
    "sigma_scaled",
    "maintenance_cost",
    "failure_cost_scaled",
    "production_scaled",
    "discount_scaled",
    "maintenance_reset_scaled",
    "failure_reset_scaled",
    "window_dt",
    "margin",
    "call",
    "put",
    "current_wait_risk",
    "previous_action_flow",
    "previous_failed",
    "previous_repair",
]
OBJECTIVE = sha(b"finite-window-production-minus-discounted-failure-maintenance.v1")


class CostMeter:
    """Separate monotone user/system child deltas avoid a+b-a-b cancellation."""

    def __init__(self):
        self.start_wall = time.perf_counter()
        self.start_cpu = time.process_time()
        self.child = resource.getrusage(resource.RUSAGE_CHILDREN)

    def finish(self):
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        user = child.ru_utime - self.child.ru_utime
        system = child.ru_stime - self.child.ru_stime
        if user < 0 or system < 0:
            raise ValueError("Nonmonotone child CPU clock")
        return {
            "wall_seconds": time.perf_counter() - self.start_wall,
            "python_cpu_seconds": time.process_time() - self.start_cpu,
            "completed_child_cpu_seconds": user + system,
            "child_cpu_scope": "only children reaped inside this window",
        }


def kind_for(arm):
    return "gru" if arm == "generic_gru" else "elman" if arm == "elman_mlp" else "dual"


def protocol():
    return {
        "schema": "hepta.continuous-boundary-policy.protocol.v1",
        "prior_commit": PRIOR_COMMIT,
        "prior_result": "study-002 remains 0/3 benefit gates; no pooling or reinterpretation",
        "seeds": SEEDS,
        "arms": ARMS + CONTROLS,
        "primary_pairs": PAIRS,
        "train_contexts": 12,
        "train_paths": 8,
        "development_contexts": 8,
        "development_paths": 8,
        "confirmation_contexts_per_split": 8,
        "confirmation_paths": 16,
        "splits": ["test_id", "test_ood"],
        "split_weights": [0.5, 0.5],
        "grid_states": 64,
        "grid_upper": 4.8,
        "features": FEATURE_NAMES,
        "input_width": 18,
        "persistent_continuous_state": 6,
        "continuous_trainable_scalars": 464,
        "direct_boundary_extra_scalars": 20,
        "masked_parameter_scope": "464 allocated; masked current-channel input columns intentionally have no gradient; strict live-count match concerns full-information dual/GRU/Elman",
        "generic_match": "same 464 live parameters, fixed sign arrays, inputs, state size, initial effective GRU weights, optimizer, epochs and candidates; only dual sign projection differs",
        "elman": "fully trained 6-state Elman plus bias-free 24x12 tanh readout and 12x2+bias head; 464 scalars",
        "native_sparse": "unchanged original native width20 top-k4 kernel; 420 frozen encoder and 42 fitted head coefficients; common18 information with two explicit duplicate channels; unmatched training capacity reference",
        "training": "full-sequence NumPy BPTT; cross-entropy plus expected action regret/(1+maximum action regret); common exploratory DP teacher",
        "epochs": 120,
        "adam_gradient_clip": 5.0,
        "parameter_abs_bound": 8.0,
        "score_map": "keep/repair=8*tanh(linear/8); stop=0; Q24 native NDU decides",
        "candidates": CANDIDATES,
        "selection": "maximum actual-native development mean net utility; smallest candidate index breaks ties",
        "reset": "dual and ordinary GRU use previous action risk as reset fraction; dual_event uses previous observed failure; Elman learns its recurrence without forced reset",
        "channel_masks": "margin arms hide current C,P,F; value_call hides P,F; all arms see prior action flow, failure, repair and same public context",
        "deadline": "remaining windows/16 and public dt; no initial-horizon normalization",
        "familywise_alpha": 0.05,
        "minimum_effect": 0.005,
        "primary_sample_unit": "8 independent training/environment seeds; 4 Bonferroni-corrected paired t intervals",
        "message_price_per_byte": 1e-6,
        "message_scope": "actual numeric cross-process decision input: 3 i64 scores=24 bytes for continuous policies; 20 i64 features=160 for native sparse; full JSON framing separately measured",
        "cpu_price": None,
        "energy_measurement": None,
        "child_cpu_clock_tolerance_seconds": 5e-6,
        "native_execution": "continuous policies use original NDU only, without sparse kernel; native_sparse uses original kernel and NDU; neither uses Python-selected actions",
        "risk_scope": "same analytic current-window after-action first-hit predictor; visitation calibration, not learned risk superiority",
        "authority": "research only; DENY_ALL; no production admission",
        "failure_policy": "abort and preserve incomplete evidence; no sample exclusion, resampling, seed extension or test-based changes",
    }


def append_cost(output, row):
    with (Path(output) / "costs.jsonl").open("ab") as stream:
        stream.write(canonical(row) + b"\n")
