"""Isolated small-reader experiment; never promote it to Qwen/production evidence."""

from pathlib import Path
import unittest

import yaml

from reader_reference import MODELS


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-smol-source-pilot.yml"
)


class SmolPilotTests(unittest.TestCase):
    def test_model_pin_is_the_historical_135m_not_the_qwen_reader(self):
        self.assertEqual(
            MODELS["smol-135m"],
            (
                "HuggingFaceTB/SmolLM2-135M-Instruct",
                "12fd25f77366fa6b3b4b768ec3050bf629380bac",
            ),
        )
        self.assertNotEqual(MODELS["smol-135m"], MODELS["qwen-3b"])

    def test_push_scope_and_concurrency_are_isolated(self):
        flow = yaml.safe_load(WORKFLOW.read_text())
        trigger = flow.get("on", flow.get(True))
        self.assertEqual(
            trigger["push"]["paths"],
            [".github/workflows/hepta-memory-smol-source-pilot.yml"],
        )
        self.assertEqual(
            flow["concurrency"]["group"],
            "memory-source-write-smol135-${{ github.sha }}",
        )
        self.assertFalse(flow["concurrency"]["cancel-in-progress"])
        self.assertEqual(flow["permissions"], {"contents": "read", "actions": "read"})

    def test_pinned_sources_same_seven_arms_and_full_suite(self):
        flow = yaml.safe_load(WORKFLOW.read_text())
        jobs = flow["jobs"]
        self.assertIn("repository-format", jobs)
        self.assertIn("just fmt --check", str(jobs["repository-format"]))
        self.assertEqual(jobs["write-and-read"]["needs"], "source-contracts")
        self.assertEqual(jobs["write-and-read"]["timeout-minutes"], 330)
        work = str(jobs["write-and-read"])
        for expected in (
            "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
            "35756b456f75718cc422d8678ec7ae97790ca36ced625501d24884698fddab24",
            "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897",
            "stage smol-135m",
            "source_write_effects.py",
            "test_*.py",
            "full-regression-exit-code.txt",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, work)

    def test_unsupported_projection_and_likelihood_are_not_fake_zeroes(self):
        flow = yaml.safe_load(WORKFLOW.read_text())
        steps = flow["jobs"]["write-and-read"]["steps"]
        names = [step.get("name", "") for step in steps]
        self.assertFalse(any("Prove source-only Qwen2.5-3B" in x for x in names))
        write = next(
            x["run"] for x in steps if x.get("name", "").startswith("Write observed")
        )
        self.assertNotIn("--loss-backend supervised_positions", write)
        self.assertNotIn("--parity-receipt", write)
        no_score = next(
            x["run"] for x in steps if "inapplicable Qwen-only" in x.get("name", "")
        )
        for literal in (
            "'available': False",
            "'unknown_not_zero': True",
            "'production_accepted': False",
        ):
            self.assertIn(literal, no_score)
        self.assertLess(
            names.index(
                "New process reloads both committed modules before task exposure"
            ),
            names.index(
                "Recompute seven-arm knowledge and policy effects from original answers"
            ),
        )


if __name__ == "__main__":
    unittest.main()
