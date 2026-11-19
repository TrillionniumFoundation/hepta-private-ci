"""Loss mathematics and real tiny-decoder invariants; no capability claim."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory_cell"))

import torch
import torch.nn.functional as F

import test_parametric_model as fixture
from parametric_model import SourceMemoryCell, adapter_digest
from source_value_margin_v2 import (
    check_value_receipt_size,
    distinct_value_negatives,
    value_margin_loss,
)
from tensor_contract import tensor_layout


class Tokenizer:
    eos_token_id = 2

    def encode(self, value, add_special_tokens=False):
        return {"red": [3], "blue green": [4, 5]}[value]


class LogitDecoder(torch.nn.Module):
    """Controlled differentiable logits isolate the loss's token boundary."""

    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(vocab_size=7)
        self.positive = torch.nn.Parameter(torch.zeros(1, 8, 7))
        self.negative = torch.nn.Parameter(torch.zeros(1, 8, 7))
        self.calls = []

    def forward(self, input_ids, attention_mask, use_cache, return_dict, labels=None):
        self.calls.append(
            (input_ids.tolist(), None if labels is None else labels.tolist())
        )
        logits = (self.positive if labels is not None else self.negative)[
            :, : input_ids.shape[1]
        ]
        loss = (
            None
            if labels is None
            else F.cross_entropy(
                logits[:, :-1].reshape(-1, 7), labels[:, 1:].reshape(-1)
            )
        )
        return SimpleNamespace(logits=logits, loss=loss)


class ValueMarginMathTests(unittest.TestCase):
    def evaluate(self, model):
        return value_margin_loss(
            model, Tokenizer(), [1, 6], "red", "blue green", maximum=16
        )

    def test_unequal_values_positive_reuse_and_exact_charge(self):
        model = LogitDecoder()
        loss, charge = self.evaluate(model)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(
            model.calls,
            [
                ([[1, 6, 3, 2]], [[-100, -100, 3, 2]]),
                ([[1, 6, 4, 5, 2]], None),
            ],
        )
        self.assertAlmostEqual(
            float(loss), float(torch.log(torch.tensor(7.0))) + 1, places=6
        )
        self.assertEqual(charge["actual_model_forwards"], 2)
        self.assertEqual(charge["actual_input_tokens"], 9)
        self.assertEqual(charge["actual_supervised_tokens"], 4)
        self.assertEqual(
            (
                charge["positive_ce_tokens"],
                charge["positive_margin_tokens"],
                charge["negative_margin_tokens"],
            ),
            (2, 1, 2),
        )
        loss.backward()
        self.assertEqual(float(model.negative.grad[0, 3].abs().sum()), 0)
        self.assertGreater(float(model.positive.grad[0, 2].abs().sum()), 0)
        self.assertGreater(float(model.positive.grad[0, 1].abs().sum()), 0)
        self.assertGreater(float(model.negative.grad[0, 1:3].abs().sum()), 0)

    def test_eos_changes_ce_but_neither_value_score(self):
        model = LogitDecoder()
        first_loss, first = self.evaluate(model)
        with torch.no_grad():
            model.positive[0, 2, 2] = 2
            model.negative[0, 3, 2] = 100
        second_loss, second = self.evaluate(model)
        self.assertLess(float(second_loss), float(first_loss))
        for key in ("positive_value_mean_logp", "negative_value_mean_logp", "hinge"):
            self.assertEqual(first[key], second[key])
        self.assertLess(second["positive_ce"], first["positive_ce"])

    def test_duplicate_token_values_cannot_be_false_negatives(self):
        facts = [dict(value=v, relation="color") for v in ("red", "alias", "blue")]
        self.assertEqual(
            distinct_value_negatives(facts, [[3], [3], [4, 5]]), [[2], [2], [0]]
        )
        with self.assertRaisesRegex(ValueError, "distinct live source"):
            distinct_value_negatives(facts[:2], [[3], [3]])


class ValueMarginCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SourceMemoryCellTests.setUpClass()
        cls.base = fixture.SourceMemoryCellTests.base

    @classmethod
    def tearDownClass(cls):
        fixture.SourceMemoryCellTests.tearDownClass()

    def cell(self):
        cell = SourceMemoryCell(self.base)
        cell.reset("alpha")
        return cell

    def test_real_decoder_charges_accessed_negative_lineage_only(self):
        cell = self.cell()
        facts = [
            fixture.fact("one", "red blue", "a"),
            fixture.fact("two", "green", "b"),
            fixture.fact("three", "blue", "c"),
        ]
        with patch.object(
            cell.reader.model, "forward", wraps=cell.reader.model.forward
        ) as calls:
            receipt = cell.fit_sources(
                facts, 1, 0.001, fixture.TEMPLATES, objective="source_value_margin_v2"
            )
        self.assertEqual(calls.call_count, 2)
        positive = receipt["fact_visits"].index(1)
        negative = receipt["negative_schedule_indices"][0]
        self.assertNotEqual(positive, negative)
        self.assertEqual(
            receipt["roots"],
            sorted(facts[i]["source_digest"] for i in (positive, negative)),
        )
        self.assertEqual(receipt["negative_fact_visits"][negative], 1)
        self.assertEqual(receipt["actual_model_forwards"], 2)
        charge = receipt["value_margin"]
        self.assertEqual(receipt["input_tokens"], charge["actual_input_tokens"])
        self.assertEqual(
            receipt["supervised_tokens"], charge["actual_supervised_tokens"]
        )

    def test_cycling_distinct_values_and_all_successful_forward_charges(self):
        facts = [
            fixture.fact("one", "red blue", "a"),
            fixture.fact("two", "green", "b"),
            fixture.fact("three", "blue", "c"),
            fixture.fact("alpha", "red blue", "d"),
        ]
        cell = self.cell()
        with patch.object(
            cell.reader.model, "forward", wraps=cell.reader.model.forward
        ) as calls:
            receipt = cell.fit_sources(
                facts, 12, 0.001, fixture.TEMPLATES, objective="source_value_margin_v2"
            )
        pairs = list(
            zip(receipt["schedule_indices"], receipt["negative_schedule_indices"])
        )
        for index, fact in enumerate(facts):
            negatives = [facts[n]["value"] for p, n in pairs if p == index]
            self.assertEqual(len(negatives), 3)
            self.assertNotIn(fact["value"], negatives)
            self.assertNotEqual(negatives[0], negatives[1])
            self.assertEqual(negatives[0], negatives[2])
        self.assertEqual(sum(receipt["negative_fact_visits"]), 12)
        self.assertEqual(receipt["actual_model_forwards"], 24)
        actual_inputs = sum(c.kwargs["input_ids"].numel() for c in calls.call_args_list)
        self.assertEqual(receipt["input_tokens"], actual_inputs)
        self.assertEqual(receipt["value_margin"]["actual_input_tokens"], actual_inputs)
        targets = 0
        for positive, negative in zip(
            calls.call_args_list[::2], calls.call_args_list[1::2]
        ):
            labels = positive.kwargs["labels"]
            targets += int((labels != -100).sum())
            targets += (
                negative.kwargs["input_ids"].numel() - int((labels == -100).sum()) - 1
            )
        self.assertEqual(receipt["supervised_tokens"], targets)
        self.assertEqual(receipt["value_margin"]["actual_supervised_tokens"], targets)

    def test_maximum_step_receipt_saves_and_reloads_within_manifest_bound(self):
        cell = self.cell()
        receipt = cell.fit_sources(
            [fixture.fact("one", "red blue", "a"), fixture.fact("two", "green", "b")],
            4096,
            0.001,
            fixture.TEMPLATES,
            objective="source_value_margin_v2",
        )
        self.assertEqual(receipt["actual_model_forwards"], 8192)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            manifest = cell.save(path)
            self.assertLessEqual((path / "lineage.json").stat().st_size, 256 * 1024)
            self.assertEqual(
                check_value_receipt_size(receipt, tensor_layout(cell.reader.initial)),
                (path / "lineage.json").stat().st_size,
            )
            self.cell().load(
                path,
                expected_manifest_sha256=manifest,
                scope="alpha",
                allowed_roots={"a" * 64, "b" * 64},
                revoked=set(),
            )

    def test_oversized_inherited_lineage_cannot_return_a_successful_fit(self):
        cell = self.cell()
        cell.reader.roots = {f"{i:064x}" for i in range(2000)}
        with self.assertRaisesRegex(ValueError, "manifest byte bound"):
            cell.fit_sources(
                [
                    fixture.fact("one", "red blue", "a"),
                    fixture.fact("two", "green", "b"),
                ],
                1,
                0.001,
                fixture.TEMPLATES,
                objective="source_value_margin_v2",
            )
        self.assertTrue(cell.reader.quarantined)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            cell.save(Path("unused-oversized-checkpoint"))

    def test_second_forward_failure_after_a_write_quarantines_partial_adapter(self):
        cell = self.cell()
        before = adapter_digest(cell.reader.model)
        actual = cell.reader.model.forward
        count = 0

        def fail(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 4:
                raise RuntimeError("negative forward failed")
            return actual(*args, **kwargs)

        with patch.object(cell.reader.model, "forward", fail):
            with self.assertRaisesRegex(RuntimeError, "negative forward failed"):
                cell.fit_sources(
                    [
                        fixture.fact("one", "red blue", "a"),
                        fixture.fact("two", "green", "b"),
                    ],
                    2,
                    0.001,
                    fixture.TEMPLATES,
                    objective="source_value_margin_v2",
                )
        self.assertEqual(count, 4)
        self.assertNotEqual(adapter_digest(cell.reader.model), before)
        self.assertTrue(cell.reader.quarantined)
        self.assertIsNone(cell.reader.scope)
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in cell.reader.model.parameters()
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "partial"
            with self.assertRaisesRegex(ValueError, "unavailable"):
                cell.save(destination)
            self.assertFalse(destination.exists())
        with self.assertRaisesRegex(ValueError, "unavailable"):
            cell.generate(["What is the color of one?"])

    def test_old_margin_still_rejects_unequal_lengths(self):
        with self.assertRaisesRegex(ValueError, "equal-length"):
            self.cell().fit_sources(
                [
                    fixture.fact("one", "red blue", "a"),
                    fixture.fact("two", "green", "b"),
                ],
                1,
                0.001,
                fixture.TEMPLATES,
                objective="source_margin",
            )


if __name__ == "__main__":
    unittest.main()
