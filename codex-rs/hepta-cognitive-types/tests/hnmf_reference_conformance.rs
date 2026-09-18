use std::str::FromStr;

use codex_hepta_cognitive_types::hnmf as production;
use codex_hepta_types::Digest32;
use serde::Deserialize;

const SHARED_FIXTURE_PATH: &str = "tests/data/hnmf_conformance_v1.json";

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

fn digest(value: &str) -> Digest32 {
    let Ok(value) = Digest32::from_str(value) else {
        panic!("fixture production digest must parse");
    };
    value
}

fn production_event(
    fixture: FixtureV1,
) -> Result<production::MemoryEventV1, production::HnmfContractError> {
    let span = production::ModalitySpanRefV1::try_new(
        fixture.span_id,
        production::ModalityKindV1::Text,
        digest(&fixture.asset_sha256),
        production::SpanRangeV1::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        digest(&fixture.preprocessor_sha256),
        None,
        None,
        25_000,
        production::PrivacyClassV1::AgentPrivate,
        None,
    )?;
    let scope = production::MemoryScopeV1::agent_private(fixture.agent_id)?;
    let interval = production::TimeIntervalV1::try_new(fixture.observed_at_unix_ms, None)?;
    let provenance = production::ProvenanceRefV1::try_new(
        fixture.source_id,
        fixture.source_revision,
        digest(&fixture.source_sha256),
        fixture.observed_at_unix_ms,
    )?;
    let retention =
        production::RetentionPolicyV1::try_new(digest(&fixture.retention_digest), None, false)?;
    production::MemoryEventV1::try_new(
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
        digest(&fixture.objective_digest),
        digest(&fixture.ndu_state_digest),
        Some(500_000),
        production::MemoryLifecycleV1::Active,
    )
}

#[test]
fn shared_fixture_is_valid_in_production() {
    assert_eq!(SHARED_FIXTURE_PATH, "tests/data/hnmf_conformance_v1.json");
    assert!(production_event(fixture()).is_ok());
}

#[test]
fn shared_fixture_rejects_modality_range_mismatch_in_production() {
    let fixture = fixture();
    let span = production::ModalitySpanRefV1::try_new(
        fixture.span_id,
        production::ModalityKindV1::Image,
        digest(&fixture.asset_sha256),
        production::SpanRangeV1::ByteRange {
            start: 0,
            end: fixture.range_end,
        },
        digest(&fixture.preprocessor_sha256),
        None,
        None,
        0,
        production::PrivacyClassV1::AgentPrivate,
        None,
    );
    assert!(span.is_err());
}

#[test]
fn shared_fixture_modality_closed_world_in_production() {
    assert_eq!(production::ModalityKindV1::ALL.len(), 9);
}
