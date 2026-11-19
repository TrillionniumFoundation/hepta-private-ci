"""Source reconstruction and original prediction scoring adversarial controls."""
from __future__ import annotations

import copy
import csv
import io
import math
import os
from pathlib import Path
import unittest

from original_canary_audit import Denied
from public_source_recount import (_agree, INTENTS, MAX_CSV_BYTES, normalize, parse_source,
                                  reconstruct, score_logits, recount, SOURCE_SHA256)


def fixture_source():
    train = [["text", "category"]]
    test = [["text", "category"]]
    for category in INTENTS:
        for i in range(17):
            train.append([f"Unique train request {category} {i}", category])
        for i in range(9):
            test.append([f"Unique test request {category} {i}", category])
    def emit(rows):
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerows(rows)
        return buf.getvalue().encode()
    return emit(train), emit(test)


def fake_predictions():
    held = [{"id": f"case-{i}", "label": i//8} for i in range(32)]
    predictions = [{"id": row["id"],
                    "before_logits": [0.0, 0.0, 0.0, 0.0],
                    "after_logits": [1.0 if j == row["label"] else 0.0 for j in range(4)]}
                   for row in held]
    return held, predictions


class SourceRecount(unittest.TestCase):
    def test_source_parser_and_unicode_normalization(self):
        train, test = fixture_source()
        self.assertEqual(len(parse_source(train)), 68)
        self.assertEqual(len(parse_source(test)), 36)
        self.assertEqual(normalize("  The\u3000FULLWIDTH: ＡＢＣ  "), "the fullwidth: abc")

    def test_wrong_source_and_wrong_csv_schema_denied(self):
        train, test = fixture_source()
        with self.assertRaisesRegex(Denied, "fixed source"):
            reconstruct(train, test)
        bad = train.replace(b"text,category", b"text,label")
        with self.assertRaisesRegex(Denied, "columns"):
            parse_source(bad)

    def test_duplicate_normalized_conflicting_labels_denied(self):
        for rows in (b"text,category\r\nA,card_arrival\r\na,exchange_rate\r\n",
                     b"text,category\r\nA,card_arrival\r\nA,exchange_rate\r\n"):
            with self.assertRaisesRegex(Denied, "conflicting"):
                parse_source(rows)

    def test_rfc_csv_quotes_and_same_category_duplicate(self):
        raw = b'text,category\r\n"Hello, World",card_arrival\r\n"hello, world",card_arrival\r\n'
        parsed = parse_source(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed["hello, world"]["category"], "card_arrival")

    def test_invalid_source_rows_rejected(self):
        for raw in (b"", b"text,category\nfoo,card_arrival,unexpected\n",
                    b"text,category\nfoo\n", b"text,category\n,card_arrival\n",
                    b"text,category\n\xff,card_arrival\n"):
            with self.subTest(raw=raw[:30]), self.assertRaises(Denied):
                parse_source(raw)
        with self.assertRaises(Denied):
            parse_source(b"a"*(MAX_CSV_BYTES+1))

    def test_prediction_scoring_and_justified_ties(self):
        held, pred = fake_predictions()
        original = score_logits(pred, held, "before_logits")
        trained = score_logits(pred, held, "after_logits")
        # Python's first-class tie choice, matching the original historical model score.
        self.assertEqual(original["correct"], 8)
        self.assertEqual(trained["correct"], 32)
        self.assertEqual(trained["accuracy"], 1.0)
        self.assertEqual(set(trained["per_class_accuracy"]), set(INTENTS))
        _agree(trained, {k: v for k,v in trained.items() if k != "correct"})

    def test_incomplete_wrong_id_and_nonfinite_denied(self):
        held, pred = fake_predictions()
        with self.assertRaises(Denied):
            score_logits(pred[:-1], held, "after_logits")
        tampered = copy.deepcopy(pred)
        tampered[0]["id"] = tampered[1]["id"]
        with self.assertRaisesRegex(Denied, "identity|mismatch"):
            score_logits(tampered, held, "after_logits")
        tampered = copy.deepcopy(pred)
        tampered[1]["after_logits"][0] = math.inf
        with self.assertRaises(Denied):
            score_logits(tampered, held, "after_logits")

    def test_archived_metrics_mismatch_denied(self):
        held, pred = fake_predictions()
        measured = score_logits(pred, held, "after_logits")
        report = {k: v for k,v in measured.items() if k != "correct"}
        bad = copy.deepcopy(report); bad["accuracy"] = 0.875
        with self.assertRaisesRegex(Denied, "disagrees"):
            _agree(measured, bad)
        bad = copy.deepcopy(report); bad["per_class_accuracy"].pop(INTENTS[0])
        with self.assertRaisesRegex(Denied, "class"):
            _agree(measured, bad)

    def test_original_zip_without_source_bytes_cannot_self_certify(self):
        original = os.environ.get("HDCF_ORIGINAL_CANARY_ZIP")
        if original:
            with self.assertRaisesRegex(Denied, "fixed source"):
                train, test = fixture_source()
                recount(train, test, Path(original).read_bytes())


if __name__ == "__main__":
    unittest.main()
