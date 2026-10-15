"""Tests for official publisher identity vs user-provided candidate alias."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from multimodal_bridge import ContractError
from multimodal_public_identity_v12 import require_public_native_profile
from public_stem_material_v8 import CATALOG
from public_stem_handoff_v9 import handoff
from test_public_stem_handoff_v9 import fixture as v10_material_fixture
from multimodal_pinned_candidate import _v6_material_gate


def candidate(label):
    name = "mmbert-small" if "mmbert" in label else "granite-97m-r2"
    source = CATALOG[name]
    profile = dict(candidate=label, expected_width=source["width"],
                   pooling=source["pooling"], normalization=source["normalization"],
                   snapshot={"kind": source["kind"], "revision": "a"*40, "files": {}})
    policy = dict(upstream_repo=source["repo_id"], expected_width=source["width"],
                  kind=source["kind"])
    return profile, policy


class OfficialSourceIdentityTests(unittest.TestCase):
    def test_old_and_new_names_have_identical_native_profile(self):
        for alias in ("mmbert_small", "mmbert-small", "granite_97m", "granite-97m-r2"):
            with self.subTest(alias=alias):
                profile, policy = candidate(alias)
                self.assertTrue(require_public_native_profile(alias, profile, policy))

    def test_rename_cannot_skip_granite_cls_and_l2(self):
        for alias in ("granite_97m", "granite-97m-r2"):
            profile, policy = candidate(alias)
            for field, value in (("pooling", "attention-mask-mean"),
                                 ("normalization", "none"), ("expected_width", 256),
                                 ("candidate", "unrelated")):
                with self.subTest(alias=alias, field=field), self.assertRaisesRegex(
                        ContractError, "native profile"):
                    require_public_native_profile(alias, {**profile, field: value}, policy)

    def test_cross_publisher_label_and_trusted_source_must_match(self):
        for alias in ("mmbert_small", "mmbert-small", "granite_97m", "granite-97m-r2"):
            profile, policy = candidate(alias)
            wrong = dict(policy, upstream_repo=(CATALOG["mmbert-small"]["repo_id"]
                 if "granite" in alias else CATALOG["granite-97m-r2"]["repo_id"]))
            with self.subTest(alias=alias), self.assertRaisesRegex(ContractError, "upstream identity"):
                require_public_native_profile(alias, profile, wrong)
            with self.subTest(alias=alias), self.assertRaisesRegex(ContractError, "upstream identity"):
                require_public_native_profile("false_public_model", profile, policy)

    def test_native_mmbert_policy_is_an_explicit_research_baseline(self):
        for alias in ("mmbert_small", "mmbert-small"):
            profile, policy = candidate(alias)
            self.assertTrue(require_public_native_profile(alias, profile, policy))
            with self.assertRaisesRegex(ContractError, "native profile"):
                require_public_native_profile(alias, {**profile, "pooling": "cls-first-token"}, policy)

    def test_real_v10_profile_shape_matches_v5_reviewed_public_families(self):
        # Use the V10 profile itself, not a hand-typed width approximation.
        for original in CATALOG:
            with self.subTest(candidate=original), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan, material, physical = v10_material_fixture(root, original)
                profile, _ = handoff(plan, material, physical, root)
                policy = dict(upstream_repo=CATALOG[original]["repo_id"],
                              expected_width=384, kind=CATALOG[original]["kind"])
                self.assertTrue(require_public_native_profile(original, profile, policy))

    def test_v5_nonfixture_admission_rechecks_verified_model_family(self):
        # Synthetic signed-admission SUBSTITUTE, not a real signature or evidence.
        for name in ("granite_97m", "granite-97m-r2", "mmbert_small", "mmbert-small"):
            profile, policy = candidate(name)
            args = SimpleNamespace(candidate=name,
                operator_trust=Path("trust.json"), operator_trust_sha256="a"*64,
                signed_claim=Path("claim.json"), signed_claim_sha256="b"*64,
                profile_sha256="c"*64, model_snapshot=Path("model"))
            trust = {"allowed_models": [{**policy, "candidate": name}]}
            def loader(path, digest):
                return trust if path.name == "trust.json" else {"fixture_claim": True}
            with (patch("multimodal_pinned_candidate.load_pinned_document", side_effect=loader),
                  patch("multimodal_material_admission.admission", return_value={"test_only": True})):
                self.assertEqual(_v6_material_gate(args, {}, "plan", profile), {"test_only": True})
                trust = {"allowed_models": [{**policy, "candidate": name,
                    "upstream_repo": "research/other-model"}]}
                with self.assertRaisesRegex(ContractError, "trusted upstream identity"):
                    _v6_material_gate(args, {}, "plan", profile)

    def test_future_nonpublic_models_still_require_v6_but_not_public_profile(self):
        p = dict(upstream_repo="research/internal-bounded-model", expected_width=256, kind="encoder")
        self.assertFalse(require_public_native_profile("new_stem", {}, p))
        with self.assertRaises(ContractError):
            require_public_native_profile("new_stem", {},
                                          dict(p, upstream_repo=CATALOG["mmbert-small"]["repo_id"]))


if __name__ == "__main__":
    unittest.main()
