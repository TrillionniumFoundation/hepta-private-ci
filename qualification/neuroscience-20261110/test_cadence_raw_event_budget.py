"""Bounded, non-authoritative seven-lineage clock input contract."""
import unittest
from study import ContractError, UpdateOpportunity, cadence_gate

GAPS = {
    "PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
    "VERIFY": 8, "ACT": 16, "LEARN": 16,
}
LIMIT = 65_536

def bounded_then_raise(value):
    for _ in range(LIMIT + 1):
        yield value
    raise AssertionError("clock admission consumed beyond limit plus one")

class ClockRawAdmissionTests(unittest.TestCase):
    def test_raw_event_limit_one_shot_iterator(self):
        event = UpdateOpportunity("MEM", 1, 1, False, False)
        with self.assertRaisesRegex(ContractError, "clock.*limit"):
            cadence_gate(bounded_then_raise(event), GAPS)

    def test_exact_limit_accepted_without_adoption(self):
        events = (UpdateOpportunity("MEM", i, i+1, False, True)
                  for i in range(LIMIT))
        receipt = cadence_gate(events, GAPS)
        self.assertEqual(len(receipt), LIMIT)
        self.assertTrue(all(r["status"] == "NO_UPDATE" and
                            r["authority"] == "DENY_ALL" for r in receipt))

    def test_untrusted_event_object_rejected_as_contract_error(self):
        with self.assertRaises(ContractError):
            cadence_gate([object()], GAPS)

if __name__ == "__main__":
    unittest.main()
