//! Test port responses exercise binding only; they are not real model evidence.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelErrorV1;
use codex_hepta_agent_components::types::AuthorityPosture;

#[derive(Default)]
struct BindingTestPort {
    requests: Vec<SelfIterationModelRequestV1>,
    wrong_role: bool,
}
impl SelfIterationModelPortV1 for BindingTestPort {
    async fn assess(
        &mut self,
        request: SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
        self.requests.push(request.clone());
        Ok(SelfIterationModelAssessmentV1 {
            request_id: request.request_id,
            role: if self.wrong_role {
                SelfIterationModelRoleV1::Observer
            } else {
                request.role
            },
            envelope_digest: request.envelope_digest,
            candidate_digest: request.candidate_digest,
            model_output: "test advisory only".into(),
            native_run_digest: Digest32::of_bytes(b"test port terminal binding"),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
fn envelope() -> IterationEnvelopeV1 {
    let digest = Digest32::of_bytes(b"test envelope");
    IterationEnvelopeV1 {
        envelope_id: StableId::new("test.iteration").expect("id"),
        base_commit: digest,
        base_tree: digest,
        objective_digest: digest,
        grammar_digest: digest,
        maximum_files: 1,
        maximum_diff_bytes: 1024,
        maximum_candidates: 1,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: super::super::cycle::now_ms().expect("time") / 1_000 + 60,
    }
}
fn pending() -> AgentdSelfIterationArtifactReadinessV1 {
    AgentdSelfIterationArtifactReadinessV1::PendingInputs {
        descriptor_digest: None,
        manifest_missing: true,
        missing: vec![AgentdSelfIterationArtifactKindV1::ModelWeights],
    }
}

#[tokio::test]
async fn pending_turn_dispatches_generator_without_candidate_or_activation() {
    let mut port = BindingTestPort::default();
    let envelope = envelope();
    let output =
        assess_self_iteration_pending_inputs_v1(&mut port, &envelope, "test objective", &pending())
            .await
            .expect("bounded advisory");
    assert_eq!(port.requests.len(), 1);
    assert!(
        port.requests[0]
            .request_id
            .as_str()
            .starts_with("iteration.pending.")
    );
    assert_eq!(port.requests[0].role, SelfIterationModelRoleV1::Generator);
    assert!(port.requests[0].candidate_digest.is_none());
    assert_eq!(
        port.requests[0].deadline_ms,
        envelope.expiry_unix_seconds * 1_000
    );
    assert_eq!(output.readiness, pending());
    assert!(!output.assessment.authority.grants_any());
    let mut installed = pending();
    if let AgentdSelfIterationArtifactReadinessV1::PendingInputs {
        descriptor_digest, ..
    } = &mut installed
    {
        *descriptor_digest = Some(Digest32::of_bytes(b"installed"));
    }
    assess_self_iteration_pending_inputs_v1(&mut port, &envelope, "test objective", &installed)
        .await
        .expect("distinct inventory turn");
    assert_ne!(port.requests[0].request_id, port.requests[1].request_id);
}

#[tokio::test]
async fn expired_envelope_stays_unsubmitted_and_wrong_role_response_is_rejected() {
    let mut port = BindingTestPort::default();
    let mut envelope = envelope();
    envelope.expiry_unix_seconds = 1;
    assert!(
        assess_self_iteration_pending_inputs_v1(&mut port, &envelope, "test objective", &pending())
            .await
            .is_err()
    );
    assert!(port.requests.is_empty());
    envelope.expiry_unix_seconds = super::super::cycle::now_ms().expect("time") / 1_000 + 60;
    port.wrong_role = true;
    assert!(
        assess_self_iteration_pending_inputs_v1(&mut port, &envelope, "test objective", &pending())
            .await
            .is_err()
    );
    assert_eq!(port.requests.len(), 1);
}
