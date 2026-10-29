"""Focused state/provenance tests; real native composition has its own run record."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.first_passage_adaptive.credit_execution import CONTRACT, CreditAccount, HERE, file_sha, load_selected_model


CHECKPOINT = HERE / "evidence/train_20261029_v2/checkpoint.json"


def response(name, usage, spent, *, successful=0, replayed=False):
    return {"request_digest": name, "owner": {"checkpoint_after": "anchor-" + name},
            "source_read_attempts_this_call": usage, "source_reads_this_call": successful,
            "state": {"read_units_spent": spent, "terminal": "ReadFailed" if usage and not successful else None},
            "read": None, "replayed": replayed}


class CreditTests(unittest.TestCase):
    def test_selected_training_checkpoint_is_loaded_with_explicit_coordinate_mapping(self):
        parameters, selected = load_selected_model(CHECKPOINT, file_sha(CHECKPOINT))
        raw = json.loads(CHECKPOINT.read_text())["physical_training"]["final"]
        self.assertEqual(parameters.drift, -raw[0])
        self.assertEqual(parameters.sigma, raw[1])
        self.assertEqual(selected["training_parameters"]["physical_cancel_rate"], raw[2])
        self.assertEqual(selected["cell_model_digest"], parameters.digest())

    def test_selected_checkpoint_content_change_rejects_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "checkpoint.json"
            changed.write_bytes(CHECKPOINT.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
                load_selected_model(changed, file_sha(CHECKPOINT))

    def test_failed_attempt_increases_price_and_replay_does_not_settle_twice(self):
        credit = CreditAccount(True)
        first = response("one", 1, 1)
        receipt = credit.settle(first, 0)
        expected = CONTRACT["price_step"] * (1 - CONTRACT["target_usage_per_decision"])
        self.assertEqual(credit.price, expected)
        self.assertEqual(receipt["record"]["successful_source_reads"], 0)
        snapshot = credit.snapshot()
        replay = response("one", 0, 1, replayed=True)
        self.assertTrue(credit.settle(replay, 0)["already_applied"])
        self.assertEqual(credit.snapshot(), snapshot)

    def test_missing_credit_outcome_cannot_be_reconstructed_from_native_replay(self):
        with self.assertRaisesRegex(ValueError, "missing credit settlement"):
            CreditAccount(True).settle(response("missing", 0, 1, replayed=True), 0)

    def test_price_bounds_and_owner_budget_charge_are_enforced(self):
        credit = CreditAccount(True)
        for index in range(10):
            credit.settle(response(str(index), 1, index + 1), index)
        self.assertEqual(credit.price, CONTRACT["price_maximum"])
        for index in range(20):
            credit.settle(response("idle-" + str(index), 0, 10), 10)
        self.assertEqual(credit.price, 0)
        with self.assertRaisesRegex(ValueError, "budget disagree"):
            credit.settle(response("bad-charge", 0, 11), 10)


if __name__ == "__main__":
    unittest.main()
