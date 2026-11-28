"""Batch encoding through actual local sources; no user data or model-quality claim."""

import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import chat_protocol as chat, data, paired_opaque_teacher, paired_source
from .test_chat_protocol import ChatTokenizer
from .test_data import record
from .test_opaque_teacher_data import fixture
from .test_paired_source import capture


def derived_pair(root, name):
    originals = root / "originals"
    originals.mkdir(mode=0o700, exist_ok=True)
    failure = capture(root, "failure-" + name, "0", "a" * 64, {"action": "0"}, 1)
    draft, source, _ = fixture()
    draft["record_id"] = "correction-" + name
    for key in ("task_id", "lineage_id", "project_id", "task"):
        draft[key] = copy.deepcopy(failure[key])
    draft["authorization"]["training_allowed"] = True
    source["items"][0]["sdk_payload"]["content"][0]["text"] = draft["task"]["input"]
    raw = data.canonical(source)
    draft["source"].update(
        repository=failure["source"]["repository"],
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    paired_source._publish_bytes(originals / draft["source"]["sha256"], raw)
    correction = paired_opaque_teacher.capture_correction(
        draft,
        originals,
        root / ("correction-" + name + ".json"),
        prompt_item_id="u",
        answer_item_id="a",
        student_policy_sha256="a" * 64,
    )
    return paired_source.derive(failure, correction, originals)


class OpaqueBatchTests(unittest.TestCase):
    def test_distinct_opaque_and_mixed_batches_preserve_each_encoded_example(self):
        with TemporaryDirectory() as tmp:
            first = derived_pair(Path(tmp), "first")
            second = derived_pair(Path(tmp), "second")
            tokenizer = ChatTokenizer()
            for rows in ([first, second], [first, record(), second], [record(), first]):
                before = copy.deepcopy(rows)
                for protocol in (chat.LEGACY, chat.NATIVE):
                    for mode in ("final_answer", "trajectory"):
                        with self.subTest(
                            protocol=protocol, mode=mode, count=len(rows)
                        ):
                            if mode == "trajectory":
                                with self.assertRaisesRegex(
                                    ValueError, "final_answer only"
                                ):
                                    chat.training_examples(rows, mode, protocol)
                                self.assertEqual(rows, before)
                                continue
                            expected = [
                                chat.training_examples([row], mode, protocol)[0]
                                for row in rows
                            ]
                            examples = chat.training_examples(rows, mode, protocol)
                            self.assertEqual(examples, expected)
                            self.assertEqual(rows, before)
                            for row, example in zip(rows, examples):
                                if row["schema"] != paired_opaque_teacher.DERIVED:
                                    continue
                                messages, duplicates = chat.training_messages(example)
                                self.assertEqual(
                                    (
                                        [m["content"] for m in messages if m["train"]],
                                        duplicates,
                                    ),
                                    (["1"], 0),
                                )
                                self.assertNotIn(
                                    "1", [m["content"] for m in messages[:-1]]
                                )
                                encoded = chat.encode_native_turns(
                                    tokenizer, example, 1024
                                )
                                self.assertEqual(len(encoded), 1)
                                self.assertEqual(
                                    [
                                        value
                                        for value in encoded[0]["labels"]
                                        if value != -100
                                    ],
                                    tokenizer.encode("1<eos>\n"),
                                )

    def test_duplicate_ids_are_refused_within_and_across_profiles(self):
        with TemporaryDirectory() as tmp:
            derived = derived_pair(Path(tmp), "one")
            ordinary = record()
            ordinary["record_id"] = derived["record_id"]
            for rows in ([derived, derived], [ordinary, derived], [ordinary, ordinary]):
                with (
                    self.subTest(count=len(rows)),
                    self.assertRaisesRegex(ValueError, "duplicate record id"),
                ):
                    chat.training_examples(rows, "final_answer", chat.NATIVE)

    def test_mixed_batches_keep_permissions_failure_masks_and_original_admission(self):
        with TemporaryDirectory() as tmp:
            derived = derived_pair(Path(tmp), "one")
            cases = []
            for split in ("selection", "confirmation"):
                cases.append([derived, record(1, split)])
            denied = record()
            denied["authorization"]["training_allowed"] = False
            cases.append([derived, denied])
            failed = record()
            failed["verified_outcome"]["success"] = False
            cases.append([failed, derived])
            changed = copy.deepcopy(derived)
            changed["trajectory"][0]["trainable"] = True
            cases.append([record(), changed])
            changed = copy.deepcopy(derived)
            changed["original_pair"]["correction"]["authorization"][
                "training_allowed"
            ] = False
            cases.append([changed, record()])
            cases.append([record(), derived["original_pair"]["correction"]])
            for rows in cases:
                for protocol in (chat.LEGACY, chat.NATIVE):
                    with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                        chat.training_examples(rows, "final_answer", protocol)

    def test_opaque_dispatch_retains_the_existing_batch_size_contract(self):
        with TemporaryDirectory() as tmp:
            derived = derived_pair(Path(tmp), "one")
            for rows in ([], (derived,), [derived] * (data.MAX_RECORDS + 1)):
                with self.assertRaisesRegex(ValueError, "bounded records"):
                    chat.training_examples(rows, "final_answer", chat.NATIVE)


if __name__ == "__main__":
    unittest.main()
