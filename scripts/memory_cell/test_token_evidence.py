import unittest
from types import SimpleNamespace

import torch

from native import digest
from selector_head import TrainingCut
from token_evidence import TokenEvidenceHead, TokenWindow, position_labels


class TokenEvidenceTests(unittest.TestCase):
    def record(self):
        return TokenWindow(
            "q",
            "family",
            "window",
            "root",
            torch.eye(3),
            ((-1, -1), (5, 8), (9, 12)),
            1.0,
        )

    def cut(self):
        return TrainingCut(
            frozenset({"q"}),
            frozenset({"family"}),
            frozenset({"root"}),
            frozenset({"test"}),
            "admitted-test",
        )

    def test_offsets_and_unknown_never_impute_null(self):
        target = SimpleNamespace(
            question_id="q", spans=((6, 11, "x"),), unanswerable=False
        )
        self.assertEqual(position_labels(target, self.record()), ((1, 2),))
        target.spans = ((30, 32, "x"),)
        self.assertEqual(position_labels(target, self.record()), ())
        target.spans, target.unanswerable = (), True
        self.assertEqual(position_labels(target, self.record()), ((0, 0),))
        target.question_id = "foreign"
        with self.assertRaises(ValueError):
            position_labels(target, self.record())

    def test_real_learning_reload_and_revocation(self):
        model = TokenEvidenceHead(3, "encoder")
        record = self.record()
        before = model.margin(record, revoked=set())
        receipt = model.fit(((record, ((2, 2),)),), self.cut(), steps=64, revoked=set())
        self.assertGreater(receipt["delta_squared_norm"], 0)
        after = model.margin(record, revoked=set())
        self.assertGreater(after[0], before[0])
        self.assertEqual(after[1:], (2, 2))
        raw = model.export()
        restored = TokenEvidenceHead.restore(
            raw,
            expected_digest=digest(raw.hex()),
            encoder_identity="encoder",
            allowed_roots={"root"},
            revoked=set(),
        )
        self.assertEqual(after, restored.margin(record, revoked=set()))
        with self.assertRaises(ValueError):
            restored.margin(record, revoked={"root"})
        with self.assertRaises(ValueError):
            TokenEvidenceHead.restore(
                raw,
                expected_digest=digest(raw.hex()),
                encoder_identity="other",
                allowed_roots={"root"},
                revoked=set(),
            )

    def test_unknown_row_and_wrong_cut_reject_before_update(self):
        model = TokenEvidenceHead(3, "encoder")
        original = {k: v.clone() for k, v in model.state_dict().items()}
        for gold, revoked in (((), set()), (((1, 1),), {"root"}), (((1, 99),), set())):
            with self.assertRaises(ValueError):
                model.fit(
                    ((self.record(), gold),), self.cut(), steps=1, revoked=revoked
                )
            self.assertTrue(
                all(torch.equal(v, original[k]) for k, v in model.state_dict().items())
            )

    def test_question_and_special_tokens_cannot_be_selected(self):
        record = TokenWindow(
            "q", "family", "w", "root", torch.eye(3), ((-1, -1), (-1, -1), (5, 8)), 1.0
        )
        model = TokenEvidenceHead(3, "encoder")
        with torch.no_grad():
            model.positions.weight[:, 1] = 1000
        self.assertEqual(model.margin(record, revoked=set())[1:], (2, 2))


if __name__ == "__main__":
    unittest.main()
