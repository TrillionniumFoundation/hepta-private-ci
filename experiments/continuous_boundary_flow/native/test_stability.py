"""Bounded engineering stress for the unchanged native continuous-flow host.

Eight independent engineering cases run for the supported maximum of 512 ticks
(total 4096 primary ticks). These deterministic fixture streams are not new
scientific samples. A separate 4096-kernel reference replay is fully charged.
This checks finite-domain numeric stability, not unlimited-horizon stability.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from .adapter import NativeBridge, Q, digest, make_profile, save_profile

MASK64 = (1 << 64) - 1
ENGINEERING_STREAM = 0x6A09E667F3BCC909


class SplitMix64:
    """Explicit integer generator so fixture bytes do not depend on a library RNG."""

    def __init__(self, state):
        self.state = state

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
        return value ^ (value >> 31)

    def bounded(self, low, high):
        return low + self.next() % (high - low + 1)


def fixture():
    generator = SplitMix64(ENGINEERING_STREAM)
    profile = make_profile(
        [f"fixture_{i}" for i in range(17)],
        [[0.0] * 20 for _ in range(20)],
        [0.0] * 20,
        [[0.0] * 20 for _ in range(3)],
        [0.0] * 3,
        source_model_digest=digest("bounded-engineering-stability-fixture-v1"),
        objective_digest=digest("engineering-state-stability-not-task-efficacy"),
        arm_id="engineering-stability",
        stage="transform",
        maximum_ticks=512,
    )
    profile["encoder_weights_q24"] = [
        [generator.bounded(-Q // 2, Q // 2) for _ in range(20)] for _ in range(20)
    ]
    profile["head_weights_q24"] = [
        [generator.bounded(-Q, Q) for _ in range(20)] for _ in range(2)
    ] + [[0] * 20]
    sequences = []
    for case in range(8):
        sequence = []
        for tick in range(512):
            raw = [generator.bounded(-8 * Q, 8 * Q) for _ in range(17)]
            if tick % 64 == 0:
                raw[case % 17] = 8 * Q if case % 2 == 0 else -8 * Q
            sequence.append(
                {
                    "raw_q24": raw,
                    "continuous": {
                        "margin_q24": generator.bounded(-8 * Q, 8 * Q),
                        "risk_q24": generator.bounded(0, Q),
                        "flow_q24": generator.bounded(-8 * Q, 8 * Q),
                    },
                }
            )
        sequences.append(sequence)
    return profile, sequences


def run(binary, output_dir, run_dir):
    output_dir.mkdir(parents=True, exist_ok=False)
    profile, sequences = fixture()
    profile_path, profile_sha = save_profile(output_dir, profile)
    samples_path = output_dir / "stability_samples_v1.jsonl"
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    adapter_sha = hashlib.sha256(
        Path(__file__).with_name("adapter.py").read_bytes()
    ).hexdigest()
    primary_input_sha = digest(sequences)
    checks = 0

    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    started = time.perf_counter()
    bridge = NativeBridge(binary, run_dir, expected_binary_sha256=binary_sha)
    summary = {
        "schema": "hepta.continuous-boundary.engineering-stability.v1",
        "scope": "bounded native numerical fixture, not scientific efficacy or infinite-horizon stability",
        "case_count": 8,
        "ticks_per_case": 512,
        "primary_ticks": 4096,
        "reference_replay_ticks": 4096,
        "longest_uninterrupted_case_ticks": 512,
        "report_every_ticks_per_case": 64,
        "durable_owner_execution": False,
        "stage": "transform",
        "native_recommendations_do_not_end_transform_fixture": True,
        "scientific_samples_added": 0,
        "fixture_stream_algorithm": "SplitMix64-explicit-integer-v1",
        "engineering_stream_initial_state_hex": hex(ENGINEERING_STREAM),
        "binary_sha256": binary_sha,
        "script_sha256": source_sha,
        "adapter_sha256": adapter_sha,
        "profile_sha256": profile_sha,
        "profile_file": profile_path.name,
        "input_stream_sha256": primary_input_sha,
        "windows": [],
        "success": False,
    }
    error = None
    try:
        bridge.load_profile(profile_path)
        reference = bridge.kernel_batch(profile_sha, sequences)
        require(
            reference["actual_kernel_calls"] == 4096, "Reference kernel count mismatch"
        )
        cases = [f"engineering.{i}" for i in range(8)]
        bridge.kernel_reset(profile_sha, cases)
        previous = ["0" * 64 for _ in cases]
        projections = 0
        activation_min, activation_max = 8 * Q, 0
        eligibility_l1_max, threshold_min, threshold_max = 0, Q // 2, 0
        action_counts = {"keep": 0, "repair": 0, "stop": 0}
        output_hash = hashlib.sha256()
        row_hash = hashlib.sha256()
        sample_count = 0
        with samples_path.open("x") as samples:
            for tick in range(512):
                observations = [
                    {"case_id": case, "features": sequences[i][tick]}
                    for i, case in enumerate(cases)
                ]
                advanced = bridge.kernel_advance(profile_sha, observations)
                require(
                    advanced["actual_kernel_calls"] == 8, "Causal kernel count mismatch"
                )
                require(advanced["actual_ndu_calls"] == 8, "NDU count mismatch")
                require(len(advanced["rows"]) == 8, "Causal case roster mismatch")
                for i, row in enumerate(advanced["rows"]):
                    state = reference["sequences"][i][tick]
                    activation = state["activation_q24"]
                    thresholds = state["threshold_q24"]
                    eligibility = state["eligibility_q24"]
                    require(
                        len(activation) == len(thresholds) == len(eligibility) == 20,
                        "State shape drift",
                    )
                    require(
                        all(isinstance(x, int) and 0 <= x <= 8 * Q for x in activation),
                        "Activation bound violation",
                    )
                    require(
                        all(
                            isinstance(x, int) and 0 <= x <= Q // 2 for x in thresholds
                        ),
                        "Homeostatic threshold bound violation",
                    )
                    norm = sum(abs(x) for x in eligibility)
                    require(norm <= 4 * Q, "Original eligibility L1 bound violation")
                    require(
                        row["case_id"] == cases[i] and row["step"] == tick + 1,
                        "Case/sequence drift",
                    )
                    require(
                        row["checkpoint_before"] == previous[i],
                        "Checkpoint chain discontinuity",
                    )
                    require(
                        row["activation_q24"] == activation,
                        "Causal/reference amplitude mismatch",
                    )
                    require(
                        row["temporal_digest"] == state["temporal_digest"],
                        "Causal/reference temporal-state mismatch",
                    )
                    require(
                        row["projection_count"] == state["projection_count"],
                        "Projection count drift",
                    )
                    require(
                        row["readout"]["scores_q24"][2] == 0,
                        "Known-zero stop value changed",
                    )
                    require(
                        not row["terminal"], "Transform fixture terminated unexpectedly"
                    )
                    payload = dict(row)
                    saved = payload.pop("receipt_digest")
                    require(
                        digest(payload) == saved, "Native row receipt digest mismatch"
                    )
                    previous[i] = row["checkpoint_after"]
                    projections += state["projection_count"]
                    activation_min = min(activation_min, min(activation))
                    activation_max = max(activation_max, max(activation))
                    threshold_min = min(threshold_min, min(thresholds))
                    threshold_max = max(threshold_max, max(thresholds))
                    eligibility_l1_max = max(eligibility_l1_max, norm)
                    action_counts[row["readout"]["action"]] += 1
                    output_hash.update(
                        json.dumps(
                            state, sort_keys=True, separators=(",", ":")
                        ).encode()
                        + b"\n"
                    )
                    row_hash.update(saved.encode() + b"\n")
                    if (tick + 1) % 64 == 0:
                        sample = {
                            "case_id": cases[i],
                            "step": tick + 1,
                            "input": sequences[i][tick],
                            "reference_raw_receipt": state,
                            "causal_raw_receipt": row,
                        }
                        samples.write(
                            json.dumps(sample, sort_keys=True, separators=(",", ":"))
                            + "\n"
                        )
                        sample_count += 1
                if (tick + 1) % 64 == 0:
                    summary["windows"].append(
                        {
                            "through_tick_per_case": tick + 1,
                            "causal_ticks": 8 * (tick + 1),
                            "activation_min_q24": activation_min,
                            "activation_max_q24": activation_max,
                            "threshold_min_q24": threshold_min,
                            "threshold_max_q24": threshold_max,
                            "eligibility_l1_max_q24": eligibility_l1_max,
                            "projection_count": projections,
                            "native_action_counts": dict(action_counts),
                            "case_checkpoints": list(previous),
                        }
                    )
        require(projections > 0, "Stress never exercised native projections")
        attempted = bridge.rpc(
            {
                "command": "KernelAdvance",
                "profile_sha256": profile_sha,
                "observations": [{"case_id": cases[0], "features": sequences[0][0]}],
            },
            allow_error=True,
        )
        require(not attempted["ok"], "Maximum supported sequence length did not reject")
        summary.update(
            success=True,
            checks_passed=checks,
            reference_state_stream_sha256=output_hash.hexdigest(),
            causal_receipt_stream_sha256=row_hash.hexdigest(),
            raw_sample_count=sample_count,
            raw_samples_file=samples_path.name,
            raw_samples_sha256=hashlib.sha256(samples_path.read_bytes()).hexdigest(),
            sequence_limit_rejection=attempted,
            numeric_claim="No out-of-bound state, overflow or causal/reference numerical drift in the declared finite fixture",
        )
    except Exception as exc:
        error = exc
        summary.update(error=f"{type(exc).__name__}: {exc}", checks_passed=checks)
    finally:
        summary["native_process_cost"] = bridge.close()
        summary["engineering_wall_seconds"] = time.perf_counter() - started
        summary["source_and_binary_unchanged_after_run"] = (
            hashlib.sha256(binary.read_bytes()).hexdigest() == binary_sha
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == source_sha
            and hashlib.sha256(
                Path(__file__).with_name("adapter.py").read_bytes()
            ).hexdigest()
            == adapter_sha
        )
        (output_dir / "stability_v1.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
    if error:
        raise error
    require(
        summary["native_process_cost"]["counters"]["actual_kernel_calls"] == 8192,
        "Final total kernel count mismatch",
    )
    require(
        summary["native_process_cost"]["counters"]["actual_ndu_calls"] == 4096,
        "Final total NDU count mismatch",
    )
    print(
        json.dumps(
            {
                "success": True,
                "primary_ticks": 4096,
                "charged_kernel_calls": 8192,
                "charged_ndu_calls": 4096,
                "longest_case_ticks": 512,
                "summary": str(output_dir / "stability_v1.json"),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.binary.resolve(), args.output_dir.resolve(), args.run_dir.resolve())


if __name__ == "__main__":
    main()
