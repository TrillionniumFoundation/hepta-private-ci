#!/usr/bin/env python3
"""Exercise the fleet validator against the real emitter output, never a fallback fixture."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

from platform_wire_managed_fleet_profile import validate


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate measurement field: {key}")
        result[key] = value
    return result


def contract_suite(report: dict[str, Any], rounds: int) -> unittest.TestSuite:
    class EmitterContractTests(unittest.TestCase):
        def test_real_emitter_output_is_accepted(self) -> None:
            validate(report, rounds)

        def test_same_turn_completion_is_valid(self) -> None:
            changed = copy.deepcopy(report)
            for row in changed["scenarios"]:
                row["scheduler_turns_to_last_completion_max"] = row[
                    "scheduler_turns_to_first_completion_max"
                ]
                row["scheduler_fairness_gap_turns_max"] = 0
            validate(changed, rounds)

        def test_negative_boolean_and_missing_gap_reject(self) -> None:
            for value in (-1, True, False, None, 0.0):
                changed = copy.deepcopy(report)
                changed["scenarios"][0]["scheduler_fairness_gap_turns_max"] = value
                with self.subTest(value=value), self.assertRaises(ValueError):
                    validate(changed, rounds)

        def test_inconsistent_zero_gap_rejects(self) -> None:
            changed = copy.deepcopy(report)
            row = changed["scenarios"][0]
            row["scheduler_turns_to_last_completion_max"] = row[
                "scheduler_turns_to_first_completion_max"
            ] + 1
            row["scheduler_fairness_gap_turns_max"] = 0
            with self.assertRaises(ValueError):
                validate(changed, rounds)

        def test_lost_frame_rejects(self) -> None:
            changed = copy.deepcopy(report)
            changed["scenarios"][0]["delivered_frames"] -= 1
            with self.assertRaises(ValueError):
                validate(changed, rounds)

        def test_missing_scenario_rejects(self) -> None:
            changed = copy.deepcopy(report)
            changed["scenarios"].pop()
            with self.assertRaises(ValueError):
                validate(changed, rounds)

        def test_measurement_cannot_become_acceptance(self) -> None:
            for field in ("independent_acceptance", "authenticated_network_ingress"):
                changed = copy.deepcopy(report)
                changed[field] = True
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate(changed, rounds)

    return unittest.defaultTestLoader.loadTestsFromTestCase(EmitterContractTests)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--rounds", type=int, required=True)
    args = parser.parse_args()
    if not 8 <= args.rounds <= 256:
        parser.error("rounds must be in 8..256")
    try:
        with args.input.open("rb") as stream:
            raw = stream.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("measurement exceeds the 512 KiB contract-input limit")
        report = json.loads(raw, object_pairs_hook=unique_object)
        # Reject invalid input before running mutation tests. No synthetic fallback.
        validate(report, args.rounds)
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(f"real fleet measurement rejected: {error}", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(contract_suite(report, args.rounds))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
