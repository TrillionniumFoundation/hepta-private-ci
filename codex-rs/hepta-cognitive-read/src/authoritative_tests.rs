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

fn envelope() -> AuthoritativeSnapshotV1 {
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
    let key =
        CognitiveSnapshotKeyV1::new(vector()).unwrap_or_else(|error| panic!("valid key: {error}"));
    AuthoritativeSnapshotV1::new(id("provider:one"), key, snapshot, 5, 50)
        .unwrap_or_else(|error| panic!("valid envelope: {error}"))
}

fn acquisition_request() -> SnapshotAcquisitionRequestV1 {
    SnapshotAcquisitionRequestV1 {
        request_id: id("request:one"),
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        minimum_memory_frontier: 10,
        minimum_tombstone_frontier: 4,
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

#[test]
fn authoritative_read_binds_provider_vector_and_query() {
    let envelope = envelope();
    let provider = FixtureProvider {
        envelope: envelope.clone(),
    };
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: envelope.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 8,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    let result = read_authoritative(&provider, 10, acquisition_request(), request)
        .unwrap_or_else(|error| panic!("authoritative read: {error}"));
    assert_eq!(result.read_result.records().len(), 1);
    assert_eq!(
        result.generation_vector_digest,
        envelope.snapshot_key().vector_digest
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
fn provider_rejects_expired_deadline_and_wrong_read_snapshot() {
    let envelope = envelope();
    assert_eq!(
        envelope.validate_for_request(50, &acquisition_request()),
        Err(SnapshotProviderError::DeadlineExpired)
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
