from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


REFERENCE_PATH = Path(__file__).with_name("reference.py")
SPEC = importlib.util.spec_from_file_location("hepta_fault_matrix_reference", REFERENCE_PATH)
assert SPEC is not None and SPEC.loader is not None
REFERENCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REFERENCE
SPEC.loader.exec_module(REFERENCE)
Record = REFERENCE.Record
State = REFERENCE.State
replay = REFERENCE.replay
transition = REFERENCE.transition


class FaultMatrixTests(unittest.TestCase):
    def record(self) -> Record:
        return Record("operation-1", "payload-a", 7)

    def test_crash_before_authority_replays_pending(self) -> None:
        record = copy.deepcopy(self.record())
        self.assertEqual(replay(record, "operation-1", "payload-a", 7), record)

    def test_crash_after_authority_before_dispatch_is_not_success(self) -> None:
        record = transition(self.record(), State.AUTHORIZED, generation=7)
        restored = copy.deepcopy(record)
        self.assertEqual(restored.state, State.AUTHORIZED)

    def test_dispatch_ack_loss_stays_indeterminate_until_observed(self) -> None:
        record = transition(self.record(), State.AUTHORIZED, generation=7)
        record = transition(record, State.DISPATCHED, generation=7)
        record = transition(record, State.INDETERMINATE, generation=7)
        self.assertEqual(record.state, State.INDETERMINATE)
        self.assertEqual(
            transition(record, State.APPLIED, generation=7).state,
            State.APPLIED,
        )

    def test_stale_reconciler_and_payload_drift_fail_closed(self) -> None:
        record = transition(self.record(), State.AUTHORIZED, generation=7)
        with self.assertRaisesRegex(ValueError, "stale-generation"):
            transition(record, State.DISPATCHED, generation=6)
        with self.assertRaisesRegex(ValueError, "binding-conflict"):
            replay(record, "operation-1", "payload-b", 7)

    def test_terminal_state_is_immutable(self) -> None:
        record = transition(self.record(), State.AUTHORIZED, generation=7)
        record = transition(record, State.DISPATCHED, generation=7)
        record = transition(record, State.NOT_APPLIED, generation=7)
        with self.assertRaisesRegex(ValueError, "terminal"):
            transition(record, State.APPLIED, generation=7)


if __name__ == "__main__":
    unittest.main()
