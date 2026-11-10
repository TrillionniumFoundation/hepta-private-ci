import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from . import candidate_expansion as expansion
from . import ocr


class CandidateExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "public.png"
        Image.new("RGB", (40, 60), (250, 240, 230)).save(self.path)
        self.args = dict(
            prompt="Read address",
            image_path=self.path,
            source_size=(80, 120),
            observation_bbox=[0, 0, 80, 120],
            expected_observation_sha256=hashlib.sha256(
                self.path.read_bytes()
            ).hexdigest(),
            expected_profile_sha256=expansion.digest(expansion.profile()),
        )
        self.lines = [
            dict(
                text=text,
                confidence=0.8,
                bbox=[1, 2 + i * 10, 30, 8 + i * 10],
                origin="pixel_ocr",
                words=[],
            )
            for i, text in enumerate(
                ("Three Jalan", "Fourth Taman", "Town Street", "Country")
            )
        ]

    def test_original_prefix_and_features_are_bitwise_preserved(self):
        original_args = {
            k: v for k, v in self.args.items() if not k.startswith("expected_")
        }
        base, features = ocr.candidate_features(self.lines, **original_args)
        result, expanded, receipt = expansion.expand_candidates(self.lines, **self.args)
        self.assertEqual(result[: len(base)], base)
        self.assertEqual(expanded[: len(base)].tobytes(), features.tobytes())
        self.assertEqual(
            [c["text"] for c in result[len(base) :]],
            [
                "Three Jalan Fourth Taman Town Street",
                "Fourth Taman Town Street Country",
            ],
        )
        self.assertEqual(expanded.shape, (len(base) + 2, ocr.FEATURE_WIDTH))
        self.assertTrue(np.isfinite(expanded).all())
        self.assertEqual(receipt["added_candidates"], 2)
        self.assertEqual(receipt["added_provenance"][0]["line_indices"], [0, 1, 2])
        self.assertEqual(expanded[len(base), 113], np.float32(len(base) / 128))
        self.assertGreater(receipt["wall_seconds"], 0)

    def test_registered_public_text_spans_do_not_cross_into_pixel_ocr(self):
        result, _, receipt = expansion.expand_candidates(
            self.lines, **self.args, public_text="Public One\nPublic Two\nPublic Three"
        )
        additions = result[receipt["base_candidates"] :]
        self.assertEqual(
            additions[0],
            dict(
                text="Public One Public Two Public Three",
                bbox=[0, 0, 80, 120],
                origin="registered_public_text",
            ),
        )
        self.assertEqual(len(additions), 3)
        self.assertFalse(
            any("Public Three Three Jalan" in c["text"] for c in additions)
        )

    def test_cap_preserves_base_without_inventing_known_base_truncation(self):
        public = "\n".join(f"Public Line {i}" for i in range(128))
        result, features, receipt = expansion.expand_candidates(
            [], **self.args, public_text=public
        )
        self.assertEqual(
            (len(result), len(features), receipt["added_candidates"]), (128, 128, 0)
        )
        self.assertTrue(receipt["base_at_cap"])
        self.assertIsNone(receipt["base_truncation"])
        self.assertEqual(
            (
                receipt["eligible_unique_extensions"],
                receipt["dropped_by_extension_limit"],
                receipt["dropped_by_candidate_cap"],
            ),
            (126, 62, 64),
        )

    def test_unrelated_field_retains_exact_original_output(self):
        args = {**self.args, "prompt": "Read date"}
        result, features, receipt = expansion.expand_candidates(self.lines, **args)
        base, original = ocr.candidate_features(
            self.lines,
            **{k: v for k, v in args.items() if not k.startswith("expected_")},
        )
        self.assertEqual(result, base)
        self.assertEqual(features.tobytes(), original.tobytes())
        self.assertEqual(receipt["eligible_unique_extensions"], 0)

    def test_wrong_pins_and_reference_fields_are_rejected(self):
        for name in ("expected_observation_sha256", "expected_profile_sha256"):
            with self.assertRaises(ValueError):
                expansion.expand_candidates(self.lines, **{**self.args, name: "0" * 64})
        with self.assertRaises(ValueError):
            expansion.expand_candidates(
                [{**self.lines[0], "reference": "private"}], **self.args
            )
        with self.assertRaises(TypeError):
            expansion.expand_candidates(
                self.lines, **self.args, expected_text="private"
            )
        with self.assertRaises(ValueError):
            expansion.expand_candidates(
                self.lines, **self.args, public_text="line\n" * 257
            )

    def test_loaded_code_cannot_publish_new_disk_source_pins(self):
        name = "_candidate_expansion_source_fixture"
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / name
            package.mkdir()
            (package / "__init__.py").write_bytes(b"")
            for module in (ocr, expansion):
                (package / Path(module.__file__).name).write_bytes(
                    Path(module.__file__).read_bytes()
                )
            try:
                with patch.object(sys, "path", [tmp, *sys.path]):
                    loaded = importlib.import_module(name + ".candidate_expansion")
                original_function = loaded.ocr.candidate_features
                frozen = loaded.profile()
                disk = package / "ocr.py"
                original = disk.read_bytes()
                changed = original.replace(
                    b"return candidates, np.stack(vectors)",
                    b"candidates[0]['text'] = 'DISK_V2'\n    return candidates, np.stack(vectors)",
                )
                self.assertNotEqual(original, changed)
                disk.write_bytes(changed)
                new_pin = loaded.digest(
                    {**frozen, "base_ocr_sha256": hashlib.sha256(changed).hexdigest()}
                )
                with self.assertRaises(ValueError):
                    loaded.profile()
                with self.assertRaises(ValueError):
                    loaded.expand_candidates(
                        self.lines, **{**self.args, "expected_profile_sha256": new_pin}
                    )
                self.assertIs(loaded.ocr.candidate_features, original_function)
                disk.write_bytes(original)
                own = package / "candidate_expansion.py"
                own.write_bytes(own.read_bytes() + b"\n# changed after import\n")
                with self.assertRaises(ValueError):
                    loaded.profile()
            finally:
                for key in list(sys.modules):
                    if key == name or key.startswith(name + "."):
                        sys.modules.pop(key)

    def test_preloaded_old_ocr_is_not_used_for_new_source_profile(self):
        name = "_candidate_expansion_preloaded_fixture"
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / name
            package.mkdir()
            (package / "__init__.py").write_bytes(b"")
            for module in (ocr, expansion):
                (package / Path(module.__file__).name).write_bytes(
                    Path(module.__file__).read_bytes()
                )
            try:
                with patch.object(sys, "path", [tmp, *sys.path]):
                    preloaded = importlib.import_module(name + ".ocr")
                    disk = package / "ocr.py"
                    disk.write_bytes(
                        disk.read_bytes().replace(
                            b"return candidates, np.stack(vectors)",
                            b"candidates[0]['text'] = 'DISK_V2'\n    return candidates, np.stack(vectors)",
                        )
                    )
                    loaded = importlib.import_module(name + ".candidate_expansion")
                result, _, _ = loaded.expand_candidates(
                    self.lines,
                    **{
                        **self.args,
                        "expected_profile_sha256": loaded.digest(loaded.profile()),
                    },
                )
                self.assertEqual(result[0]["text"], "DISK_V2")
                original_args = {
                    k: v for k, v in self.args.items() if not k.startswith("expected_")
                }
                baseline, _ = preloaded.candidate_features(self.lines, **original_args)
                self.assertEqual(baseline[0]["text"], "Three Jalan")
                self.assertIsNot(loaded.ocr, preloaded)
            finally:
                for key in list(sys.modules):
                    if key == name or key.startswith(name + "."):
                        sys.modules.pop(key)


if __name__ == "__main__":
    unittest.main()
