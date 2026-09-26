from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from control_engineering_v2.plasticity_bridge import MutationGrammarManifestV1
from control_engineering_v2.plasticity_bridge import PlasticityBridgeError
from control_engineering_v2.plasticity_bridge import load_mutation_grammar_manifest_v1
from control_engineering_v2.plasticity_bridge import project_parameter_mutation_policy_v1


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "qualification"
    / "fixtures"
    / "learning.plasticity"
    / "mutation-grammar-projection-v1.json"
)


class PlasticityBridgeTests(unittest.TestCase):
    def fixture(self) -> dict[str, object]:
        with FIXTURE.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def test_cross_module_golden_matches_rust_policy_encoding(self) -> None:
        raw = self.fixture()
        manifest = load_mutation_grammar_manifest_v1(FIXTURE)
        self.assertEqual(manifest.semantic_digest(), raw["semanticDigest"])
        projection = project_parameter_mutation_policy_v1(
            manifest,
            policy_id=str(raw["expectedPlasticityPolicyId"]),
        )
        self.assertEqual(
            projection.policy_digest,
            raw["expectedPlasticityPolicyDigest"],
        )
        self.assertEqual(
            projection.mutation_grammar_digest,
            raw["semanticDigest"],
        )
        self.assertEqual(
            [rule.parameter_id for rule in projection.rules],
            ["parameter:a", "parameter:b"],
        )

    def test_rule_order_is_semantically_canonical(self) -> None:
        raw = self.fixture()
        reversed_value = copy.deepcopy(raw)
        reversed_value["rules"] = list(reversed(reversed_value["rules"]))
        left = MutationGrammarManifestV1.from_mapping(raw)
        right = MutationGrammarManifestV1.from_mapping(reversed_value)
        self.assertEqual(left, right)
        self.assertEqual(left.semantic_digest(), right.semantic_digest())

    def test_each_semantic_field_changes_the_manifest_digest(self) -> None:
        original = self.fixture()
        expected = MutationGrammarManifestV1.from_mapping(original).semantic_digest()
        mutations = []

        changed = copy.deepcopy(original)
        changed["manifestId"] = "grammar:plasticity:changed"
        mutations.append(changed)

        changed = copy.deepcopy(original)
        changed["selectedArtifactDigest"] = "1" * 64
        mutations.append(changed)

        changed = copy.deepcopy(original)
        changed["window"]["windowId"] = "window:changed"
        mutations.append(changed)

        changed = copy.deepcopy(original)
        changed["window"]["windowDigest"] = "2" * 64
        mutations.append(changed)

        for field, value in (
            ("parameterId", "parameter:changed"),
            ("layerId", "layer:changed"),
            ("surface", "authority"),
            ("minimumDeltaRawQ32", -101),
            ("maximumDeltaRawQ32", 101),
        ):
            changed = copy.deepcopy(original)
            changed["rules"][1][field] = value
            mutations.append(changed)

        for changed in mutations:
            self.assertNotEqual(
                expected,
                MutationGrammarManifestV1.from_mapping(changed).semantic_digest(),
            )

    def test_duplicate_unknown_and_inverted_rules_fail_closed(self) -> None:
        duplicate = self.fixture()
        duplicate["rules"][0]["parameterId"] = duplicate["rules"][1]["parameterId"]
        with self.assertRaisesRegex(PlasticityBridgeError, "duplicate parameterId"):
            MutationGrammarManifestV1.from_mapping(duplicate)

        unknown = self.fixture()
        unknown["rules"][0]["surface"] = "ambient_authority"
        with self.assertRaisesRegex(PlasticityBridgeError, "unsupported mutation surface"):
            MutationGrammarManifestV1.from_mapping(unknown)

        inverted = self.fixture()
        inverted["rules"][0]["minimumDeltaRawQ32"] = 201
        with self.assertRaisesRegex(PlasticityBridgeError, "inverted mutation bounds"):
            MutationGrammarManifestV1.from_mapping(inverted)


if __name__ == "__main__":
    unittest.main()
