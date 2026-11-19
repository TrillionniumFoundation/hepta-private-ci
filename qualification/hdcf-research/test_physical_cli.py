"""Original disk-byte CLI tests: no TEST target access in training process."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from physical_bank import Denied
from physical_cli import read_document, write_once
from test_physical_bank import original


class TwoProcessCLI(unittest.TestCase):
    def test_real_separate_process_train_and_review(self):
        bundle, targets = original()
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            features, held_targets, predictions, reviewed = (d / n for n in
                ("features.json", "targets.json", "predictions.json", "review.json"))
            write_once(str(features), bundle)
            write_once(str(held_targets), targets)
            cmd = [sys.executable, str(Path(__file__).with_name("physical_cli.py"))]
            result = subprocess.run(cmd + ["train", "--features", str(features), "--out", str(predictions)],
                                    capture_output=True, text=True, timeout=20, check=True)
            self.assertEqual(result.stdout, "")
            self.assertIn("predictions", read_document(str(predictions)))
            # Second physically separate OS process is the only process receiving blind targets.
            subprocess.run(cmd + ["review", "--predictions", str(predictions),
                                  "--targets", str(held_targets), "--out", str(reviewed)],
                           capture_output=True, text=True, timeout=20, check=True)
            review = read_document(str(reviewed))
            self.assertEqual(review["results"]["split"]["n"], 32)
            self.assertFalse(review["independent_source_authenticated"])
            with self.assertRaises(FileExistsError):
                write_once(str(predictions), {"tamper": True})

    def test_bad_duplicate_json_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            for bad in (b'{"a":1,"a":2}', b'{"a": NaN}', b'{"a": Infinity}'):
                p.write_bytes(bad)
                with self.assertRaises(Denied):
                    read_document(str(p))

    def test_symlink_denied(self):
        with tempfile.TemporaryDirectory() as td:
            p, link = Path(td) / "input", Path(td) / "link"
            p.write_text('{}')
            link.symlink_to(p)
            with self.assertRaises(OSError):
                read_document(str(link))
            with self.assertRaises(FileExistsError):
                write_once(str(link), {"tamper": True})

    def test_train_cli_cannot_accept_target_arg(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "original.json"
            write_once(str(p), original()[0])
            cmd = [sys.executable, str(Path(__file__).with_name("physical_cli.py")),
                   "train", "--features", str(p), "--out", str(Path(td) / "output.json"),
                   "--targets", str(Path(td) / "targets.json")]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(td) / "output.json").exists())


if __name__ == "__main__":
    unittest.main()
