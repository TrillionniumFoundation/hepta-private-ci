"""Protocol alignment tests; fixture tokenization is not model quality evidence."""

import copy
import unittest

from . import chat_protocol as chat
from .coding_sft import encode_example, prompt_text
from .test_data import record


class ChatTokenizer:
    eos_token_id = 0

    def encode(self, text, add_special_tokens=False):
        return list(text.replace("<eos>", "\0").encode())

    def decode(
        self, ids, skip_special_tokens=False, clean_up_tokenization_spaces=False
    ):
        return bytes(ids).decode().replace("\0", "<eos>")

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        rendered = "".join(
            "[" + message["role"] + "]\n" + message["content"] + "<eos>\n"
            for message in messages
        )
        if add_generation_prompt:
            rendered += "[assistant]\n"
        return self.encode(rendered) if tokenize else rendered


def check_native_tokenizer(tokenizer):
    """Run manually with the pinned real AutoTokenizer; no weights or downloads.

    Returns measured token lengths only after exact prefix/masking assertions
    pass. This verifies serialization, not generated answers or model quality.
    """
    rows = []
    for index, target in enumerate(
        (
            '{"path":"src/math.py","old":"a - b","new":"a + b"}',
            '{"label":"结果","value":4}',
            '  {"text":"line\\nnext"}\n',
        )
    ):
        example = {
            "record_id": f"tokenizer-contract-{index}",
            "input": "Repair this repository; return exactly one JSON edit.",
            "segments": [
                {
                    "role": "assistant",
                    "content": "wrong",
                    "train": True,
                    "actor": "student",
                },
                {
                    "role": "tool",
                    "content": "Test failed: expected 4, observed 2.",
                    "train": False,
                },
                {
                    "role": "assistant",
                    "content": '{"edits":[]}',
                    "train": True,
                    "kind": "action",
                },
                {
                    "role": "tool",
                    "content": "Test failed: no assertions executed.",
                    "train": False,
                },
                {
                    "role": "assistant",
                    "content": target,
                    "train": True,
                    "kind": "correction",
                },
                {"role": "tool", "content": "Test passed.", "train": False},
                {
                    "role": "assistant",
                    "content": target,
                    "train": True,
                    "kind": "final_answer",
                },
            ],
        }
        messages, _ = chat.training_messages(example)
        turns = chat.encode_native_turns(tokenizer, example, 2048)
        assert len(turns) == 2
        for encoded in turns:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in messages[: encoded["message_index"]]
            ]
            prefix = tokenizer.encode(
                prompt_text(example["input"], tokenizer, chat.NATIVE, history),
                add_special_tokens=False,
            )
            assert encoded["input_ids"][: len(prefix)] == prefix
            assert encoded["labels"][: len(prefix)] == [-100] * len(prefix)
            assert encoded["dropped_terminal_duplicates"] == 1
            supervised = [n for n in encoded["labels"] if n != -100]
            assert supervised.count(tokenizer.eos_token_id) == 1
            complete = tokenizer.apply_chat_template(
                chat._wire(messages[: encoded["message_index"] + 1]),
                tokenize=False,
                add_generation_prompt=False,
            )
            assert (
                tokenizer.decode(
                    encoded["input_ids"],
                    skip_special_tokens=False,
                    clean_up_tokenization_spaces=False,
                )
                == complete
            )
            rows.append(
                {
                    "record_id": example["record_id"],
                    "turn_index": encoded["turn_index"],
                    "input_tokens": len(encoded["input_ids"]),
                    "supervised_tokens": encoded["supervised_tokens"],
                    "inference_prefix_tokens": len(prefix),
                    "whole_message_tokenization_differs": tokenizer.encode(
                        complete, add_special_tokens=False
                    )
                    != encoded["input_ids"],
                }
            )
    return {
        "status": "PASS",
        "scope": "native tokenizer serialization only",
        "cases": rows,
    }


