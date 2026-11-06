"""Preserve the historic ORIGINAL source byte and callable identities."""

import shutil
import tempfile
from pathlib import Path
import unittest

from historical_reader_format_source import SOURCE_PINS, locked_reader_format


class ReaderFormatHistoricalTests(unittest.TestCase):
    def test_old_source_bytes_are_pinned_not_latest_formatted_code(self):
        prompt, reader, sha = locked_reader_format()
        self.assertEqual(set(sha), set(SOURCE_PINS))
        self.assertEqual(
            sha["prompt_representation_probe.py"],
            SOURCE_PINS["prompt_representation_probe.py"][1],
        )
        self.assertEqual(
            sha["offline_smol_reader.py"], SOURCE_PINS["offline_smol_reader.py"][1]
        )
        self.assertEqual(tuple(prompt.STYLES), ("verbatim", "normalized"))
        self.assertTrue(reader.PINS["model.safetensors"])

    def test_mutated_historical_source_is_rejected(self):
        root = Path(__file__).parent / "frozen_source"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name, (snapshot, _) in SOURCE_PINS.items():
                shutil.copyfile(root / snapshot, target / snapshot)
            first = next(iter(SOURCE_PINS.values()))[0]
            with (target / first).open("ab") as stream:
                stream.write(b"\n# tampered historical source\n")
            with self.assertRaisesRegex(ValueError, "original source bytes changed"):
                locked_reader_format(target)

    def test_missing_historical_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "missing or unsafe"):
                locked_reader_format(directory)


if __name__ == "__main__":
    unittest.main()
