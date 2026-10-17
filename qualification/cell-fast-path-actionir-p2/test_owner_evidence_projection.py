import unittest

from cell_fast_path_actionir import ActionIRV1, ActionOpV1, canonical_digest, compile_shadow_candidate
from owner_evidence_projection import (
    GuardianEvidenceV1,
    NeuronFeatureReceiptProjectionV1,
    TaskFlowObserverReceiptV1,
    project_owner_shadow_evidence,
)

D = "a" * 64
E = "b" * 64
F = "c" * 64
G = "d" * 64
H = "e" * 64
I = "f" * 64


def make_ir():
    op = ActionOpV1(
        op="observe_ax", target="window:main", args={}, capability_id="cap.observe",
        idempotency_key="op-1", precondition_digest=D, postcondition_digest=E, reversible=True,
    )
    return ActionIRV1(
        cell_id="cell.reflex", stem_digest=D, head_digest=E, objective_digest=F,
        app_identity="app.browser", body_generation=4, revocation_epoch=9,
        abi="wasm32-wasi", ops=(op,), required_capabilities=("cap.observe",),
        max_ops=8, deadline_ms=25, max_memory_bytes=4096, determinism="strict",
    )


def make_candidate(ir):
    return compile_shadow_candidate(
        ir, candidate_id="candidate.reflex.4", capability_manifest_digest=D,
        runtime_tuple_digest=G, policy_digest=E, snapshot_id="snapshot-4",
        authorization_version=H, backend="wasm_aot", target="cpu",
        evidence={"lane": "synthetic", "source": "p2-contract"},
    )


def make_neuron(status="succeeded", runtime=G, input_digest=H):
    output = I if status == "succeeded" else None
    vector = D if status == "succeeded" else None
    payload = {
        "schema": "hepta.neuron.feature-receipt-projection.v1",
        "request_digest": D, "input_digest": input_digest, "runtime_tuple_digest": runtime,
        "encoder_digest": D, "head_digest": E, "output_digest": output,
        "output_vector_digest": vector, "status": status,
        "observed_memory_bytes": 10, "observed_transient_bytes": 20,
        "observed_queue_age_ns": 3, "observed_latency_ns": 4,
        "model_id": "shadow-model", "authority": "DENY_ALL",
    }
    return NeuronFeatureReceiptProjectionV1(receipt_digest=canonical_digest(payload), **{k: v for k, v in payload.items() if k != "schema"})


def make_guardian(eligible=True, scope=F, auth=H):
    values = dict(enabled=eligible, scope_digest=scope, authorization_version=auth,
                  score_fresh=eligible, newer_failed_classification=not eligible,
                  action_risk=1.0 if eligible else 10.0, risk_threshold=2.0,
                  decision="eligible" if eligible else "fallback", authority="DENY_ALL")
    digest = canonical_digest({"schema": "hepta.guardian.fast-decision-evidence.v1", **values})
    return GuardianEvidenceV1(evidence_digest=digest, **values)


def make_taskflow(terminal=False):
    return TaskFlowObserverReceiptV1(D, E, F, 7, True, "observed" if not terminal else "terminal", terminal_claim=terminal)


class OwnerEvidenceProjectionTests(unittest.TestCase):
    def test_exact_success_projection_is_shadow_only(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = project_owner_shadow_evidence(candidate, ir, make_neuron(), make_guardian(scope=F), make_taskflow(), expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.status, "PROJECTED")
        self.assertFalse(decision.effect_admitted)
        self.assertEqual(decision.authority, "DENY_ALL")
        self.assertEqual(decision.projection_digest, canonical_digest({"schema": decision.as_dict()["schema"], **{k: v for k, v in decision.as_dict().items() if k != "projection_digest"}}))

    def test_runtime_and_input_drift_fallback(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = project_owner_shadow_evidence(candidate, ir, make_neuron(runtime=I, input_digest=D), make_guardian(scope=F), make_taskflow(), expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.status, "FALLBACK")
        self.assertIn("RUNTIME_TUPLE_MISMATCH", decision.reason_codes)
        self.assertIn("INPUT_DIGEST_MISMATCH", decision.reason_codes)

    def test_failed_cancelled_indeterminate_have_no_output_and_fallback(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        for status in ("failed", "cancelled", "indeterminate"):
            decision = project_owner_shadow_evidence(candidate, ir, make_neuron(status=status), make_guardian(scope=F), make_taskflow(), expected_input_digest=H, expected_scope_digest=F)
            self.assertEqual(decision.status, "FALLBACK")
            self.assertIn("NEURON_NONTERMINAL_OR_FAILED", decision.reason_codes)

    def test_guardian_stale_or_risky_forces_fallback(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        decision = project_owner_shadow_evidence(candidate, ir, make_neuron(), make_guardian(eligible=False, scope=F), make_taskflow(), expected_input_digest=H, expected_scope_digest=F)
        self.assertEqual(decision.status, "FALLBACK")
        self.assertIn("GUARDIAN_FALLBACK", decision.reason_codes)

    def test_taskflow_terminal_claim_is_rejected(self):
        ir, candidate = make_ir(), None
        candidate = make_candidate(ir)
        with self.assertRaises(ValueError):
            make_taskflow(terminal=True)

    def test_receipt_digest_is_deterministic(self):
        self.assertEqual(make_neuron().receipt_digest, make_neuron().receipt_digest)
        self.assertEqual(make_taskflow().digest, make_taskflow().digest)


if __name__ == "__main__":
    unittest.main()
