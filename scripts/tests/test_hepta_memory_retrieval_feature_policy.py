import json
from pathlib import Path
import tempfile
import unittest

from scripts import hepta_memory_retrieval_feature_policy as policy


class FeaturePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        crate = self.root / "codex-rs/hepta-memory-retrieval"
        crate.mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            "[package]\nname = \"codex-hepta-memory-retrieval\"\nversion = \"0.0.0\"\n"
            "[features]\ndefault = []\nlegacy-uncontrolled-retrieval = []\n",
            encoding="utf-8",
        )
        guide = self.root / "docs/modules/memory.retrieval/CONTROLLED_API.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("controlled\n", encoding="utf-8")
        composition = self.root / "qualification/memory-retrieval/product-composition.json"
        composition.parent.mkdir(parents=True)
        composition.write_text(
            json.dumps(
                {
                    "controlledApi": {
                        "defaultFeatures": [],
                        "legacyFeature": "legacy-uncontrolled-retrieval",
                        "legacyFeatureProductionAllowed": False,
                        "workControlRequired": True,
                        "absoluteDeadlineForwardingRequired": True,
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_valid_contract_passes(self):
        self.assertEqual(policy.audit(self.root), [])

    def test_nonempty_default_features_fail(self):
        manifest = self.root / policy.CRATE_MANIFEST
        manifest.write_text(
            "[package]\nname = \"codex-hepta-memory-retrieval\"\nversion = \"0.0.0\"\n"
            "[features]\ndefault = [\"legacy-uncontrolled-retrieval\"]\n"
            "legacy-uncontrolled-retrieval = []\n",
            encoding="utf-8",
        )
        self.assertIn("default features must be empty", policy.audit(self.root)[0])

    def test_product_crate_cannot_enable_legacy_feature(self):
        manifest = self.root / "codex-rs/product/Cargo.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "[package]\nname = \"product\"\nversion = \"0.0.0\"\n"
            "[dependencies]\ncodex-hepta-memory-retrieval = { path = \"../hepta-memory-retrieval\", "
            "features = [\"legacy-uncontrolled-retrieval\"] }\n",
            encoding="utf-8",
        )
        self.assertIn("enables or mentions", policy.audit(self.root)[0])

    def test_product_composition_must_keep_legacy_disabled(self):
        composition = self.root / policy.COMPOSITION
        data = json.loads(composition.read_text(encoding="utf-8"))
        data["controlledApi"]["legacyFeatureProductionAllowed"] = True
        composition.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(
            any("legacyFeatureProductionAllowed" in row for row in policy.audit(self.root))
        )

    def test_missing_guide_fails(self):
        (self.root / policy.CONTROLLED_API_GUIDE).unlink()
        self.assertIn("missing", policy.audit(self.root)[0])


if __name__ == "__main__":
    unittest.main()
