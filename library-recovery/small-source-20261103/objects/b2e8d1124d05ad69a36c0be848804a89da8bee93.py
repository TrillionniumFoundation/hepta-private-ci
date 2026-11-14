"""Offline synthetic fixture tests; none assert that genuine weights were run."""
import copy
from pathlib import Path
import tempfile
import unittest

from public_stem_material_v8 import CATALOG, canonical
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
        result, entry = collect(self.roots)
        self.assertEqual(sorted(entry), sorted(CATALOG))
        self.assertTrue(result["two_material_directories_rehashed"])
        self.assertTrue(result["research_pair_self_consistent"])
        for field in ("production_accepted", "ndu_promotion_authorized",
                      "no_change_baseline_executed", "matched_training_completed",
                      "independent_future_efficacy_verified",
                      "paired_physical_execution_independently_attested"):
            self.assertFalse(result[field], field)
        out = self.root / "published"
        publish(out, result, entry)
        self.assertEqual(len(list(out.iterdir())), 5)
        self.assertFalse(any(p.suffix == ".safetensors" for p in out.iterdir()))

    def test_cli_output_is_atomic_and_second_attempt_rejected(self):
        args = ["--mmbert-root", str(self.roots["mmbert-small"]),
                "--granite-root", str(self.roots["granite-97m-r2"]),
                "--output", str(self.root / "out")]
        self.assertEqual(main(args), 0)
        self.assertEqual(main(args), 2)

    def test_missing_model_and_candidate_swap_refuse_without_publishing(self):
        target = self.root / "no-result"
        (self.roots["mmbert-small"] / "model" / "model.safetensors").unlink()
        self.assertEqual(main(["--mmbert-root", str(self.roots["mmbert-small"]),
                               "--granite-root", str(self.roots["granite-97m-r2"]),
                               "--output", str(target)]), 2)
        self.assertFalse(target.exists())
        with self.assertRaises(AdmissionError):
            collect({"mmbert-small": self.roots["granite-97m-r2"],
                     "granite-97m-r2": self.roots["granite-97m-r2"]})

    def test_changed_physical_input_or_material_bytes_fail_closed(self):
        for name in sorted(CATALOG):
            with self.subTest(candidate=name):
                receipt = self.roots[name] / "physical-receipt.json"
                import json
                data = json.loads(receipt.read_bytes())
                data["probe_input_sha256"] = "f" * 64
                receipt.write_bytes(canonical(data))
                with self.assertRaisesRegex(AdmissionError, "input census"):
                    collect(self.roots)
                from public_stem_material_v8 import PROBE_TEXTS, probe_input_digest
                data["probe_input_sha256"] = probe_input_digest(PROBE_TEXTS)
                receipt.write_bytes(canonical(data))
                assert collect(self.roots)[0]["research_pair_self_consistent"]
        image = self.roots["granite-97m-r2"] / "model" / "model.safetensors"
        image.write_bytes(b"tamper-even-if-same-length-123")
        with self.assertRaises(AdmissionError):
            collect(self.roots)

    def test_symlink_input_is_rejected(self):
        link = self.root / "borrowed"
        link.symlink_to(self.roots["granite-97m-r2"], target_is_directory=True)
        with self.assertRaisesRegex(AdmissionError, "linked"):
            collect({"mmbert-small": self.roots["mmbert-small"],
                     "granite-97m-r2": link})


if __name__ == "__main__":
    unittest.main()
