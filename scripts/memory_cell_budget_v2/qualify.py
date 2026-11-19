"""Frozen pure qualification and read-only replay of existing historical evidence."""

import argparse
import copy
import datetime
import json
from pathlib import Path
import sys
import time
import unittest

from arm_controller import ArmController
from common import BudgetExceeded, file_identity, quantities, read_json, save
from receipt_bridge import collect
from tensor_capacity import admit


HERE = Path(__file__).resolve().parent


def case_ids(suite):
    return [
        identity
        for item in suite
        for identity in (
            case_ids(item) if isinstance(item, unittest.TestSuite) else [item.id()]
        )
    ]


def check_sources(plan):
    for row in plan["sources"] + [plan["python"]]:
        if file_identity(row["path"]) != row["identity"]:
            raise ValueError("qualification source/runtime pin changed")
    if Path(sys.executable).resolve() != Path(plan["python"]["path"]).resolve():
        raise ValueError("qualification Python differs from frozen runtime")


def run(plan_path, expected_sha, output):
    identity = file_identity(plan_path)
    if identity["sha256"] != expected_sha:
        raise ValueError("qualification plan SHA mismatch")
    plan = read_json(plan_path, identity)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.monotonic_ns(), time.process_time_ns()
    result = {
        "schema": "hepta.memory-budget.qualification.v2",
        "accepted": False,
        "plan_identity": identity,
        "new_model_calls": 0,
        "training_updates": 0,
        "five_arm_experiments": 0,
        "future_tasks": 0,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        check_sources(plan)
        suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py")
        discovered = sorted(case_ids(suite))
        if discovered != plan["test_ids"]:
            raise ValueError("discovered tests differ from frozen qualification")
        with (output / "unittest.txt").open("x") as stream:
            tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        result["unit_tests"] = {
            "ids": discovered,
            "run": tests.testsRun,
            "failures": len(tests.failures),
            "errors": len(tests.errors),
            "skips": len(tests.skipped),
            "expected_failures": len(tests.expectedFailures),
            "unexpected_successes": len(tests.unexpectedSuccesses),
            "raw": file_identity(output / "unittest.txt"),
        }
        if not tests.wasSuccessful() or tests.skipped or tests.expectedFailures:
            raise ValueError("pure qualification did not completely pass")
        single = copy.deepcopy(plan["capacity"])
        single["components"] = single["components"][:1]
        single["limits"]["active_values"] = 460800
        single["limits"]["active_tensor_bytes"] = 460800 * 4
        one = admit(single)
        two = admit(plan["capacity"])
        if [one["used"]["active_values"], two["used"]["active_values"]] != [
            460800,
            921600,
        ]:
            raise ValueError("historical r8 checkpoint tensor count changed")
        denied = copy.deepcopy(plan["capacity"])
        denied["limits"] = single["limits"]
        try:
            admit(denied)
        except ValueError as error:
            result["two_real_r8_refused_under_one_r8_cap"] = str(error)
        else:
            raise ValueError("two actual checkpoints bypassed shared capacity")
        save(output / "single-real-r8.json", one)
        save(output / "two-real-r8.json", two)
        merged = collect(plan["historical_receipts"])
        if merged["observation"]["cpu_ns"] != plan["expected_historical_cpu_ns"]:
            raise ValueError("historical raw CPU aggregation changed")
        save(output / "historical-merged.json", merged)
        controller = ArmController(
            output / "accounting-replay",
            arm="historical-receipt-replay",
            seed=24041,
            protocol_sha256=expected_sha,
            budget=plan["replay_budget"],
            capacity=single,
        )
        request = {
            "scope": "offline accounting replay, not newly executed physical work"
        }
        ticket = controller.begin(
            "existing-warm-cost", "infer", plan["replay_reservation"], request
        )
        controller.finish(ticket, plan["historical_receipts"])
        effects = []
        try:
            controller.run(
                "would-exceed-remaining",
                "infer",
                quantities({"cpu_ns": 8 * 10**9}),
                request,
                lambda token: effects.append(token),
            )
        except BudgetExceeded:
            result["gate_denied_before_callback"] = effects == []
        else:
            raise ValueError("gate received a second full allowance")
        result["accounting_replay"] = {
            "observation_cpu_ns": merged["observation"]["cpu_ns"],
            "budget_charge_state": controller.ledger.snapshot(),
            "remaining": controller.remaining(),
            "new_physical_work": False,
        }
        check_sources(plan)
        result["accepted"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["qualification_self_cpu_ns"] = time.process_time_ns() - started_cpu
        result["qualification_wall_ns"] = time.monotonic_ns() - started_wall
        result["finished_utc"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        result["scope"] = (
            "Engineering qualification and historical metadata replay only; no five-arm task or scientific benefit result."
        )
        save(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.plan, args.plan_sha256, args.output)
    print(
        json.dumps(
            {key: result.get(key) for key in ("accepted", "error", "unit_tests")}
        )
    )
    raise SystemExit(0 if result["accepted"] else 1)
