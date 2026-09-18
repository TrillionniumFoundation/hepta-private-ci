use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
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

fn vector() -> AuthoritativeReadGenerationVectorV1 {
    AuthoritativeReadGenerationVectorV1 {
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        memory_ledger_frontier: 10,
        source_ledger_frontier: 9,
        tombstone_frontier: 4,
        knowledge_fact_frontier: 8,
        knowledge_graph_generation: generation(2),
        consumer_profile_digest: digest("consumer-profile"),
        authority_epoch: 7,
    }
}

fn snapshot() -> CognitiveSnapshot {
    let record = MemoryRecord {
        record_id: id("memory:one"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    build_snapshot(generation(11), vec![record])
        .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn envelope() -> AuthoritativeSnapshotV1 {
    AuthoritativeSnapshotV1::new(id("provider:one"), vector(), snapshot(), 5, 30)
        .unwrap_or_else(|error| panic!("valid envelope: {error}"))
}

fn acquisition_request() -> SnapshotAcquisitionRequestV1 {
    SnapshotAcquisitionRequestV1 {
        request_id: id("request:one"),
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        consumer_profile_digest: digest("consumer-profile"),
        minimum_memory_frontier: 10,
        minimum_source_frontier: 9,
        minimum_tombstone_frontier: 4,
        minimum_knowledge_fact_frontier: 8,
        minimum_knowledge_graph_generation: generation(2),
        authority_epoch: 7,
        deadline_unix_ms: 40,
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

fn authoritative_read(
    envelope: &AuthoritativeSnapshotV1,
) -> (SnapshotAcquisitionRequestV1, AuthoritativeReadResultV1) {
    let provider = FixtureProvider {
        envelope: envelope.clone(),
    };
    let acquisition = acquisition_request();
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: envelope.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 8,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    let result = read_authoritative(&provider, 10, acquisition.clone(), request)
        .unwrap_or_else(|error| panic!("authoritative read: {error}"));
    (acquisition, result)
}

#[test]
fn authoritative_read_binds_provider_vector_and_query() {
    let envelope = envelope();
    let (_, result) = authoritative_read(&envelope);
    assert_eq!(result.read_result.records().len(), 1);
    assert_eq!(
        result.generation_vector_digest,
        envelope.generation_vector_digest()
    );
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid result: {error}"));
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
    request.minimum_source_frontier += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleSourceFrontier)
    );

    let mut request = acquisition_request();
    request.minimum_tombstone_frontier += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleTombstoneFrontier)
    );

    let mut request = acquisition_request();
    request.minimum_knowledge_fact_frontier += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleKnowledgeFactFrontier)
    );

    let mut request = acquisition_request();
    request.minimum_knowledge_graph_generation = generation(3);
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleKnowledgeGraphGeneration)
    );

    let mut request = acquisition_request();
    request.consumer_profile_digest = digest("different-profile");
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::ConsumerProfileMismatch)
    );

    let mut request = acquisition_request();
    request.authority_epoch += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );
}

#[test]
fn provider_rejects_expired_deadline_lease_and_wrong_read_snapshot() {
    let envelope = envelope();
    assert_eq!(
        envelope.validate_for_request(40, &acquisition_request()),
        Err(SnapshotProviderError::DeadlineExpired)
    );
    assert_eq!(
        envelope.validate_for_request(30, &acquisition_request()),
        Err(SnapshotProviderError::LeaseExpired)
    );

    let provider = FixtureProvider { envelope };
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: digest("wrong-snapshot"),
            allowed_kinds: Vec::new(),
            maximum_results: 1,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    assert_eq!(
        read_authoritative(&provider, 10, acquisition_request(), request),
        Err(SnapshotProviderError::ReadSnapshotMismatch)
    );
}

#[test]
fn consume_revalidation_accepts_fresh_receipt_for_identical_owner_cut() {
    let original = envelope();
    let (request, result) = authoritative_read(&original);
    let current = AuthoritativeSnapshotV1::new(
        id("provider:one"),
        vector(),
        original.snapshot().clone(),
        12,
        35,
    )
    .unwrap_or_else(|error| panic!("current envelope: {error}"));

    revalidate_authoritative_read(&result, &original, &current, 20, &request)
        .unwrap_or_else(|error| panic!("revalidation: {error}"));
    assert_ne!(original.receipt_digest(), current.receipt_digest());
}

#[test]
fn consume_revalidation_fails_closed_on_generation_or_authority_drift() {
    let original = envelope();
    let (request, result) = authoritative_read(&original);

    let mut advanced = vector();
    advanced.memory_ledger_frontier += 1;
    let current = AuthoritativeSnapshotV1::new(
        id("provider:one"),
        advanced,
        original.snapshot().clone(),
        12,
        35,
    )
    .unwrap_or_else(|error| panic!("advanced envelope: {error}"));
    assert_eq!(
        revalidate_authoritative_read(&result, &original, &current, 20, &request),
        Err(SnapshotProviderError::GenerationGone)
    );

    let mut revoked = vector();
    revoked.authority_epoch += 1;
    let current = AuthoritativeSnapshotV1::new(
        id("provider:one"),
        revoked,
        original.snapshot().clone(),
        12,
        35,
    )
    .unwrap_or_else(|error| panic!("revoked envelope: {error}"));
    assert_eq!(
        revalidate_authoritative_read(&result, &original, &current, 20, &request),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );
}
