use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::*;
use codex_hepta_evidence::metrics_group_commit::MetricsGroupCommitV1;
use codex_hepta_operator_acceptance::CELL_SPLIT_EVIDENCE_WAL_OBSERVER_SCHEMA_V1;
use codex_hepta_operator_acceptance::CellSplitEvidenceWalIndependentObserverV1;
use codex_hepta_operator_acceptance::CellSplitEvidenceWalObserverErrorV1;
use codex_hepta_operator_acceptance::CellSplitEvidenceWalObserverProofV1;
use codex_hepta_operator_acceptance::cell_split_evidence_wal_observer_signing_payload_v1;
use codex_hepta_operator_acceptance::verify_cell_split_evidence_wal_observer_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;

const DOMAIN: &str = "scope.evidence.metrics";

fn original_sink(path: &std::path::Path) -> Arc<DurablePhaseMetricSinkV1> {
    Arc::new(
        DurablePhaseMetricSinkV1::open(path, 16, 8, 60_000)
            .expect("original durable Evidence writer"),
    )
}

fn sample(phase: PhaseMetricKindV1) -> PhaseMetricEventV1 {
    PhaseMetricEventV1 {
        scope_digest: Digest32::of_bytes(b"original-evidence-scope"),
        operation_digest: Digest32::of_bytes(b"original-evidence-operation"),
        phase,
        latency_micros: 12,
        succeeded: true,
    }
}

fn adapter(sink: Arc<DurablePhaseMetricSinkV1>) -> AgentdOriginalEvidenceWalReadV1 {
    AgentdOriginalEvidenceWalReadV1::new(
        StableId::new(DOMAIN).expect("pinned domain"),
        sink,
    )
    .expect("genuine writer")
}

#[derive(Debug)]
struct IndependentFixture {
    retained: CellSplitEvidenceWalLocalFrontierV1,
    calls: usize,
}

impl CellSplitEvidenceWalIndependentObserverV1 for IndependentFixture {
    type Error = &'static str;

    fn read_current(
        &mut self,
        domain: &str,
        challenge: &str,
    ) -> Result<CellSplitEvidenceWalObserverProofV1, Self::Error> {
        self.calls += 1;
        let mut proof = CellSplitEvidenceWalObserverProofV1 {
            schema: CELL_SPLIT_EVIDENCE_WAL_OBSERVER_SCHEMA_V1.to_owned(),
            journal_domain_id: domain.to_owned(),
            authority_epoch: 3,
            challenge_nonce: challenge.to_owned(),
            sequence: self.retained.sequence,
            committed_rows: self.retained.committed_rows,
            head_digest: self.retained.head_digest.clone(),
            wal_bytes: self.retained.wal_bytes,
            signature_bytes: Vec::new(),
        };
        proof.signature_bytes = SigningKey::from_bytes(&[73_u8; 32])
            .sign(
                &cell_split_evidence_wal_observer_signing_payload_v1(&proof)
                    .expect("isolated test-only signing payload"),
            )
            .to_bytes()
            .to_vec();
        Ok(proof)
    }
}

#[test]
fn real_evidence_writer_readback_is_original_fsynced_wal_not_queued_counts() {
    let root = tempfile::tempdir().expect("private root");
    let path = root.path().join("metrics.wal");
    let sink = original_sink(&path);
    let mut reader = adapter(Arc::clone(&sink));
    sink.record(sample(PhaseMetricKindV1::Cas)).expect("first actual event");
    sink.record(sample(PhaseMetricKindV1::Cns)).expect("second actual event");
    let before = reader
        .read_original_durable_frontier(DOMAIN)
        .expect("FIFO fsync before readback");
    assert_eq!(before.sequence, 1);
    assert_eq!(before.committed_rows, 2);
    assert!(before.wal_bytes > 0);
    assert_ne!(before.head_digest, Digest32::ZERO.to_string());
    drop(reader);
    drop(sink);

    let mut reopened = MetricsGroupCommitV1::open(&path).expect("reopen exact original WAL");
    let after = reopened.read_local_original_frontier().expect("real disk readback");
    assert_eq!(after.sequence, before.sequence);
    assert_eq!(after.committed_rows, before.committed_rows);
    assert_eq!(after.head_digest.to_string(), before.head_digest);
    assert_eq!(after.wal_bytes, before.wal_bytes);
}

#[test]
fn production_adapter_rejects_foreign_domain_before_wal_readback() {
    let root = tempfile::tempdir().expect("private root");
    let sink = original_sink(&root.path().join("metrics.wal"));
    let mut reader = adapter(sink);
    assert!(reader.read_original_durable_frontier("foreign.metrics").is_err());
}

#[test]
fn independent_challenged_signature_joins_two_real_original_wal_reads() {
    let root = tempfile::tempdir().expect("private root");
    let sink = original_sink(&root.path().join("metrics.wal"));
    sink.record(sample(PhaseMetricKindV1::Cas)).expect("sample");
    let mut reader = adapter(Arc::clone(&sink));
    let actual = reader
        .read_original_durable_frontier(DOMAIN)
        .expect("original current fsync");
    let mut remote = IndependentFixture {
        retained: actual.clone(),
        calls: 0,
    };
    let accepted = verify_cell_split_evidence_wal_observer_v1(
        DOMAIN,
        &mut reader,
        &mut remote,
        &SigningKey::from_bytes(&[73_u8; 32]).verifying_key(),
    )
    .expect("test-only Observer and genuine Evidence original agree");
    assert_eq!(accepted.local, actual);
    assert_eq!(remote.calls, 1);
    assert!(sink.healthy());
}

#[test]
fn external_signed_old_highwater_cannot_ack_real_wal_advancement() {
    let root = tempfile::tempdir().expect("private root");
    let sink = original_sink(&root.path().join("metrics.wal"));
    let mut reader = adapter(Arc::clone(&sink));
    sink.record(sample(PhaseMetricKindV1::Cas)).expect("first group");
    let original = reader
        .read_original_durable_frontier(DOMAIN)
        .expect("original fsync");
    let mut remote = IndependentFixture {
        retained: original,
        calls: 0,
    };
    sink.record(sample(PhaseMetricKindV1::Cns)).expect("later actual group");
    let now = reader
        .read_original_durable_frontier(DOMAIN)
        .expect("new original fsync");
    assert_eq!(now.sequence, 2);
    assert!(matches!(
        verify_cell_split_evidence_wal_observer_v1(
            DOMAIN,
            &mut reader,
            &mut remote,
            &SigningKey::from_bytes(&[73_u8; 32]).verifying_key(),
        ),
        Err(CellSplitEvidenceWalObserverErrorV1::Stale)
    ));
    assert_eq!(remote.calls, 1);
}

#[cfg(unix)]
#[test]
fn replacement_original_wal_denies_readback_and_poisoned_sink() {
    use std::os::unix::fs::PermissionsExt as _;

    let root = tempfile::tempdir().expect("private root");
    let path = root.path().join("metrics.wal");
    let parked = root.path().join("displaced.wal");
    let sink = original_sink(&path);
    let mut reader = adapter(Arc::clone(&sink));
    sink.record(sample(PhaseMetricKindV1::Cas)).expect("sample");
    reader
        .read_original_durable_frontier(DOMAIN)
        .expect("initial fsync");
    let actual = std::fs::read(&path).expect("original bytes");
    std::fs::rename(&path, &parked).expect("replace pathname");
    std::fs::write(&path, &actual).expect("same bytes, different inode");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
        .expect("private replacement");
    assert!(reader.read_original_durable_frontier(DOMAIN).is_err());
    assert!(!sink.healthy(), "invalid original must poison Evidence health");
}
