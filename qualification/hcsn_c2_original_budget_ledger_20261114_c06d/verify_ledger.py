#!/usr/bin/env python3
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ledger = json.loads((ROOT / "LEDGER.json").read_text(encoding="utf-8"))

assert ledger["status"] == "ORIGINAL_START_LEDGER_CLOSED_CURRENT_REMAINING_UNKNOWN"
assert ledger["all_closed"] is False
assert ledger["full_independent_training_replay_completed"] == 0
assert ledger["lifetime_optimizer_calls"] == "UNKNOWN"
assert ledger["original_controller_terminal"] == "UNKNOWN"
assert all(value == 0 for value in ledger["execution"].values())

originals = ledger["desktop_originals"]
assert originals["campaign_result"]["sha256"] == "362bc0345635bb5c9438670c13efa5908140527463aa4f373479235686b5683b"
assert originals["campaign_result"]["status"] == "completed_attempt_roster"
assert originals["campaign_result"]["source_unchanged"] is True
assert originals["locked_plan"]["sha256"] == originals["campaign_plan"]["sha256"]
assert originals["commands"]["hcsn_started_rows"] == originals["commands"]["hcsn_terminal_rows"] == 6
assert originals["training_source"]["sha256"] == "06cb85c7a0da85fb8d656526c2b07285979bc6c47c2e00c154e89f43bcfc1a22"

fits = ledger["fits"]
assert len(fits) == 6
assert [row["parent_epoch"] for row in fits] == [46, 47, 46, 47, 46, 46]
assert all(row["command_returncode"] == 2 for row in fits)
assert all(row["fit_status"] == "budget_exhausted" for row in fits)
assert all(row["current_remaining_wall_seconds"] == "UNKNOWN" for row in fits)
assert len({row["parent_sha256"] for row in fits}) == 6
assert len({row["plan_sha256"] for row in fits}) == 6
assert len({row["result_sha256"] for row in fits}) == 6

cap = ledger["contract"]["cumulative_active_wall_seconds_per_fit"]
reserve = ledger["contract"]["finalization_reserve_seconds_inside_same_cap"]
charges = [row["original_whole_process_wall_seconds"] for row in fits]
remainders = [row["original_decision_non_refunded_charged_remainder_seconds"] for row in fits]
worker_ceilings = [row["original_decision_worker_active_ceiling_before_finalization_seconds"] for row in fits]
assert all(cap - charge == remainder for charge, remainder in zip(charges, remainders, strict=True))
assert all(remainder - reserve == ceiling and ceiling >= 0 for remainder, ceiling in zip(remainders, worker_ceilings, strict=True))
charge_sum = math.fsum(charges)
remaining_sum = len(fits) * cap - charge_sum
worker_sum = remaining_sum - len(fits) * reserve
assert charge_sum == ledger["arithmetic"]["original_whole_process_wall_seconds_fsum"]
assert remaining_sum == ledger["arithmetic"]["original_decision_non_refunded_charged_remainder_seconds_fsum"]
assert worker_sum == ledger["arithmetic"]["original_decision_worker_active_ceiling_before_finalization_seconds_fsum"]
assert remaining_sum == ledger["contract"]["maximum_new_summed_fit_active_wall_seconds_before_exit_overhead"]
assert ledger["arithmetic"]["matches_frozen_decision_aggregate_before_reserve_deduction_exactly"] is True

print("PASS: original start ledger and reserve separation closed; current remaining stays UNKNOWN/HOLD")
