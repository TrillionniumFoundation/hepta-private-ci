"""Synthetic CLI resource, offline, and receipt rejection tests; no data fetch."""

from contextlib import redirect_stdout
import io
import json
import resource
import sys
import unittest
from unittest.mock import patch
import preflight as p


class CLITests(unittest.TestCase):
    def test_resource_offline_and_serialization_failures_return_only_deny(self):
        def audit_attempt(*_args):
            sys.audit("socket.connect", None, ("synthetic-no-endpoint", 0))

        attempts = [
            {"side_effect": MemoryError("fixture memory failure")},
            {"side_effect": audit_attempt},
            {
                "return_value": {
                    "metadata_supply_status": "SUFFICIENT_METADATA_ONLY",
                    "overflow": "x" * (16 * 1024**2),
                }
            },
            {
                "return_value": {
                    "metadata_supply_status": "SUFFICIENT_METADATA_ONLY",
                    "nonfinite": float("inf"),
                }
            },
        ]
        argv = ["preflight.py", "--archive", "unused", "--p39-registry", "unused"]
        for attempt in attempts:
            output = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(p, "preflight", **attempt),
                redirect_stdout(output),
            ):
                self.assertEqual(p.main(), 2)
            result = json.loads(output.getvalue())
            self.assertEqual(result["metadata_supply_status"], "FAILED_CLOSED")
            self.assertEqual(result["authority"], "DENY_ALL")
            self.assertEqual(result["admission"], "HOLD_NO_GO")
            self.assertNotIn("eligible_inventory_not_selected_roster", result)
            self.assertLess(len(output.getvalue()), 1024)
        output = io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                resource, "setrlimit", side_effect=OSError("fixture limit failure")
            ),
            patch.object(p, "preflight") as implementation,
            redirect_stdout(output),
        ):
            self.assertEqual(p.main(), 2)
            implementation.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["metadata_supply_status"], "FAILED_CLOSED"
        )


if __name__ == "__main__":
    unittest.main()
