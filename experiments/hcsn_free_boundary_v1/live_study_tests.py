"""Development-only native driver checks; never a heldout model evaluation."""

import argparse
import hashlib
import json
from pathlib import Path
import traceback
from unittest.mock import patch

import torch

from .live_study import (PACKAGE, REPOSITORY, REFERENCE_READS, collect_native,
                         cost_scenarios, run_references, source_identity, verify_freeze,
                         verify_recovered_trajectory)
from .model import HCSNClassifier
from .native_bridge import POLICIES, restored_binary
from .run_native import write
from .run_native_live import model_identity, run_live


def run_checks(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "REQUEST.json", {"scope": "untrained synthetic development fixture; not scientific heldout results",
                                    "source_sha256": source_identity()})
    try:
        torch.set_num_threads(1)
        model = HCSNClassifier(3, 2, width=4, seed=77).eval()
        generator = torch.Generator().manual_seed(73)
        x = torch.randn(1, 24, 3, generator=generator)
        dt, labels = torch.full((1, 24), 0.7), torch.tensor([0])
        ids, price = ["development-synthetic-only"], 0.02
        run_live(model, x, dt, labels, 0.01, output / "uninterrupted", binary=restored_binary(),
                 episode_ids=ids, recover_first=False,
                 provenance={"scope": "untrained development fixture"})
        live = run_live(model, x, dt, labels, price, output / "native", binary=restored_binary(),
                        episode_ids=ids, recover_first=True,
                        provenance={"scope": "untrained development fixture"})
        records = collect_native(output / "native", live, price)
        verify_recovered_trajectory(output / "uninterrupted", output / "native", records)
        plan = json.loads((output / "native/PROTOCOL.json").read_text())
        expected_identity = model_identity(model)[0]
        assert all(plan["policies"][name]["source_model_digest"] == expected_identity for name in POLICIES)
        assert all(row["native_counters"]["owner_ticks"] == row["actual_reads"] for row in records.values())
        with patch.object(model, "step", wraps=model.step) as steps:
            refs = run_references(model, x, dt, labels, ids, price, output / "references")
            expected_calls = sum(x.shape[1] if count is None else count for count in REFERENCE_READS.values())
            assert steps.call_count == expected_calls
        assert sum(row["actual_reads"] for row in refs.values()) == expected_calls
        for row in refs.values():
            assert abs(row["mean_utility"] - row["accuracy"] + price * row["mean_reads"]) < 1e-10
        protocol = json.loads((PACKAGE / "PROTOCOL.json").read_text())
        all_records = {**records, **refs}
        scenarios = cost_scenarios([{"read_price": price, "results": all_records}], records, 40.0, protocol)
        assert len(scenarios) == 84
        for row in scenarios:
            total_cpu = (row["full_training_search_cpu_amortized"]
                         + row["measured_execution_cpu_per_episode"]
                         + row["recovery_verification_cpu_amortized"])
            assert abs(row["scenario_utility"] - row["read_only_utility"]
                       + row["utility_units_per_cpu_second_scenario"] * total_cpu) < 1e-10
        frozen = {str((PACKAGE / name).relative_to(REPOSITORY)):
                  hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest()
                  for name in ("model.py", "oracle_torch.py", "training.py", "benchmark_models.py")}
        write(output / "valid_freeze.json", {"source_sha256": frozen})
        verify_freeze(output / "valid_freeze.json")
        frozen[next(iter(frozen))] = "0" * 64
        write(output / "invalid_freeze.json", {"source_sha256": frozen})
        rejected = False
        try:
            verify_freeze(output / "invalid_freeze.json")
        except ValueError:
            rejected = True
        assert rejected
        result = {"status": "passed", "scope": "development only; no model training or heldout data",
                  "native_profile_binds_actual_model": True,
                  "actual_native_owner_ticks_equal_paid_reads": True,
                  "fixed_reference_model_step_calls": expected_calls,
                  "cost_scenario_rows_checked": len(scenarios),
                  "source_freeze_mismatch_rejected": True,
                  "recovered_raw_and_native_trajectories_match_uninterrupted": True,
                  "recovery_exercised_by_policy": {key: value["cold_native_and_neural_restorations"]
                                                   for key, value in records.items()},
                  "source_sha256": source_identity()}
        write(output / "SUMMARY.json", result)
        return result
    except Exception as error:
        write(output / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                       "traceback": traceback.format_exc(), "partial_results_preserved": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_checks(args.output), sort_keys=True))
