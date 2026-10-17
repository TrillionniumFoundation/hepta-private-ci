import unittest

from cell_fast_path_actionir import ActionIRV1, ActionOpV1, canonical_digest, compile_shadow_candidate
from owner_evidence_projection import GuardianEvidenceV1, TaskFlowObserverReceiptV1
from rust_receipt_adapter import RustNeuronReceiptViewV1, adapt_verified_rust_receipt

D, E, F, G, H, I = (x * 64 for x in "abcdef")
ZERO = "0" * 64


def make_ir():
    op = ActionOpV1("observe_ax", "window:main", {}, "cap.observe", "op-1", D, E, True)
    return ActionIRV1("cell.reflex", D, E, F, "app.browser", 4, 9, "wasm32-wasi", (op,), ("cap.observe",), 8, 25, 4096, "strict")


def make_candidate(ir):
    return compile_shadow_candidate(ir, candidate_id="candidate.reflex.4", capability_manifest_digest=D, runtime_tuple_digest=G, policy_digest=E, snapshot_id="snapshot-4", authorization_version=H, backend="wasm_aot", target="cpu", evidence={"lane": "synthetic", "source": "p3"})


def make_guardian():
    values = dict(enabled=True, scope_digest=F, authorization_version=H, score_fresh=True, newer_failed_classification=False, action_risk=1.0, risk_threshold=2.0, decision="eligible", authority="DENY_ALL")
    return GuardianEvidenceV1(evidence_digest=canonical_digest({"schema": "hepta.guardian.fast-decision-evidence.v1", **values}), **values)


def make_taskflow():
    return TaskFlowObserverReceiptV1(D, E, F, 7, True, "observed")


def make_rust(*, verified=True, request=D, status="Succeeded"):
    return RustNeuronReceiptViewV1(
        source_commit_digest=I, source_receipt_digest=H, request_digest=request, input_digest=H,
        runtime_tuple_digest=G, encoder_digest=D, head_digest=E, output_digest=F,
        drive_vector_digest=D if status == "Succeeded" else ZERO,
        prediction_vector_digest=E if status == "Succeeded" else ZERO,
        status=status, observed_memory_bytes=10, transient_allocation_bytes=20,
        queue_age_micros=3, latency_micros=4, source_verified=verified,
    )


class RustReceiptAdapterTests(unittest.TestCase):
    def test_verified_succeeded_receipt_adapts_to_shadow_projection(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = adapt_verified_rust_receipt(candidate, ir, make_rust(), make_guardian(), make_taskflow(), expected_request_digest=D, expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.status, "ADAPTED")
        self.assertEqual(decision.authority, "DENY_ALL")
        self.assertFalse(decision.effect_admitted)
        self.assertEqual(decision.projection.status, "PROJECTED")

    def test_unverified_source_falls_back(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = adapt_verified_rust_receipt(candidate, ir, make_rust(verified=False), make_guardian(), make_taskflow(), expected_request_digest=D, expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.status, "FALLBACK")
        self.assertIn("RUST_SOURCE_NOT_VERIFIED", decision.reason_codes)

    def test_request_drift_falls_back(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = adapt_verified_rust_receipt(candidate, ir, make_rust(request=I), make_guardian(), make_taskflow(), expected_request_digest=D, expected_input_digest=H, expected_scope_digest=F)
        self.assertIn("REQUEST_DIGEST_MISMATCH", decision.reason_codes)

    def test_failed_cancelled_indeterminate_fall_back_without_output(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        for status in ("Failed", "Cancelled", "Indeterminate"):
            rust = make_rust(status=status)
            decision = adapt_verified_rust_receipt(candidate, ir, rust, make_guardian(), make_taskflow(), expected_request_digest=D, expected_input_digest=H, expected_scope_digest=F)
            self.assertEqual(decision.status, "FALLBACK")
            self.assertIn("RUST_NONTERMINAL_OR_FAILED", decision.reason_codes)

    def test_authority_and_effect_are_structurally_denied(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = adapt_verified_rust_receipt(candidate, ir, make_rust(), make_guardian(), make_taskflow(), expected_request_digest=D, expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.authority, "DENY_ALL")
        self.assertFalse(decision.effect_admitted)
        self.assertFalse(decision.projection.effect_admitted)


if __name__ == "__main__":
    unittest.main()
