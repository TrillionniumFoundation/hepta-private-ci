"""Raw-byte identity, independent reopen and semantic/completion separation."""

import copy
from pathlib import Path
import tempfile
import unittest
import zipfile

import torch

from .media import RawMediaArchive, reopen_archive_records


class MediaTests(unittest.TestCase):
    def test_persist_reopen_dedup_and_completion_are_independent_of_truth(self):
        pixels = torch.zeros((3, 1, 28, 56))
        pixels[1, :, 3:8, 4:9] = 1
        tokens = torch.tensor([[1, 3, 14, 4, 15, 5, 6, 2],
                               [1, 3, 3, 2, 0, 0, 0, 0],
                               [1, 2, 0, 0, 0, 0, 0, 0]])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "actual.zip"
            with RawMediaArchive(path) as writer:
                decoded, captions, records = writer.append(pixels, tokens)
                self.assertEqual(writer.samples, 3)
            torch.testing.assert_close(decoded, pixels, rtol=0, atol=0)
            independent, strings = reopen_archive_records(path, records)
            torch.testing.assert_close(independent, pixels, rtol=0, atol=0)
            self.assertEqual(strings, captions)
            self.assertEqual([row["required_output_complete"] for row in records],
                             [True, True, False])
            self.assertEqual(records[0]["image_sha256"], records[2]["image_sha256"])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(len(archive.namelist()), 5)
            with self.assertRaises(FileExistsError):
                RawMediaArchive(path)
            corrupted = copy.deepcopy(records)
            corrupted[0]["text_sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                reopen_archive_records(path, corrupted)

    def test_soft_probabilities_cannot_be_substituted_for_actual_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            with RawMediaArchive(Path(temporary) / "actual.zip") as writer:
                with self.assertRaises(ValueError):
                    writer.append(torch.full((1, 1, 28, 56), .5),
                                  torch.tensor([[1, 2, 0, 0, 0, 0, 0, 0]]))


if __name__ == "__main__":
    unittest.main()
