from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).with_name("runtime_agentd_target_host.py")
SPEC = importlib.util.spec_from_file_location("runtime_agentd_target_host", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE_SHA = "a" * 40
SOURCE_TREE = "b" * 40
CONFIGURATION = "c" * 64


def contract() -> dict:
    return {
        "requiredTargetHostScenarios": {
            "safe": {
                "destructive": False,
                "requiredInvariants": ["bounded", "observable"],
            },
            "destructive": {
                "destructive": True,
                "requiredInvariants": ["no_redispatch"],
            },
        }
    }


def plan() -> dict:
    return {
        "schema": 1,
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "host_identity": "fixture-host",
        "effective_configuration_digest": CONFIGURATION,
        "artifacts": {
            "fixture": {
                "path": str(Path(sys.executable).resolve()),
                "sha256": MODULE.sha256(Path(sys.executable).resolve()),
            }
        },
        "scenarios": {
            "safe": {
                "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                "timeout_seconds": 10,
            },
            "destructive": {
                "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                "timeout_seconds": 10,
            },
        },
    }


def adapter_result(name: str, invariants: list[str]) -> dict:
    return {
        "schema": 1,
        "scenario": name,
        "operation_ids": [f"operation-{name}"],
        "initial_state_digest": "d" * 64,
        "final_state_digest": "e" * 64,
        "observed_invariants": {key: True for key in invariants},
        "measurements": {"samples": 1},
        "notes": [],
    }


def receipt(name: str, invariants: list[str]) -> dict:
    result = adapter_result(name, invariants)
    return {
        "schema": 1,
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "host_identity": "fixture-host",
        "kernel_or_platform": "fixture",
        "effective_configuration_digest": CONFIGURATION,
        "artifact_digests": {"fixture": "f" * 64},
        "scenario": name,
        "destructive": name == "destructive",
        "started_at_unix_ms": 1,
        "finished_at_unix_ms": 2,
        "initial_state_digest": result["initial_state_digest"],
        "final_state_digest": result["final_state_digest"],
        "operation_ids": result["operation_ids"],
        "observed_invariants": result["observed_invariants"],
        "measurements": result["measurements"],
        "notes": result["notes"],
        "command": [str(Path(sys.executable).resolve())],
        "exit_code": 0,
        "log_sha256": "1" * 64,
        "result": "success",
        "production_activation": False,
    }


class TargetHostQualificationTests(unittest.TestCase):
    def test_plan_requires_explicit_destructive_admission(self) -> None:
        with self.assertRaisesRegex(ValueError, "allow-destructive"):
            MODULE.validate_plan(plan(), contract(), SOURCE_SHA, SOURCE_TREE, False)

    def test_plan_normalizes_complete_scenario_set(self) -> None:
        normalized = MODULE.validate_plan(
            plan(), contract(), SOURCE_SHA, SOURCE_TREE, True
        )
        self.assertEqual(set(normalized), {"safe", "destructive"})
        self.assertTrue(Path(normalized["safe"]["argv"][0]).is_absolute())
        self.assertTrue(normalized["destructive"]["destructive"])

    def test_adapter_result_requires_exact_true_invariants(self) -> None:
        value = adapter_result("safe", ["bounded", "observable"])
        self.assertEqual(
            MODULE.validate_adapter_result(
                value, "safe", ["bounded", "observable"]
            ),
            value,
        )
        value["observed_invariants"]["bounded"] = False
        with self.assertRaisesRegex(ValueError, "invariants failed"):
            MODULE.validate_adapter_result(
                value, "safe", ["bounded", "observable"]
            )

    def test_aggregate_requires_every_scenario(self) -> None:
        safe = receipt("safe", ["bounded", "observable"])
        with self.assertRaisesRegex(ValueError, "missing required"):
            MODULE.validate_aggregate([safe], contract(), SOURCE_SHA, SOURCE_TREE)

    def test_aggregate_rejects_activation_claim(self) -> None:
        safe = receipt("safe", ["bounded", "observable"])
        destructive = receipt("destructive", ["no_redispatch"])
        destructive["production_activation"] = True
        with self.assertRaisesRegex(ValueError, "cannot activate production"):
            MODULE.validate_aggregate(
                [safe, destructive], contract(), SOURCE_SHA, SOURCE_TREE
            )

    def test_complete_aggregate_succeeds(self) -> None:
        aggregate = MODULE.validate_aggregate(
            [
                receipt("safe", ["bounded", "observable"]),
                receipt("destructive", ["no_redispatch"]),
            ],
            contract(),
            SOURCE_SHA,
            SOURCE_TREE,
        )
        self.assertEqual(aggregate["target_host_result"], "success")
        self.assertFalse(aggregate["production_activation"])


if __name__ == "__main__":
    unittest.main()
