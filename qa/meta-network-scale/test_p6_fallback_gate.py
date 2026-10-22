"""Offline P6 security regressions; ephemeral keys are test-only, never production."""
from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p6_fallback_gate import (
    DOMAIN, Decision, EvidenceRejected, assess_fallback, assess_signed_parity,
    canonical_bytes, strict_json, verify_envelope,
)


def d(char: str) -> str:
    return char * 64


class FallbackGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private = {role: Ed25519PrivateKey.generate() for role in (
            "final_use_issuer", "independent_observer", "native_owner", "codex_owner", "independent_evaluator"
        )}
        self.trust = {role: {role: key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()} for role, key in self.private.items()}
        self.req = dict(
            operation_id="op-1", scope_id="organ-a", generation=7,
            intent_digest=d("a"), payload_digest=d("b"), tool_id="tool-write",
            host_scope="host-a", idempotency_key="idem-1", owner_epoch=12,
            primary_backend="native", fallback_backend="codex",
        )
        self.grant = {k: v for k, v in self.req.items() if k not in ("primary_backend", "fallback_backend")}
        self.grant.update(expires_at_ms=9000, allowed_backends=["native", "codex"])
        self.observation = {k: v for k, v in self.req.items() if k != "fallback_backend"}
        self.observation.update(state="rejected_before_admission", dispatch_count=0, observation_digest=d("c"))

    def seal(self, role: str, payload: dict) -> dict:
        body = {"version": 1, "role": role, "key_id": role, "payload": copy.deepcopy(payload)}
        signature = self.private[role].sign(DOMAIN + canonical_bytes(body))
        return dict(body, signature=base64.b64encode(signature).decode("ascii"))

    def fallback(self, **kwargs):
        return assess_fallback(
            request=kwargs.get("req", self.req),
            final_use=kwargs.get("grant", self.seal("final_use_issuer", self.grant)),
            primary_observation=kwargs.get("obs", self.seal("independent_observer", self.observation)),
            trust=kwargs.get("trust", self.trust), now_ms=kwargs.get("now_ms", 8000),
        )

    def record(self, sandbox: str) -> dict:
        return {
            "case_id": "frozen-case", "task_digest": d("a"),
            "source_tree_digest": d("b"), "model_digest": d("c"),
            "policy_digest": d("d"), "budget_digest": d("e"),
            "hardware_digest": d("f"), "tool_digest": d("1"),
            "scope_id": "organ-a", "generation": 7, "sandbox_id": sandbox,
            "status": "completed", "dispatch_count": 1,
            "normalized_result_digest": d("2"), "state_before_digest": d("3"),
            "state_after_digest": d("4"), "effect_receipt_digest": d("5"),
            "failure_class": "none",
        }

    def pair(self, nrec=None, crec=None, eval_rec=None):
        n = self.seal("native_owner", nrec or self.record("native-sandbox"))
        c = self.seal("codex_owner", crec or self.record("codex-sandbox"))
        nn = verify_envelope(n, self.trust, "native_owner")
        cc = verify_envelope(c, self.trust, "codex_owner")
        ev = dict(case_id="frozen-case", native_envelope_digest=nn.envelope_digest,
                  codex_envelope_digest=cc.envelope_digest, heldout_digest=d("6"),
                  evaluator_policy_digest=d("7"), result="matched")
        if eval_rec:
            ev.update(eval_rec)
        return n, c, self.seal("independent_evaluator", ev)

    def test_positive_rejection_only_advisory(self):
        self.assertEqual(self.fallback(), Decision.ADVISORY_FALLBACK)

    def test_unknown_effect_never_falls_back(self):
        for state in ("admitted", "indeterminate", "timeout", "cancel_pending", "failed_after_dispatch"):
            with self.subTest(state=state):
                self.observation.update(state=state, dispatch_count=1)
                self.assertEqual(self.fallback(), Decision.RECONCILE_ONLY)

    def test_completed_never_falls_back(self):
        self.observation.update(state="completed", dispatch_count=1)
        self.assertEqual(self.fallback(), Decision.NO_FALLBACK_TERMINAL)

    def test_pre_rejection_with_dispatch_fails(self):
        self.observation["dispatch_count"] = 1
        with self.assertRaises(EvidenceRejected):
            self.fallback()

    def test_multiple_dispatches_fail(self):
        self.observation.update(state="indeterminate", dispatch_count=2)
        with self.assertRaises(EvidenceRejected):
            self.fallback()

    def test_expired_grant_fails(self):
        for now in (9000, 10000):
            with self.subTest(now=now), self.assertRaises(EvidenceRejected):
                self.fallback(now_ms=now)

    def test_tool_payload_generation_host_idempotency_binding(self):
        for k, v in (("tool_id", "other"), ("payload_digest", d("f")),
                     ("generation", 8), ("host_scope", "host-b"),
                     ("idempotency_key", "other"), ("owner_epoch", 13),
                     ("intent_digest", d("e")), ("scope_id", "other")):
            with self.subTest(field=k):
                req = dict(self.req, **{k: v})
                with self.assertRaises(EvidenceRejected):
                    self.fallback(req=req)

    def test_wrong_backend_or_unqualified_capability_fails(self):
        for request in (dict(self.req, fallback_backend="native"),
                        dict(self.req, fallback_backend="other")):
            with self.assertRaises(EvidenceRejected):
                self.fallback(req=request)
        self.grant["allowed_backends"] = ["native"]
        with self.assertRaises(EvidenceRejected):
            self.fallback()

    def test_signed_envelope_version_relabel_does_not_validate(self):
        original = self.seal("final_use_issuer", self.grant)
        for invalid_version in (True, 1.0, "1"):
            with self.subTest(version=invalid_version):
                altered = dict(original, version=invalid_version)
                # The signature was genuinely made over integer 1, not the
                # relabelled envelope; exact signed shape is mandatory.
                with self.assertRaises(EvidenceRejected):
                    self.fallback(grant=altered)

    def test_signature_mutation_fails(self):
        g = self.seal("final_use_issuer", self.grant)
        g["payload"]["expires_at_ms"] += 1000
        with self.assertRaises(EvidenceRejected):
            self.fallback(grant=g)
        o = self.seal("independent_observer", self.observation)
        o["payload"]["state"] = "rejected_before_admission"
        o["payload"]["dispatch_count"] += 1
        with self.assertRaises(EvidenceRejected):
            self.fallback(obs=o)

    def test_role_and_key_separation_fail(self):
        # Two signer identities with one public key are not independent.
        self.private["independent_observer"] = self.private["final_use_issuer"]
        self.trust["independent_observer"]["independent_observer"] = self.trust["final_use_issuer"]["final_use_issuer"]
        with self.assertRaises(EvidenceRejected):
            self.fallback()

    def test_malformed_extra_fields_fail(self):
        req = dict(self.req, smuggled_authority=True)
        with self.assertRaises(EvidenceRejected):
            self.fallback(req=req)
        g = dict(self.grant, unexpected=True)
        with self.assertRaises(EvidenceRejected):
            self.fallback(grant=self.seal("final_use_issuer", g))
        self.observation["dispatch_count"] = True  # bool is not a valid integer counter
        with self.assertRaises(EvidenceRejected):
            self.fallback()

    def test_duplicate_json_and_nonfinite_rejected(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(text=text), self.assertRaises(EvidenceRejected):
                strict_json(text)

    def test_exponent_overflow_is_never_valid_signed_evidence_json(self):
        # parse_constant alone misses JSON number overflow such as 1e999.
        for text in ('{"x":1e999}', '{"x":-1e999}', '{"x":3.0e10000}'):
            with self.subTest(text=text), self.assertRaises(EvidenceRejected):
                strict_json(text)

    def test_signed_pair_structural_parity_not_production(self):
        n, c, e = self.pair()
        result = assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)
        self.assertFalse(result["production_qualified"])
        self.assertEqual(result["case_id"], "frozen-case")

    def test_parity_input_cohort_mismatch(self):
        for k, v in (("source_tree_digest", d("9")), ("policy_digest", d("9")),
                     ("model_digest", d("9")), ("budget_digest", d("9")),
                     ("generation", 8), ("state_before_digest", d("9"))):
            rec = self.record("codex-sandbox")
            rec[k] = v
            n, c, e = self.pair(crec=rec)
            with self.subTest(field=k), self.assertRaises(EvidenceRejected):
                assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_parity_output_divergence(self):
        for k, v in (("normalized_result_digest", d("9")),
                     ("state_after_digest", d("9")), ("status", "failed"),
                     ("failure_class", "network")):
            rec = self.record("codex-sandbox")
            rec[k] = v
            n, c, e = self.pair(crec=rec)
            with self.subTest(field=k), self.assertRaises(EvidenceRejected):
                assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_parity_same_sandbox_for_effects_refused(self):
        n, c, e = self.pair(crec=self.record("native-sandbox"))
        with self.assertRaises(EvidenceRejected):
            assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_parity_unknown_or_multiple_dispatch_refused(self):
        for status, count in (("indeterminate", 1), ("completed", 2), ("rejected", 1), ("completed", 0)):
            nrec = self.record("native-sandbox")
            nrec.update(status=status, dispatch_count=count)
            n, c, e = self.pair(nrec=nrec)
            with self.subTest(status=status,count=count), self.assertRaises(EvidenceRejected):
                assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_parity_independent_evaluator_binds_both_envelopes(self):
        n, c, e = self.pair(eval_rec={"native_envelope_digest": d("9")})
        with self.assertRaises(EvidenceRejected):
            assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)
        n, c, e = self.pair(eval_rec={"result": "not_matched"})
        with self.assertRaises(EvidenceRejected):
            assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_denied_operation_must_have_no_effect(self):
        nrec = self.record("native-sandbox")
        nrec.update(status="rejected", dispatch_count=0, state_after_digest=d("4"))
        n, c, e = self.pair(nrec=nrec)
        with self.assertRaises(EvidenceRejected):
            assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)

    def test_parity_synthetic_untrusted_signature_refused(self):
        n, c, e = self.pair()
        n["signature"] = base64.b64encode(b"x" * 64).decode("ascii")
        with self.assertRaises(EvidenceRejected):
            assess_signed_parity(native=n, codex=c, evaluation=e, trust=self.trust)


if __name__ == "__main__":
    unittest.main()
