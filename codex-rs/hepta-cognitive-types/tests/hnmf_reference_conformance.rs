use std::str::FromStr;

use codex_hepta_cognitive_types::hnmf as production;
use codex_hepta_types::Digest32;
use hepta_hnmf_contract_reference as reference;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FixtureV1 {
    event_id: u64,
    episode_id: u64,
    span_id: u64,
    agent_id: String,
    source_id: String,
    source_revision: u64,
    observed_at_unix_ms: i64,
    range_end: u64,
    semantic_keys: Vec<String>,
    asset_sha256: String,
    preprocessor_sha256: String,
    source_sha256: String,
    objective_digest: String,
    ndu_state_digest: String,
    retention_digest: String,
}

fn fixture() -> FixtureV1 {
    let bytes = include_bytes!("data/hnmf_conformance_v1.json");
    let Ok(value) = serde_json::from_slice(bytes) else {
        panic!("checked-in HNMF conformance fixture must parse");
    };
    value
}

fn production_digest(value: &str) -> Digest32 {
    let Ok(value) = Digest32::from_str(value) else {
        panic!("fixture production digest must parse");
    };
    value
}

fn reference_digest(value: &str) -> reference::Digest32 {
    let Ok(value) = reference::Digest32::parse(value) else {
        panic!("fixture reference digest must parse");
    };
    value
}

#[test]
fn canonical_event_fixture_is_valid_in_reference_and_production() {
    let fixture = fixture();
    let reference_span = reference::ModalitySpanRef {
        span_id: fixture.span_id,
        modality: reference::ModalityKind::Text,
        asset_sha256: reference_digest(&fixture.asset_sha256),
        range: reference::SpanRange::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        preprocessor_manifest_sha256: reference_digest(&fixture.preprocessor_sha256),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 25_000,
        privacy_class: reference::PrivacyClass::AgentPrivate,
        redaction_mask_sha256: None,
    };
    let reference_event = reference::MemoryEvent {
        event_id: fixture.event_id,
        episode_id: fixture.episode_id,
        scope: reference::MemoryScope::AgentPrivate {
            agent_id: fixture.agent_id.clone(),
        },
        observed_interval: reference::TimeInterval {
            start_unix_ms: fixture.observed_at_unix_ms,
            end_unix_ms: None,
        },
        modality_spans: vec![reference_span],
        cross_modal_bindings: Vec::new(),
        semantic_keys: fixture.semantic_keys.iter().cloned().collect(),
        provenance: vec![reference::ProvenanceRef {
            source_id: fixture.source_id.clone(),
            source_revision: fixture.source_revision,
            source_sha256: reference_digest(&fixture.source_sha256),
            observed_at_unix_ms: fixture.observed_at_unix_ms,
        }],
        objective_digest: reference_digest(&fixture.objective_digest),
        ndu_state_digest: reference_digest(&fixture.ndu_state_digest),
        behavior_propensity_ppm: Some(500_000),
        lifecycle: reference::MemoryLifecycle::Active,
    };
    assert_eq!(reference_event.validate(), Ok(()));

    let span = production::ModalitySpanRefV1::try_new(
        fixture.span_id,
        production::ModalityKindV1::Text,
        production_digest(&fixture.asset_sha256),
        production::SpanRangeV1::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        production_digest(&fixture.preprocessor_sha256),
        None,
        None,
        25_000,
        production::PrivacyClassV1::AgentPrivate,
        None,
    );
    let Ok(span) = span else {
        panic!("production span fixture must be valid");
    };
    let scope = production::MemoryScopeV1::agent_private(fixture.agent_id);
    let Ok(scope) = scope else {
        panic!("production scope fixture must be valid");
    };
    let interval = production::TimeIntervalV1::try_new(fixture.observed_at_unix_ms, None);
    let Ok(interval) = interval else {
        panic!("production interval fixture must be valid");
    };
    let provenance = production::ProvenanceRefV1::try_new(
        fixture.source_id,
        fixture.source_revision,
        production_digest(&fixture.source_sha256),
        fixture.observed_at_unix_ms,
    );
    let Ok(provenance) = provenance else {
        panic!("production provenance fixture must be valid");
    };
    let retention = production::RetentionPolicyV1::try_new(
        production_digest(&fixture.retention_digest),
        None,
        false,
    );
    let Ok(retention) = retention else {
        panic!("production retention fixture must be valid");
    };
    let event = production::MemoryEventV1::try_new(
        fixture.event_id,
        fixture.episode_id,
        scope,
        interval,
        vec![span],
        Vec::new(),
        fixture.semantic_keys.into_iter().collect(),
        vec![provenance],
        production::MemoryVerificationStateV1::Verified,
        retention,
        production_digest(&fixture.objective_digest),
        production_digest(&fixture.ndu_state_digest),
        Some(500_000),
        production::MemoryLifecycleV1::Active,
    );
    assert!(event.is_ok());
}

#[test]
fn modality_range_mismatch_fails_closed_in_reference_and_production() {
    let fixture = fixture();
    let reference_span = reference::ModalitySpanRef {
        span_id: fixture.span_id,
        modality: reference::ModalityKind::Image,
        asset_sha256: reference_digest(&fixture.asset_sha256),
        range: reference::SpanRange::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        preprocessor_manifest_sha256: reference_digest(&fixture.preprocessor_sha256),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: reference::PrivacyClass::AgentPrivate,
        redaction_mask_sha256: None,
    };
    assert!(reference_span.validate().is_err());

    let production_span = production::ModalitySpanRefV1::try_new(
        fixture.span_id,
        production::ModalityKindV1::Image,
        production_digest(&fixture.asset_sha256),
        production::SpanRangeV1::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        production_digest(&fixture.preprocessor_sha256),
        None,
        None,
        0,
        production::PrivacyClassV1::AgentPrivate,
        None,
    );
    assert!(production_span.is_err());
}

#[test]
fn modality_closed_world_matches_reference() {
    assert_eq!(
        production::ModalityKindV1::ALL.len(),
        reference::ModalityKind::ALL.len()
    );
    assert_eq!(production::ModalityKindV1::ALL.len(), 9);
}
