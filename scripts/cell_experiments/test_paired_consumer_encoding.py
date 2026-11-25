"""One-pass readback controls with synthetic tokenizer and router ports."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from . import data, paired_consumer as owner, paired_consumer_run as cold
from . import test_paired_consumer_journal as journal


class Tokenizer:
    def __init__(self, text, ids, answer):
        self.text, self.ids, self.answer = text, ids, answer

    def __len__(self):
        return 32

    def encode(self, text, *, add_special_tokens):
        if text != self.text or add_special_tokens:
            raise AssertionError("unexpected fixture encoding")
        return list(self.ids)

    def decode(self, ids, *, skip_special_tokens):
        if ids != [9] or not skip_special_tokens:
            raise AssertionError("unexpected fixture decoding")
        return self.answer


def node(text, ids, answer):
    model = {
        "runtime": {"max_new_tokens": 1, "message_protocol": "fixture"},
        "fixture_cell": text,
    }
    task = {"input": text}
    tokenizer = Tokenizer(text, ids, answer)
    pred = {
        "loaded_model_digest": data.digest(model),
        "input_sha256": cold.sha(text.encode()),
        "rendered_input": text,
        "rendered_input_sha256": cold.sha(text.encode()),
        "input_ids": list(ids),
        "input_ids_sha256": data.digest(ids),
        "input_tokens": len(ids),
        "output_ids": [9],
        "output_tokens": 1,
        "answer": answer,
        "external_effect_executed": False,
    }
    return model, task, tokenizer, pred


class ConsumerEncodingTests(unittest.TestCase):
    def test_single_cell_returns_verified_ids_and_preserves_the_bytes_api(self):
        model, task, tokenizer, pred = node("first input", [1, 2], "answer")
        ids = [1, 2]
        with (
            patch.object(
                cold, "encoding", return_value=(tokenizer, task["input"], ids)
            ) as encode,
            patch.object(cold.paired_cold, "loader_for", return_value=cold.coding_sft),
        ):
            result = cold._inspect_with_encoding(
                {"candidate": model}, task, Path("."), pred
            )
            self.assertEqual(result, (b"answer", (1, 2)))
            encode.assert_called_once()
            encode.reset_mock()
            self.assertEqual(
                cold.inspect({"candidate": model}, task, Path("."), pred), b"answer"
            )
            encode.assert_called_once()
        ids.append(3)
        pred["input_ids"].append(4)
        self.assertEqual(result, (b"answer", (1, 2)))

    def test_circuit_returns_the_same_validated_first_node_input(self):
        first, task, first_tok, first_pred = node("first input", [1, 2], "relay")
        second, later, second_tok, second_pred = node("later input", [5, 6], "result")
        model = {"models": {"first": first, "second": second}}
        pred = {
            "circuit_trace": {
                "nodes": [
                    {"cell_id": "first", "request": task, "output": first_pred},
                    {"cell_id": "second", "request": later, "output": second_pred},
                ]
            }
        }
        router = Mock()
        with (
            patch.object(
                cold, "encoding", return_value=(first_tok, task["input"], [1, 2])
            ) as encode,
            patch.object(cold.paired_cold, "loader_for", return_value=router),
            patch.object(
                cold.paired_cold,
                "frozen_tokenizer",
                side_effect=[first_tok, second_tok, first_tok, second_tok],
            ),
            patch.object(
                cold.coding_sft, "prompt_text", side_effect=lambda text, *_: text
            ),
            patch.object(cold, "inspect_cell", wraps=cold.inspect_cell) as inspect_cell,
        ):
            result = cold._inspect_with_encoding(
                {"candidate": model}, task, Path("."), pred
            )
            self.assertEqual(result, (b"result", (1, 2)))
            encode.assert_called_once()
            router.check_prediction.assert_called_once_with(model, pred, task)
            self.assertEqual(inspect_cell.call_count, 2)
            wrong = deepcopy(pred)
            wrong["circuit_trace"]["nodes"][0]["output"]["input_ids"] = [7, 8]
            with self.assertRaisesRegex(ValueError, "Circuit first input differs"):
                cold._inspect_with_encoding(
                    {"candidate": model}, task, Path("."), wrong
                )
            wrong = deepcopy(pred)
            wrong["circuit_trace"]["nodes"][1]["output"]["loaded_model_digest"] = (
                data.digest(first)
            )
            with self.assertRaisesRegex(ValueError, "original model output"):
                cold._inspect_with_encoding(
                    {"candidate": model}, task, Path("."), wrong
                )
        first_pred["input_ids"].append(8)
        self.assertEqual(result, (b"result", (1, 2)))

    def test_invalid_candidate_or_input_never_returns_a_verified_encoding(self):
        model, task, tokenizer, original = node("first input", [1, 2], "answer")
        for field, value in (
            ("loaded_model_digest", data.digest("other candidate")),
            ("input_ids", [7, 8]),
            ("rendered_input", "other text"),
            ("output_tokens", 2),
            ("external_effect_executed", True),
        ):
            with (
                self.subTest(field=field),
                patch.object(
                    cold, "encoding", return_value=(tokenizer, task["input"], [1, 2])
                ),
                patch.object(
                    cold.paired_cold, "loader_for", return_value=cold.coding_sft
                ),
            ):
                pred = deepcopy(original)
                pred[field] = value
                with self.assertRaisesRegex(ValueError, "original model output"):
                    cold._inspect_with_encoding(
                        {"candidate": model}, task, Path("."), pred
                    )

    def test_recovery_uses_one_inspection_result_after_the_delivery_fence(self):
        case = journal.ConsumerJournalTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with (
            patch.object(
                cold, "encoding", side_effect=AssertionError("extra exclusion scan")
            ),
            patch.object(
                cold,
                "_inspect_with_encoding",
                return_value=(case.answer, tuple(case.tokens)),
            ) as inspect,
        ):
            self.assertEqual(
                owner.read_run(
                    case.path, case.scope, case.selection, case.req, case.root
                ),
                case.run,
            )
            inspect.assert_called_once_with(
                case.req, case.task, case.root, case.wire["prediction"]
            )
            inspect.reset_mock()
            case.reservations[0].unlink()
            with self.assertRaisesRegex(ValueError, "single-use reservation"):
                owner.read_run(
                    case.path, case.scope, case.selection, case.req, case.root
                )
            inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
