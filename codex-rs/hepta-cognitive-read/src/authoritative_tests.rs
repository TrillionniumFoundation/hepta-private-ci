use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn vector() -> LaneCGenerationVectorV1 {
    LaneCGenerationVectorV1 {
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 9,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 7,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    }
}

fn envelope_with(
    vector: LaneCGenerationVectorV1,
    acquired: u64,
    expires: u64,
) -> AuthoritativeSnapshotV1 {
    let record = MemoryRecord {
        record_id: id("memory:one"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    let snapshot = build_snapshot(generation(1), vec![record])
        .unwrap_or_else(|error| panic!("valid snapshot: {error}"));
    let key = CognitiveSnapshotKeyV1::new(vector)
        .unwrap_or_else(|error| panic!("valid key: {error}"));
    AuthoritativeSnapshotV1::new(id("provider:one"), key, snapshot, acquired, expires)
        .unwrap_or_else(|error| panic!("valid envelope: {error}"))
}

fn envelope() -> AuthoritativeSnapshotV1 {
    envelope_with(vector(), 5, 50)
}

fn acquisition_request() -> SnapshotAcquisitionRequestV1 {
    SnapshotAcquisitionRequestV1 {
        request_id: id("request:one"),
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        minimum_memory_frontier: 10,
        minimum_tombstone_frontier: 4,
        authority_epoch: 7,
        deadline_unix_ms: 100,
    }
}

fn authoritative_request() -> AuthoritativeReadRequestV1 {
    AuthoritativeReadRequestV1 {
        allowed_kinds: Vec::new(),
        maximum_results: 8,
        include_tombstones: false,
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    }
}

#[derive(Clone)]
struct FixtureProvider {
    envelope: AuthoritativeSnapshotV1,
}

impl AuthoritativeCognitiveSnapshotProvider for FixtureProvider {
    fn acquire(
        &self,
        _request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        Ok(self.envelope.clone())
    }
}

#[test]
fn authoritative_read_binds_provider_vector_and_query() {
    let envelope = envelope();
    let provider = FixtureProvider {
        envelope: envelope.clone(),
    };
    let guard = read_authoritative(&provider, 10, acquisition_request(), authoritative_request())
        .unwrap_or_else(|error| panic!("authoritative read: {error}"));
    assert_eq!(guard.read_result().records().len(), 1);
    assert_eq!(
        guard.result().generation_vector_digest(),
        envelope.snapshot_key().vector_digest
    );
    guard
        .result()
        .validate()
        .unwrap_or_else(|error| panic!("valid result: {error}"));

    let current = FixtureProvider {
        envelope: envelope_with(vector(), 9, 60),
    };
    guard
        .revalidate(&current, 10)
        .unwrap_or_else(|error| panic!("current authoritative read: {error}"));
}

#[test]
fn provider_rejects_scope_frontier_and_epoch_drift() {
    let envelope = envelope();

    let mut request = acquisition_request();
    request.scope_id = id("scope:other");
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::ScopeMismatch)
    );

    let mut request = acquisition_request();
    request.minimum_tombstone_frontier += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleTombstoneFrontier)
    );

    let mut request = acquisition_request();
    request.authority_epoch += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );
}

#[test]
fn delivery_revalidation_rejects_generation_epoch_provider_and_lease_drift() {
    let initial = envelope();
    let guard = read_authoritative(
        &FixtureProvider {
            envelope: initial.clone(),
        },
        10,
        acquisition_request(),
        authoritative_request(),
    )
    .unwrap_or_else(|error| panic!("authoritative guard: {error}"));

    let mut advanced_vector = vector();
    advanced_vector.memory_ledger_frontier += 1;
    let advanced = FixtureProvider {
        envelope: envelope_with(advanced_vector, 9, 60),
    };
    assert_eq!(
        guard.revalidate(&advanced, 10),
        Err(SnapshotProviderError::GenerationGone)
    );

    let mut epoch_vector = vector();
    epoch_vector.authority_epoch += 1;
    let revoked = FixtureProvider {
        envelope: envelope_with(epoch_vector, 9, 60),
    };
    assert_eq!(
        guard.revalidate(&revoked, 10),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );

    let other_provider_envelope = AuthoritativeSnapshotV1::new(
        id("provider:other"),
        initial.snapshot_key().clone(),
        initial.snapshot().clone(),
        9,
        60,
    )
    .unwrap_or_else(|error| panic!("authoritative snapshot: {error}"));
    assert_eq!(
        guard.revalidate(
            &FixtureProvider {
                envelope: other_provider_envelope,
            },
            10,
        ),
        Err(SnapshotProviderError::ProviderMismatch)
    );

    assert_eq!(
        guard.revalidate(
            &FixtureProvider {
                envelope: envelope_with(vector(), 49, 70),
            },
            50,
        ),
        Err(SnapshotProviderError::LeaseExpired)
    );
}

#[test]
fn provider_rejects_expired_deadline_and_invalid_bounded_read() {
    let envelope = envelope();
    assert_eq!(
        envelope.validate_for_request(100, &acquisition_request()),
        Err(SnapshotProviderError::DeadlineExpired)
    );

    let provider = FixtureProvider { envelope };
    let mut request = authoritative_request();
    request.maximum_results = 0;
    assert!(matches!(
        read_authoritative(&provider, 10, acquisition_request(), request),
        Err(SnapshotProviderError::Read(_))
    ));
}
