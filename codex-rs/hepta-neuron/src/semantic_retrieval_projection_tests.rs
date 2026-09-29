use std::str::FromStr;

use codex_hepta_infer_core::RetrievalSourceV1;
use codex_hepta_infer_core::SemanticRetrievalRequestV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticAdmissionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticCompletionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticPhaseV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticRecordV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticResourceLimitsV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

fn digest(value: char) -> Digest32 {
    Digest32::from_str(&value.to_string().repeat(64)).expect("digest")
}

fn request() -> SemanticRetrievalRequestV1 {
    SemanticRetrievalRequestV1 {
        operation_id: "semantic.op.1".to_string(),
        workspace_id: "workspace.1".to_string(),
        generation: 7,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "3".repeat(64),
        deadline_ms: 9_000,
        query: "choose current evidence".to_string(),
        sources: vec![
            RetrievalSourceV1 {
                source_id: "source.z".to_string(),
                revision: 11,
                content_sha256: Digest32::of_bytes(b"zeta").to_string(),
                text: "zeta".to_string(),
            },
            RetrievalSourceV1 {
                source_id: "source.a".to_string(),
                revision: 5,
                content_sha256: Digest32::of_bytes(b"alpha").to_string(),
                text: "alpha".to_string(),
            },
        ],
    }
}

fn reply_wire(request: &SemanticRetrievalRequestV1) -> Vec<u8> {
    let mut reply = b"HPTARS\x01\x00".to_vec();
    reply.extend_from_slice(Digest32::of_bytes(&request.encode().expect("request")).as_array());
    reply.extend_from_slice(digest('3').as_array());
    reply.extend_from_slice(&3_u32.to_be_bytes());
    for value in [333_333_u32, 333_333, 333_334] {
        reply.extend_from_slice(&value.to_be_bytes());
    }
    reply.extend_from_slice(&24_u64.to_be_bytes());
    reply.extend_from_slice(&0_u64.to_be_bytes());
    reply.extend_from_slice(&51_u64.to_be_bytes());
    request.decode_reply(&reply).expect("valid reply");
    reply
}

fn record() -> SemanticRecordV1 {
    let request = request();
    let completion = SemanticCompletionV1 {
        reply_wire: reply_wire(&request),
        observed_memory_bytes: Some(512),
    };
    let completion_digest =
        Digest32::of_bytes(&serde_json::to_vec(&completion).expect("completion encoding"))
            .to_string();
    SemanticRecordV1 {
        admission: SemanticAdmissionV1 {
            request_wire: request.encode().expect("request"),
            principal_id: "principal.1".to_string(),
            reservation_id: "reservation.1".to_string(),
            worker_id: "worker.1".to_string(),
            worker_generation: 4,
            maximum_tokens: 128,
            maximum_memory_bytes: 1_024,
            authority_binding_digest: "4".repeat(64),
        },
        resource_limits: Some(SemanticResourceLimitsV2 {
            model_id: "laya.english.1".to_string(),
            resident_bytes: 768,
            kv_bytes: 128,
            transient_bytes: 128,
        }),
        revision: 3,
        admitted_at_ms: 1_000,
        phase: SemanticPhaseV1::Completed,
        cancel_requested: false,
        stop_reason: None,
        completion: Some(completion),
        completion_digest: Some(completion_digest),
        within_resource_budget: true,
        delivery_ack_digest: None,
    }
}

fn context() -> SemanticNeuronUseContextV1 {
    let request = request();
    SemanticNeuronUseContextV1 {
        operation_id: request.operation_id,
        workspace_id: request.workspace_id,
        semantic_generation: request.generation,
        authority_binding_digest: "4".repeat(64),
        objective_digest: digest('1'),
        observation_digest: digest('2'),
        bundle_digest: digest('3'),
        current_sources: vec![
            SemanticNeuronSourceBindingV1 {
                source_id: "source.a".to_string(),
                revision: 5,
                content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            },
            SemanticNeuronSourceBindingV1 {
                source_id: "source.z".to_string(),
                revision: 11,
                content_sha256: Digest32::of_bytes(b"zeta").to_string(),
            },
        ],
        now_ms: 8_999,
        tick_id: StableId::new("run.1").expect("run"),
        subject_id: StableId::new("subject.1").expect("subject"),
        logical_sequence: 1,
        monotonic_time_micros: 500,
        checkpoint_digest: Digest32::ZERO,
        ndu_snapshot_digest: digest('5'),
        body_generation: 9,
        modulator_digest: None,
    }
}

