"""Keep hosted frozen binary chunks out of prose spelling, without hiding text.

Source-level scope test only: the required Codespell workflow still runs
normally and must pass independently. No model/CI authority is granted.
"""
from configparser import ConfigParser
from fnmatch import fnmatchcase
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HostedBinaryCodespellAdmissionTests(unittest.TestCase):
    def test_binary_shard_pattern_is_narrow_and_required(self):
        config = ConfigParser(interpolation=None)
        self.assertEqual(config.read(ROOT / ".codespellrc", encoding="utf-8"),
                         [str(ROOT / ".codespellrc")])
        patterns = [item.strip() for item in config["codespell"]["skip"].split(",")]
        shard_pattern = "*v4_hosted/inputs/chunks/part-*.bin"
        self.assertEqual(patterns.count(shard_pattern), 1)
        paths = {
            "./experiments/multimodal_output_portfolio/v4_hosted/inputs/chunks/part-00007.bin": True,
            "experiments/multimodal_output_portfolio/v4_hosted/inputs/chunks/part-00001.bin": True,
            "experiments/multimodal_output_portfolio/v4_hosted/inputs/chunks/README.md": False,
            "experiments/multimodal_output_portfolio/v4_hosted/inputs/manifest.json": False,
            "experiments/multimodal_output_portfolio/v4_hosted/inputs/chunks/part-00007.binx": False,
            "experiments/multimodal_output_portfolio/v4/portfolio.py": False,
            "experiments/multimodal_output_portfolio/v4_hosted/RESULTS.md": False,
            "scripts/tests/test_codespell_hosted_binary_admission.py": False,
            "other-research/inputs/chunks/part-00007.bin": False,
        }
        for path, expected in paths.items():
            with self.subTest(path=path):
                self.assertEqual(
                    any(fnmatchcase(path, pattern) for pattern in patterns),
                    expected,
                    "Only the known v4 binary shard family is excused.",
                )


if __name__ == "__main__":
    unittest.main()
