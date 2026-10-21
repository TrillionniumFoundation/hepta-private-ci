import importlib.util
import json
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name("stem_bakeoff.py")
MANIFEST_PATH = pathlib.Path(__file__).parents[2] / "docs" / "learning" / "STEM_BAKEOFF_MANIFEST.json"
spec = importlib.util.spec_from_file_location("stem_bakeoff", MODULE_PATH)
assert spec and spec.loader
stem_bakeoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stem_bakeoff)


class StemBakeoffTests(unittest.TestCase):
    def test_registered_manifest_is_valid(self):
        with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        self.assertEqual(stem_bakeoff.validate_manifest(manifest), [])

    def test_missing_cell_component_is_rejected(self):
        result = {
            "schema": stem_bakeoff.RESULT_SCHEMA,
            "authority": "qualification_only",
            "runtime_posture": stem_bakeoff.POSTURE,
            "candidate": "hepta_latent_150m",
            "artifact": {"digest": "sha256:test"},
            "metrics": {key: 0 for key in stem_bakeoff.REQUIRED_METRICS},
            "gates": {key: True for key in stem_bakeoff.REQUIRED_GATES},
            "cell_components": list(stem_bakeoff.CELL_COMPONENTS[:-1]),
        }
        self.assertIn(
            "cell_components must match the lightweight Cell contract",
            stem_bakeoff.validate_result(result),
        )

    def test_complete_result_is_accepted(self):
        result = {
            "schema": stem_bakeoff.RESULT_SCHEMA,
            "authority": "qualification_only",
            "runtime_posture": stem_bakeoff.POSTURE,
            "candidate": "embeddinggemma2_740m",
            "artifact": {"digest": "sha256:embeddinggemma2"},
            "metrics": {key: 0 for key in stem_bakeoff.REQUIRED_METRICS},
            "gates": {key: True for key in stem_bakeoff.REQUIRED_GATES},
            "cell_components": list(stem_bakeoff.CELL_COMPONENTS),
        }
        self.assertEqual(stem_bakeoff.validate_result(result), [])

    def test_unknown_candidate_is_rejected(self):
        result = {
            "schema": stem_bakeoff.RESULT_SCHEMA,
            "authority": "qualification_only",
            "runtime_posture": stem_bakeoff.POSTURE,
            "candidate": "per_cell_421m_copy",
            "artifact": {"digest": "sha256:unknown"},
            "metrics": {key: 0 for key in stem_bakeoff.REQUIRED_METRICS},
            "gates": {key: True for key in stem_bakeoff.REQUIRED_GATES},
            "cell_components": list(stem_bakeoff.CELL_COMPONENTS),
        }
        self.assertIn(
            "candidate is not a registered bake-off candidate",
            stem_bakeoff.validate_result(result),
        )

    def test_authority_cannot_be_smuggled_through_metadata(self):
        result = {
            "schema": stem_bakeoff.RESULT_SCHEMA,
            "authority": "qualification_only",
            "runtime_posture": {
                "mode": "SHADOW_ONLY",
                "authority": "GRANT_ALL",
                "release": "HOLD_NO_GO",
            },
            "candidate": "hepta_latent_300m",
        }
        self.assertIn(
            "runtime_posture must remain SHADOW_ONLY/DENY_ALL/HOLD_NO_GO",
            stem_bakeoff.validate_result(result),
        )


if __name__ == "__main__":
    unittest.main()