class NativeChatTests(unittest.TestCase):
    def test_final_answer_prefix_is_exactly_the_inference_prompt(self):
        tokenizer = ChatTokenizer()
        example = {
            "record_id": "one",
            "input": "Apply one edit.",
            "segments": [
                {"role": "assistant", "content": '{"new":"ok"}', "train": True}
            ],
        }
        encoded = encode_example(tokenizer, example, 512, chat.NATIVE)
        prompt = tokenizer.encode(prompt_text(example["input"], tokenizer, chat.NATIVE))
        self.assertEqual(encoded["input_ids"][: len(prompt)], prompt)
        self.assertEqual(encoded["labels"][: len(prompt)], [-100] * len(prompt))
        self.assertEqual(
            encoded["labels"][len(prompt) :],
            tokenizer.encode('{"new":"ok"}<eos>\n'),
        )
        self.assertEqual(prompt_text("old"), "### User\nold\n### Assistant\n")

    def test_recovery_history_matches_training_and_masks_failed_actions(self):
        tokenizer = ChatTokenizer()
        example = {
            "record_id": "recovery",
            "input": "Fix the result.",
            "segments": [
                {
                    "role": "assistant",
                    "content": "BAD",
                    "train": True,
                    "actor": "student",
                    "kind": "action",
                },
                {
                    "role": "tool",
                    "content": "test failed",
                    "train": False,
                    "kind": "observation",
                },
                {
                    "role": "assistant",
                    "content": "GOOD",
                    "train": True,
                    "actor": "curator",
                    "kind": "correction",
                },
                {
                    "role": "tool",
                    "content": "test passed",
                    "train": False,
                    "kind": "observation",
                },
                {
                    "role": "assistant",
                    "content": "GOOD",
                    "train": True,
                    "actor": "answer",
                    "kind": "final_answer",
                },
            ],
        }
        before = copy.deepcopy(example)
        result = encode_example(tokenizer, example, 512, chat.NATIVE)
        history = [
            {"role": "user", "content": example["input"]},
            {"role": "assistant", "content": "BAD"},
            {"role": "tool", "content": "test failed"},
        ]
        prompt = tokenizer.encode(
            prompt_text(example["input"], tokenizer, chat.NATIVE, history)
        )
        self.assertEqual(result["input_ids"][: len(prompt)], prompt)
        self.assertEqual(result["labels"][: len(prompt)], [-100] * len(prompt))
        self.assertEqual(
            [t for t in result["labels"] if t != -100], tokenizer.encode("GOOD<eos>\n")
        )
        self.assertEqual((result["dropped_terminal_duplicates"], example), (1, before))
        self.assertIn(b"[user]\nTool observation:\ntest failed", bytes(prompt))

    def test_explicit_event_supervision_and_exact_native_deduplication(self):
        item = record()
        item["trajectory"][1].update(
            actor="student", content=item["final_answer"], trainable=False
        )
        example = chat.native_examples([item], "trajectory")[0]
        messages, duplicates = chat.training_messages(example)
        self.assertEqual(
            ([m["train"] for m in messages], duplicates),
            ([False, False, False, True], 0),
        )
        item["trajectory"][1]["trainable"] = True
        messages, duplicates = chat.training_messages(
            chat.native_examples([item], "trajectory")[0]
        )
        self.assertEqual(
            ([m["train"] for m in messages], duplicates), ([False, False, True], 1)
        )
        item["final_answer"] += " "
        _, duplicates = chat.training_messages(
            chat.native_examples([item], "trajectory")[0]
        )
        self.assertEqual(duplicates, 0)
        item["trajectory"][1]["trainable"] = "false"
        with self.assertRaisesRegex(ValueError, "explicit boolean"):
            chat.native_examples([item], "trajectory")

    def test_legacy_trajectory_honors_the_explicit_failed_action_mask(self):
        item = record()
        event = item["trajectory"][1]
        event.update(actor="student", content="FAILED-ACTION", trainable=False)
        tokenizer = ChatTokenizer()

        def encode():
            example = chat.training_examples([item], "trajectory", chat.LEGACY)[0]
            return encode_example(tokenizer, example, 1024)

        masked = encode()
        start = bytes(masked["input_ids"]).index(b"FAILED-ACTION")
        end = start + len(event["content"])
        self.assertEqual(masked["labels"][start:end], [-100] * (end - start))
        self.assertEqual(
            [token for token in masked["labels"] if token != -100],
            tokenizer.encode(item["final_answer"]) + [tokenizer.eos_token_id],
        )
        del event["trainable"]
        legacy = encode()
        self.assertEqual(legacy["input_ids"], masked["input_ids"])
        self.assertEqual(
            legacy["labels"][start:end], tokenizer.encode(event["content"])
        )
        event["trainable"] = "false"
        with self.assertRaisesRegex(ValueError, "explicit boolean"):
            encode()

    def test_final_answer_sft_preserves_the_same_initial_recovery_messages(self):
        tokenizer, item = ChatTokenizer(), record()
        item["task"]["messages"] = [
            {"role": "user", "content": item["task"]["input"]},
            {"role": "assistant", "content": "wrong attempt"},
            {"role": "tool", "content": "actual test failed"},
        ]
        example = chat.native_examples([item], "final_answer")[0]
        result = encode_example(tokenizer, example, 1024, chat.NATIVE)
        prefix = tokenizer.encode(
            prompt_text(
                item["task"]["input"], tokenizer, chat.NATIVE, item["task"]["messages"]
            )
        )
        self.assertEqual(result["input_ids"][: len(prefix)], prefix)
        self.assertEqual(result["labels"][: len(prefix)], [-100] * len(prefix))
        self.assertEqual(
            [n for n in result["labels"] if n != -100],
            tokenizer.encode(item["final_answer"] + "<eos>\n"),
        )

    def test_unsupported_history_boundaries_and_overflow_fail_closed(self):
        tokenizer = ChatTokenizer()
        for messages in (
            [{"role": "user", "content": "rewritten"}],
            [{"role": "user", "content": "task", "gold": "secret"}],
            [
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": "unfinished"},
            ],
        ):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                prompt_text("task", tokenizer, chat.NATIVE, messages)
        example = {
            "record_id": "large",
            "input": "task",
            "segments": [{"role": "assistant", "content": "target", "train": True}],
        }
        with self.assertRaisesRegex(ValueError, "no truncation"):
            encode_example(tokenizer, example, 16, chat.NATIVE)

        class UnstableTokenizer(ChatTokenizer):
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                value = super().apply_chat_template(
                    messages,
                    tokenize=tokenize,
                    add_generation_prompt=add_generation_prompt,
                )
                return (
                    "unstable" + value
                    if not tokenize and add_generation_prompt
                    else value
                )

        with self.assertRaisesRegex(ValueError, "prefix-stable"):
            encode_example(UnstableTokenizer(), example, 512, chat.NATIVE)

    def test_each_supervised_turn_uses_its_actual_generation_prefix(self):
        class MergingTokenizer(ChatTokenizer):
            def encode(self, text, add_special_tokens=False):
                return super().encode(text.replace("\n ", "X"), add_special_tokens)

        tokenizer = MergingTokenizer()
        example = {
            "record_id": "spaces",
            "input": "task",
            "segments": [
                {"role": "assistant", "content": "  first", "train": True},
                {"role": "tool", "content": "test failed", "train": False},
                {"role": "assistant", "content": "  second", "train": True},
            ],
        }
        turns = chat.encode_native_turns(tokenizer, example, 512)
        messages, _ = chat.training_messages(example)
        self.assertEqual(len(turns), 2)
        for turn in turns:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in messages[: turn["message_index"]]
            ]
            prefix = tokenizer.encode(
                prompt_text("task", tokenizer, chat.NATIVE, history)
            )
            self.assertEqual(turn["input_ids"][: len(prefix)], prefix)
            self.assertEqual(turn["labels"][: len(prefix)], [-100] * len(prefix))
            full = tokenizer.apply_chat_template(
                chat._wire(messages[: turn["message_index"] + 1]),
                tokenize=True,
                add_generation_prompt=False,
            )
            self.assertNotEqual(turn["input_ids"], full)
        with self.assertRaisesRegex(ValueError, "multiple native targets"):
            encode_example(tokenizer, example, 512, chat.NATIVE)

    def test_termination_distinguishes_eos_at_the_cap_from_truncation(self):
        self.assertEqual(
            chat.generation_termination([3, 4], 0, 2),
            {
                "finish_reason": "max_new_tokens",
                "eos_seen": False,
                "hit_output_limit": True,
                "max_new_tokens": 2,
            },
        )
        self.assertEqual(
            chat.generation_termination([3, 0], 0, 2),
            {
                "finish_reason": "eos_token",
                "eos_seen": True,
                "hit_output_limit": False,
                "max_new_tokens": 2,
            },
        )


if __name__ == "__main__":
    unittest.main()
