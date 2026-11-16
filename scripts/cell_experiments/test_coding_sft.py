"""Pure preprocessing/identity controls; these are not model-training evidence."""

import tempfile
from pathlib import Path
import unittest

from .coding_sft import bound_file, encode_example, prompt_text, train, write_new


class CharacterTokenizer:
    eos_token_id = 0

    def encode(self, value, add_special_tokens=False):
        return list(value.encode())


class PreprocessingTests(unittest.TestCase):
    def test_observation_is_present_but_never_a_target(self):
        example = {
            "record_id": "task",
            "input": "fix",
            "segments": [
                {"role": "tool", "content": "ENV", "train": False},
                {"role": "assistant", "content": "ok", "train": True},
            ],
        }
        result = encode_example(CharacterTokenizer(), example, 128)
        prefix = len(prompt_text("fix").encode())
        self.assertEqual(result["input_ids"][prefix : prefix + 3], list(b"ENV"))
        self.assertEqual(result["labels"][prefix : prefix + 3], [-100] * 3)
        self.assertEqual([n for n in result["labels"] if n != -100], [111, 107, 0])

    def test_long_trace_rejected_instead_of_silently_truncated(self):
        example = {
            "record_id": "long",
            "input": "x",
            "segments": [{"role": "assistant", "content": "x" * 40, "train": True}],
        }
        with self.assertRaisesRegex(ValueError, "no truncation"):
            encode_example(CharacterTokenizer(), example, 32)

    def test_output_is_create_only_and_model_file_is_confined(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_new(root / "result.json", {"observed": True})
            with self.assertRaises(FileExistsError):
                write_new(root / "result.json", {"observed": False})
            self.assertEqual(bound_file(root, "result.json"), root / "result.json")
            with self.assertRaises(ValueError):
                bound_file(root, "../result.json")
            with self.assertRaises(ValueError):
                bound_file(root, str(root / "result.json"))

    def test_unfrozen_training_data_is_rejected_before_loading_a_model(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "records or mode"):
                train(
                    [{"source_id": "source-A"}],
                    {},
                    temporary,
                    {
                        "train_sources": ["source-A"],
                        "training_records_digest": "0" * 64,
                        "training_mode": "final_answer",
                    },
                    "final_answer",
                    "rejected",
                )
            failure = json.loads(
                (Path(temporary) / "models/rejected/FAILED.json").read_text()
            )
            self.assertEqual(
                (failure["status"], failure["automatic_retry"]), ("FAILED", False)
            )


if __name__ == "__main__":
    unittest.main()
