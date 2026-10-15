"""Offline fake artifacts; no real pretrained forward or model-quality claims."""
import json
from pathlib import Path
import tempfile
import unittest

from public_stem_material_v8 import CATALOG, PROBE_TEXTS, canonical, probe_input_digest
from public_stem_handoff_v9 import AdmissionError
from public_stem_pair_handoff_v10 import collect, publish, main
from test_public_stem_handoff_v9 import fixture


class PairHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roots = {}
        for name in sorted(CATALOG):
            path = self.root / name
            path.mkdir()
            model = path / "model"
            model.mkdir()
            plan, material, physical = fixture(model, name)
            for label, value in (("pinned-plan.json", plan),
                                 ("material-receipt.json", material),
                                 ("physical-receipt.json", physical)):
                (path / label).write_bytes(canonical(value))
            self.roots[name] = path

    def test_both_materials_rehashed_and_non_authorizing(self):
        summary, entries = collect(self.roots)
        self.assertEqual(sorted(entries), sorted(CATALOG))
        self.assertTrue(summary["two_material_directories_rehashed"])
        self.assertTrue(summary["research_pair_self_consistent"])
        for field in ("production_accepted", "ndu_promotion_authorized",
                      "no_change_baseline_executed", "matched_training_completed",
                      "independent_future_efficacy_verified",
                      "paired_physical_execution_independently_attested"):
            self.assertFalse(summary[field], field)
        output = self.root / "published"
        publish(output, summary, entries)
        self.assertEqual(len(list(output.iterdir())), 5)
        self.assertFalse(any(x.suffix == ".safetensors" for x in output.iterdir()))

    def test_cli_atomic_output_and_repeat_rejected(self):
        args = ["--mmbert-root", str(self.roots["mmbert-small"]),
                "--granite-root", str(self.roots["granite-97m-r2"]),
                "--output", str(self.root / "out")]
        self.assertEqual(main(args), 0)
        self.assertEqual(main(args), 2)

    def test_missing_material_or_candidate_alias_fails_closed(self):
        out = self.root / "not-published"
        (self.roots["mmbert-small"] / "model" / "model.safetensors").unlink()
        self.assertEqual(main(["--mmbert-root", str(self.roots["mmbert-small"]),
                               "--granite-root", str(self.roots["granite-97m-r2"]),
                               "--output", str(out)]), 2)
        self.assertFalse(out.exists())
        with self.assertRaises(AdmissionError):
            collect({"mmbert-small": self.roots["granite-97m-r2"],
                     "granite-97m-r2": self.roots["granite-97m-r2"]})

    def test_changed_physical_input_and_model_bytes_refused(self):
        for name in sorted(CATALOG):
            receipt = self.roots[name] / "physical-receipt.json"
            physical = json.loads(receipt.read_bytes())
            physical["probe_input_sha256"] = "f" * 64
            receipt.write_bytes(canonical(physical))
            with self.subTest(name=name), self.assertRaisesRegex(AdmissionError, "input census"):
                collect(self.roots)
            physical["probe_input_sha256"] = probe_input_digest(PROBE_TEXTS)
            receipt.write_bytes(canonical(physical))
            self.assertTrue(collect(self.roots)[0]["research_pair_self_consistent"])
        model = self.roots["granite-97m-r2"] / "model" / "model.safetensors"
        model.write_bytes(b"tampered-weight-file")
        with self.assertRaises(AdmissionError):
            collect(self.roots)

    def test_symlinked_candidate_root_refused(self):
        link = self.root / "borrowed"
        link.symlink_to(self.roots["granite-97m-r2"], target_is_directory=True)
        with self.assertRaisesRegex(AdmissionError, "linked"):
            collect({"mmbert-small": self.roots["mmbert-small"],
                     "granite-97m-r2": link})


if __name__ == "__main__":
    unittest.main()
