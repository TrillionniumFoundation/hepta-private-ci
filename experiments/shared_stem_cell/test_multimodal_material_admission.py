"""V6 real safetensors + actual Ed25519 verification, research-only tests.

A tiny deterministic fixture exercises the material protocol. No pretrained
publisher, neural effectiveness or physical production attestation is tested.
"""
from __future__ import annotations

from copy import deepcopy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from safetensors.torch import save_file
import torch

from multimodal_alignment_contract import canonical, sha
from multimodal_bridge import ContractError
from multimodal_candidate_gate import PLAN, validate_plan
from multimodal_material_admission import (
    CLAIM_SCHEMA, DOMAIN, REPORT_SCHEMA, TRUST_SCHEMA,
    admission, inspect_weight_material,
)
from multimodal_real_encoder import PROFILE_SCHEMA


def pin(text: str) -> str:
    return sha(text.encode())


class OfflineMaterialAdmissionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.snapshot_root = self.root / "snapshot"
        self.snapshot_root.mkdir()
        save_file({"encoder.token.weight": torch.arange(12, dtype=torch.float32).reshape(4, 3),
                   "encoder.projection.weight": torch.eye(3, dtype=torch.float32)},
                  self.snapshot_root / "model.safetensors")
        (self.snapshot_root / "config.json").write_text('{"model_type":"bert"}', encoding="utf-8")
        inventory = {p.name: sha(p.read_bytes()) for p in self.snapshot_root.iterdir()}
        snapshot = {"revision": "a" * 40, "kind": "encoder", "files": inventory}
        self.profile = {"schema": PROFILE_SCHEMA, "candidate": "tiny_random",
                        "snapshot": snapshot, "expected_width": 3, "maximum_tokens": 32,
                        "batch_size": 4, "pooling": "attention-mask-mean", "normalization": "none"}
        self.profile_sha = sha(canonical(self.profile))
        self.snapshot_sha = sha(canonical(snapshot))
        self.plan = {"schema": PLAN, "scope": "scope_A", "train_sha256": pin("train"),
                     "future_source_sha256": pin("future-source"), "future_targets_sha256": pin("future-target"),
                     "train_group_sha256s": sorted([pin("g1"), pin("g2")]), "train_cutoff": 10,
                     "future_start": 20, "future_end": 40, "classes": 2, "train_steps": 4,
                     "head_parameters": 1024, "seed": 7,
                     "hardware_sha256": pin("host"), "environment_sha256": pin("env"),
                     "candidates": [{"name": "no_change", "profile_sha256": pin("no-profile"),
                                     "snapshot_sha256": pin("no-snapshot")},
                                    {"name": "tiny_random", "profile_sha256": self.profile_sha,
                                     "snapshot_sha256": self.snapshot_sha}]}
        validate_plan(self.plan)
        self.plan_sha = sha(canonical(self.plan))
        self.private = Ed25519PrivateKey.generate()
        self.key = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.trust = {"schema": TRUST_SCHEMA, "issuer": "hepta-independent-operator-lab",
                      "public_key_ed25519_hex": self.key.hex(),
                      "allowed_models": [{"candidate": "tiny_random", "upstream_repo": "fixture/local-bert",
                                          "expected_width": 3, "kind": "encoder",
                                          "minimum_floating_elements": 21,
                                          "maximum_floating_elements": 21}],
                      "revoked_snapshot_sha256s": [], "revoked_key_sha256s": []}
        self.trust_sha = sha(canonical(self.trust))
        self.now = 1_800_000_000
        claim = {"schema": CLAIM_SCHEMA, "issuer": self.trust["issuer"],
                 "signed": {"candidate": "tiny_random", "plan_sha256": self.plan_sha,
                            "profile_sha256": self.profile_sha, "snapshot_sha256": self.snapshot_sha,
                            "upstream_repo": "fixture/local-bert", "upstream_revision": "a" * 40,
                            "saved_floating_tensor_elements": 21,
                            "issued_at": self.now - 60, "expires_at": self.now + 3600}}
        self.claim = self.sign(claim)

    def sign(self, claim: dict) -> dict:
        fields = {k: claim[k] for k in ("schema", "issuer", "signed")}
        signature = self.private.sign(DOMAIN + canonical(fields))
        return {**fields, "signature_ed25519_hex": signature.hex()}

    def verify(self, **kwargs) -> dict:
        values = dict(plan=self.plan, plan_sha256=self.plan_sha, profile=self.profile,
                      profile_sha256=self.profile_sha, snapshot_root=self.snapshot_root,
                      trust=self.trust, trust_sha256=self.trust_sha, assertion=self.claim,
                      assertion_sha256=sha(canonical(self.claim)), now_seconds=self.now)
        values.update(kwargs)
        return admission(**values)

    def test_real_file_and_operator_signature_both_verified_but_not_pretrained(self):
        report = self.verify()
        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertEqual(report["saved_floating_tensor_elements"], 21)
        self.assertEqual(report["saved_tensor_count"], 2)
        self.assertTrue(report["local_snapshot_bytes_verified"])
        self.assertTrue(report["operator_review_signature_verified"])
        for k in ("model_publisher_authenticated", "actual_pretraining_proven", "task_efficacy_proven",
                  "independent_ndu_verified", "worker_final_use_authorized", "production_accepted"):
            self.assertFalse(report[k], k)

    def test_wrong_untrusted_signer_or_changed_signature_rejected(self):
        alternate = Ed25519PrivateKey.generate()
        altered = deepcopy(self.claim)
        altered["signature_ed25519_hex"] = alternate.sign(DOMAIN + canonical({k:altered[k] for k in ("schema", "issuer", "signed")})).hex()
        with self.assertRaises(ContractError):
            self.verify(assertion=altered, assertion_sha256=sha(canonical(altered)))
        altered = deepcopy(self.claim)
        altered["signature_ed25519_hex"] = "0" * 128
        with self.assertRaises(ContractError):
            self.verify(assertion=altered, assertion_sha256=sha(canonical(altered)))

    def test_self_provided_new_key_does_not_override_external_operator_store_pin(self):
        other = deepcopy(self.trust)
        other["public_key_ed25519_hex"] = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw).hex()
        with self.assertRaises(ContractError):
            self.verify(trust=other)  # pinned SHA is still the operator's original store

    def test_signed_claim_cannot_switch_model_or_plan_without_resigning(self):
        for key, value in (("candidate", "granite_97m"), ("upstream_revision", "b"*40),
                           ("plan_sha256", pin("alternate")), ("snapshot_sha256", pin("other"))):
            altered = deepcopy(self.claim)
            altered["signed"][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.verify(assertion=altered, assertion_sha256=sha(canonical(altered)))

    def test_stale_or_future_or_overlong_claim_rejected(self):
        for issued, expires in ((self.now-4000, self.now-1), (self.now+1, self.now+500),
                                (self.now-20, self.now+31*86400)):
            doc = deepcopy(self.claim)
            doc["signed"]["issued_at"] = issued
            doc["signed"]["expires_at"] = expires
            doc = self.sign(doc)
            with self.subTest(t=(issued,expires)), self.assertRaises(ContractError):
                self.verify(assertion=doc, assertion_sha256=sha(canonical(doc)))

    def test_revocations_rejected_even_with_valid_signature(self):
        cases = [("revoked_snapshot_sha256s", self.snapshot_sha),
                 ("revoked_key_sha256s", sha(self.key))]
        for field, val in cases:
            changed = deepcopy(self.trust)
            changed[field] = [val]
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.verify(trust=changed, trust_sha256=sha(canonical(changed)))

    def test_tampered_weight_or_config_file_blocks_signed_claim(self):
        for name in ("model.safetensors", "config.json"):
            path = self.snapshot_root / name
            saved = path.read_bytes()
            try:
                path.write_bytes(saved + b"tamper")
                with self.subTest(name=name), self.assertRaises(ContractError):
                    self.verify()
            finally:
                path.write_bytes(saved)

    def test_missing_or_extra_file_blocks_verification(self):
        new = self.snapshot_root / "unlisted.json"
        new.write_text("{}", encoding="utf-8")
        with self.assertRaises(ContractError):
            self.verify()
        new.unlink()
        file = self.snapshot_root / "config.json"
        saved = file.read_bytes()
        file.unlink()
        try:
            with self.assertRaises(ContractError):
                self.verify()
        finally:
            file.write_bytes(saved)

    def test_symlink_model_root_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.snapshot_root, target_is_directory=True)
        with self.assertRaises(ContractError):
            self.verify(snapshot_root=link)

    def test_wrong_actual_tensor_count_even_with_genuine_signature_rejected(self):
        claim = deepcopy(self.claim)
        claim["signed"]["saved_floating_tensor_elements"] = 22
        claim = self.sign(claim)
        changed = deepcopy(self.trust)
        changed["allowed_models"][0]["maximum_floating_elements"] = 22
        with self.assertRaises(ContractError):
            self.verify(trust=changed, trust_sha256=sha(canonical(changed)),
                        assertion=claim, assertion_sha256=sha(canonical(claim)))

    def test_snapshot_declared_width_must_match_external_policy(self):
        changed = deepcopy(self.trust)
        changed["allowed_models"][0]["expected_width"] = 384
        with self.assertRaises(ContractError):
            self.verify(trust=changed, trust_sha256=sha(canonical(changed)))

    def test_candidate_needs_exact_precommitted_plan_and_profile(self):
        changed = deepcopy(self.plan)
        changed["seed"] += 1
        with self.assertRaises(ContractError):
            self.verify(plan=changed, plan_sha256=self.plan_sha)
        profile = deepcopy(self.profile)
        profile["normalization"] = "unit_l2"
        with self.assertRaises(ContractError):
            self.verify(profile=profile, profile_sha256=sha(canonical(profile)))

    def test_real_safetensors_header_inventory_is_read(self):
        result = inspect_weight_material(self.snapshot_root, self.profile["snapshot"])
        self.assertEqual(result["saved_all_tensor_elements"], 21)
        self.assertEqual(result["safetensors_shards"], 1)
        self.assertEqual(result["snapshot_sha256"], self.snapshot_sha)

    def test_cli_new_receipt_contains_no_model_capability_promotion(self):
        files = {}
        for name, doc in (("plan", self.plan), ("profile", self.profile),
                          ("trust", self.trust), ("claim", self.claim)):
            p = self.root / (name + ".json")
            p.write_bytes(canonical(doc))
            files[name] = p
        # CLI time uses actual wall clock; sign a fresh bounded claim.
        doc = deepcopy(self.claim)
        doc["signed"]["issued_at"] = int(time.time()) - 30
        doc["signed"]["expires_at"] = int(time.time()) + 3600
        doc = self.sign(doc)
        files["claim"].write_bytes(canonical(doc))
        dest = self.root / "receipt.json"
        cmd = [sys.executable, str(Path(__file__).with_name("multimodal_material_admission.py")),
               "--plan", str(files["plan"]), "--plan-sha256", self.plan_sha,
               "--profile", str(files["profile"]), "--profile-sha256", self.profile_sha,
               "--model-snapshot", str(self.snapshot_root),
               "--operator-trust", str(files["trust"]), "--operator-trust-sha256", self.trust_sha,
               "--signed-claim", str(files["claim"]), "--signed-claim-sha256", sha(canonical(doc)),
               "--output", str(dest)]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(dest.read_bytes())
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["actual_pretraining_proven"])
        self.assertTrue(result["operator_review_signature_verified"])
        self.assertNotIn("private_key", json.dumps(result))
        replay = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        self.assertNotEqual(replay.returncode, 0)  # never overwrite receipt

    def test_v5_nonfixture_cli_mandatorily_requires_all_v6_material_inputs(self):
        from multimodal_pinned_candidate import _v6_material_gate
        args = SimpleNamespace(candidate="granite_97m", profile_sha256=self.profile_sha,
                               model_snapshot=self.snapshot_root, operator_trust=None,
                               operator_trust_sha256=None, signed_claim=None,
                               signed_claim_sha256=None)
        with self.assertRaises(ContractError):
            _v6_material_gate(args, self.plan, self.plan_sha, self.profile)
        args.candidate = "tiny_random"
        self.assertIsNone(_v6_material_gate(args, self.plan, self.plan_sha, self.profile))
        args.operator_trust_sha256 = self.trust_sha
        with self.assertRaises(ContractError):
            _v6_material_gate(args, self.plan, self.plan_sha, self.profile)

    def test_v5_reviewed_path_rechecks_real_file_with_operator_signature(self):
        from multimodal_pinned_candidate import _v6_material_gate
        profile = deepcopy(self.profile)
        profile["candidate"] = "reviewed_tiny"
        profile_sha = sha(canonical(profile))
        plan = deepcopy(self.plan)
        plan["candidates"][-1]["name"] = "reviewed_tiny"
        plan["candidates"][-1]["profile_sha256"] = profile_sha
        plan_sha = sha(canonical(plan))
        trust = deepcopy(self.trust)
        trust["allowed_models"][0]["candidate"] = "reviewed_tiny"
        claim = deepcopy(self.claim)
        claim["signed"]["candidate"] = "reviewed_tiny"
        claim["signed"]["profile_sha256"] = profile_sha
        claim["signed"]["plan_sha256"] = plan_sha
        claim["signed"]["issued_at"] = int(time.time()) - 5
        claim["signed"]["expires_at"] = int(time.time()) + 90
        claim = self.sign(claim)
        files = {}
        for name, doc in (("operator-trust", trust), ("operator-claim", claim)):
            path = self.root / (name + ".json")
            path.write_bytes(canonical(doc))
            files[name] = path
        args = SimpleNamespace(candidate="reviewed_tiny", profile_sha256=profile_sha,
                               model_snapshot=self.snapshot_root,
                               operator_trust=files["operator-trust"],
                               operator_trust_sha256=sha(canonical(trust)),
                               signed_claim=files["operator-claim"],
                               signed_claim_sha256=sha(canonical(claim)))
        receipt = _v6_material_gate(args, plan, plan_sha, profile)
        self.assertTrue(receipt["operator_review_signature_verified"])
        self.assertFalse(receipt["actual_pretraining_proven"])
        self.assertFalse(receipt["production_accepted"])
        model_path = self.snapshot_root / "model.safetensors"
        original = model_path.read_bytes()
        try:
            model_path.write_bytes(original + b"tamper")
            with self.assertRaises(ContractError):
                _v6_material_gate(args, plan, plan_sha, profile)
        finally:
            model_path.write_bytes(original)

    def test_v5_cannot_accept_different_signed_claim_at_prediction_gate(self):
        from multimodal_pinned_candidate import _v6_material_gate
        args = SimpleNamespace(candidate="mmbert_small", profile_sha256=self.profile_sha,
                               model_snapshot=self.snapshot_root, operator_trust=None,
                               operator_trust_sha256=None, signed_claim=None,
                               signed_claim_sha256=None)
        with self.assertRaises(ContractError):
            _v6_material_gate(args, self.plan, self.plan_sha, self.profile)



if __name__ == "__main__":
    unittest.main()