#[derive(Default)]
struct Guard {
    calls: usize,
    rejection: Option<SemanticNeuronProjectionError>,
}

impl SemanticNeuronFinalUseGuard for Guard {
    fn check(
        &mut self,
        _record: &SemanticRecordV1,
        _request: &SemanticRetrievalRequestV1,
        _reply: &SemanticRetrievalReplyV1,
        _context: &SemanticNeuronUseContextV1,
    ) -> Result<(), SemanticNeuronProjectionError> {
        self.calls += 1;
        match self.rejection.clone() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

#[test]
fn projects_only_the_exact_pending_owner_observation() {
    let mut guard = Guard::default();
    let projection = project_semantic_retrieval_to_neuron_v1(&record(), context(), &mut guard)
        .expect("projection");
    assert_eq!(guard.calls, 1);
    assert_eq!(
        projection.feature_order,
        ["abstain", "source.a", "source.z"]
    );
    assert_eq!(
        projection.input.feature_vector_q24.iter().sum::<i64>(),
        1_i64 << 24
    );
    assert_eq!(
        projection.input.input_feature_digest,
        canonical_feature_vector_digest_v1(&projection.input.feature_vector_q24)
    );
    assert_eq!(projection.input.objective_digest, digest('1'));
    assert_eq!(projection.input.body_generation, Some(9));
    assert!(!projection.provenance_digest.is_zero());

    let mut second = Guard::default();
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&record(), context(), &mut second)
            .expect("same projection"),
        projection
    );
}

#[test]
fn stale_source_is_rejected_before_the_authority_guard() {
    let mut current = context();
    current.current_sources[0].revision += 1;
    let mut guard = Guard::default();
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&record(), current, &mut guard),
        Err(SemanticNeuronProjectionError::StaleSource)
    );
    assert_eq!(guard.calls, 0);
}

#[test]
fn expiry_and_binding_drift_are_rejected_before_projection() {
    let mut expired = context();
    expired.now_ms = 9_000;
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&record(), expired, &mut Guard::default()),
        Err(SemanticNeuronProjectionError::Expired)
    );

    let mut changed = context();
    changed.authority_binding_digest = "6".repeat(64);
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&record(), changed, &mut Guard::default()),
        Err(SemanticNeuronProjectionError::BindingMismatch)
    );
}

#[test]
fn cancelled_or_acknowledged_result_is_not_reprojected() {
    let mut cancelled = record();
    cancelled.cancel_requested = true;
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&cancelled, context(), &mut Guard::default()),
        Err(SemanticNeuronProjectionError::NotDeliverable)
    );

    let mut acknowledged = record();
    acknowledged.delivery_ack_digest = Some("7".repeat(64));
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&acknowledged, context(), &mut Guard::default()),
        Err(SemanticNeuronProjectionError::NotDeliverable)
    );
}

#[test]
fn corrupt_completion_identity_is_not_reinterpreted() {
    let mut changed = record();
    changed.completion_digest = Some("8".repeat(64));
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&changed, context(), &mut Guard::default()),
        Err(SemanticNeuronProjectionError::CorruptCompletion)
    );
}

#[test]
fn trusted_guard_can_reject_revoked_current_use() {
    let mut guard = Guard {
        calls: 0,
        rejection: Some(SemanticNeuronProjectionError::Revoked),
    };
    assert_eq!(
        project_semantic_retrieval_to_neuron_v1(&record(), context(), &mut guard),
        Err(SemanticNeuronProjectionError::Revoked)
    );
    assert_eq!(guard.calls, 1);
}
