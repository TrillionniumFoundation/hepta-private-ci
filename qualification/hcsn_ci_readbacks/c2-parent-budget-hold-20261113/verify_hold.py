#!/usr/bin/env python3
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
hold = json.loads((ROOT / "HOLD.json").read_text(encoding="utf-8"))

assert hold["overall"] == "HOLD_NO_GO"
assert hold["all_closed"] is False
assert hold["full_independent_training_replay_completed"] == 0
assert hold["lifetime_optimizer_calls"] == "UNKNOWN"
assert hold["original_controller_terminal"] == "UNKNOWN"
assert all(value == 0 for value in hold["execution"].values())

fits = hold["fits"]
assert len(fits) == hold["contract"]["fits"] == 6
assert [fit["original_start_parent_epoch"] for fit in fits] == [46, 47, 46, 47, 46, 46]
assert [fit["last_observed_late_epoch"] for fit in fits] == [116, 76, 126, 50, 127, 72]
assert all(fit["remaining_wall_seconds"] == "UNKNOWN" for fit in fits)
assert all(len(fit["original_start_parent_sha256"]) == 64 for fit in fits)
assert all(len(fit["last_observed_late_checkpoint_sha256"]) == 64 for fit in fits)
assert not ({fit["original_start_parent_sha256"] for fit in fits} & {fit["last_observed_late_checkpoint_sha256"] for fit in fits})

checks = hold["arithmetic_checks_only_not_authoritative_ledgers"]
result_wall = math.fsum(fit["original_result_wall_seconds"] for fit in fits)
process_wall = math.fsum(fit["original_result_process_wall_seconds"] for fit in fits)
cap = hold["contract"]["cumulative_active_wall_seconds_per_fit"] * len(fits)
assert math.isclose(result_wall, checks["sum_original_result_wall_seconds"], rel_tol=0.0, abs_tol=1e-9)
assert math.isclose(process_wall, checks["sum_original_result_process_wall_seconds"], rel_tol=0.0, abs_tol=1e-9)
assert math.isclose(cap - result_wall, checks["naive_cap_minus_result_wall_seconds"], rel_tol=0.0, abs_tol=1e-9)
assert math.isclose(cap - process_wall, checks["naive_cap_minus_process_wall_seconds"], rel_tol=0.0, abs_tol=1e-9)
authoritative = hold["contract"]["authoritative_aggregate_maximum_new_summed_fit_active_wall_seconds_before_exit_overhead"]
assert not math.isclose(authoritative, cap - result_wall, rel_tol=0.0, abs_tol=1e-9)
assert not math.isclose(authoritative, cap - process_wall, rel_tol=0.0, abs_tol=1e-9)

print("PASS: six start-parent identities closed; remaining-wall ledger remains UNKNOWN/HOLD")
