"""Captured synthetic originals test context integrity, not consent or model quality."""

import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import chat_protocol as chat, opaque_teacher_data as opaque, paired_source
from .test_chat_protocol import ChatTokenizer
from .test_data import record
from .test_paired_opaque_teacher import pair


class OpaqueContextTests(unittest.TestCase):
    def test_unbound_history_is_refused_without_changing_retained_originals(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            retained = {path.name: path.read_bytes() for path in originals.iterdir()}
            source = retained[correction["source"]["sha256"]]
            paired_source.derive(failure, correction, originals)
            histories = (
                None,
                [{"role": "user", "content": failure["task"]["input"]}],
                [
                    {"role": "user", "content": failure["task"]["input"]},
                    {"role": "assistant", "content": correction["final_answer"]},
                    {"role": "user", "content": "Repeat the previous answer."},
                ],
            )
            for history in histories:
                changed_failure, changed_correction = copy.deepcopy(
                    (failure, correction)
                )
                for changed in (changed_failure, changed_correction):
                    changed["task"]["messages"] = copy.deepcopy(history)
                with self.subTest(history=history):
                    with self.assertRaisesRegex(ValueError, "task.messages"):
                        opaque.verify_source(changed_correction, source)
                    with self.assertRaisesRegex(ValueError, "task.messages"):
                        paired_source.derive(
                            changed_failure, changed_correction, originals
                        )
            self.assertEqual(
                {path.name: path.read_bytes() for path in originals.iterdir()}, retained
            )

    def test_final_answer_prefix_is_exactly_the_supported_inference_prefix(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            derived = paired_source.derive(failure, correction, originals)
            example = chat.training_examples([derived], "final_answer", chat.NATIVE)[0]
            tokenizer = ChatTokenizer()
            encoded = chat.encode_native_turns(tokenizer, example, 1024)
            self.assertEqual(len(encoded), 1)
            prefix = tokenizer.encode(chat.render_prompt(tokenizer, example["input"]))
            target = tokenizer.encode(correction["final_answer"] + "<eos>\n")
            self.assertEqual(
                (encoded[0]["input_ids"], encoded[0]["labels"]),
                (prefix + target, [-100] * len(prefix) + target),
            )
            messages, duplicates = chat.training_messages(example)
            self.assertEqual(
                (messages, duplicates),
                (
                    [
                        {"role": "user", "content": example["input"], "train": False},
                        {
                            "role": "assistant",
                            "content": correction["final_answer"],
                            "train": True,
                        },
                    ],
                    0,
                ),
            )

    def test_unbound_trajectory_observations_cannot_become_training_context(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            retained = {path.name: path.read_bytes() for path in originals.iterdir()}
            for append_answer in (False, True):
                changed_failure = copy.deepcopy(failure)
                if append_answer:
                    changed_failure["trajectory"].append(
                        {
                            "index": len(changed_failure["trajectory"]),
                            "actor": "environment",
                            "kind": "observation",
                            "content": correction["final_answer"],
                            "executed": False,
                            "receipt_sha256": None,
                        }
                    )
                derived = paired_source.derive(changed_failure, correction, originals)
                self.assertEqual(
                    derived["original_pair"],
                    {"failure": changed_failure, "correction": correction},
                )
                for protocol in (chat.LEGACY, chat.NATIVE):
                    with self.subTest(append_answer=append_answer, protocol=protocol):
                        with self.assertRaisesRegex(ValueError, "final_answer only"):
                            chat.training_examples([derived], "trajectory", protocol)
                        example = chat.training_examples(
                            [derived], "final_answer", protocol
                        )[0]
                        messages, _ = chat.training_messages(example)
                        self.assertEqual(
                            messages[:-1],
                            [
                                {
                                    "role": "user",
                                    "content": failure["task"]["input"],
                                    "train": False,
                                }
                            ],
                        )
                        self.assertNotIn(
                            correction["final_answer"],
                            [message["content"] for message in messages[:-1]],
                        )
            self.assertEqual(
                {path.name: path.read_bytes() for path in originals.iterdir()}, retained
            )

    def test_recorded_fixture_feedback_remains_supported_for_ordinary_records(self):
        tokenizer = ChatTokenizer()
        ordinary = record()
        ordinary["trajectory"] = [
            {
                "index": 0,
                "actor": "student",
                "kind": "action",
                "content": "0",
                "executed": False,
                "trainable": False,
                "receipt_sha256": None,
            },
            {
                "index": 1,
                "actor": "environment",
                "kind": "observation",
                "content": "Fixture artifact check failed: observed 0, expected 1.",
                "executed": False,
                "receipt_sha256": None,
            },
            {
                "index": 2,
                "actor": "curator",
                "kind": "correction",
                "content": ordinary["final_answer"],
                "executed": False,
                "receipt_sha256": None,
            },
        ]
        before = copy.deepcopy(ordinary)
        example = chat.training_examples([ordinary], "trajectory", chat.NATIVE)[0]
        encoded = chat.encode_native_turns(tokenizer, example, 1024)
        history = [
            {"role": "user", "content": ordinary["task"]["input"]},
            {"role": "assistant", "content": ordinary["trajectory"][0]["content"]},
            {"role": "tool", "content": ordinary["trajectory"][1]["content"]},
        ]
        prefix = tokenizer.encode(
            chat.render_prompt(tokenizer, ordinary["task"]["input"], history)
        )
        self.assertEqual(len(encoded), 1)
        self.assertEqual(
            (
                encoded[0]["input_ids"][: len(prefix)],
                encoded[0]["labels"][: len(prefix)],
            ),
            (prefix, [-100] * len(prefix)),
        )
        self.assertEqual(
            [value for value in encoded[0]["labels"] if value != -100],
            tokenizer.encode(ordinary["final_answer"] + "<eos>\n"),
        )
        self.assertEqual(
            (encoded[0]["dropped_terminal_duplicates"], ordinary), (1, before)
        )
        without_feedback = copy.deepcopy(ordinary)
        del without_feedback["trajectory"][1]
        without_feedback["trajectory"][1]["index"] = 1
        example = chat.training_examples([without_feedback], "trajectory", chat.NATIVE)[
            0
        ]
        with self.assertRaisesRegex(ValueError, "user or tool observation"):
            chat.encode_native_turns(tokenizer, example, 1024)


if __name__ == "__main__":
    unittest.main()
