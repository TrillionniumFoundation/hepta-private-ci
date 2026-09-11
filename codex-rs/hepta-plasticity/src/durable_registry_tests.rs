use super::*;
use crate::ParameterCandidateKindV2;
use crate::ParameterCandidateRequestV2;
use crate::ParameterDeltaV2;
use crate::ParameterProposalRequestV2;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct TestFile {
    path: PathBuf,
}

impl TestFile {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-plasticity-{label}-{}-{nonce}.journal",
            std::process::id()
        ));
        Self { path }
    }

    fn create(&self) -> File {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
            .unwrap_or_else(|error| panic!("create test registry: {error}"))
    }

    fn open(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .unwrap_or_else(|error| panic!("open test registry: {error}"))
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error:?}"))
}

fn proposal(proposal_id: &str, window_digest: &[u8]) -> ParameterProposalV2 {
    let selected = digest(b"selected-artifact");
    crate::propose_v2(ParameterProposalRequestV2 {
        proposal_id: id(proposal_id),
        proposer_id: id("proposer:durable"),
        evaluator_id: id("evaluator:durable"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id("window:durable"),
            window_digest: digest(window_digest),
        },
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        dataset_digest: digest(b"dataset"),
        update_rule_digest: digest(b"update-rule"),
        modulator_digest: digest(b"modulator"),
        modulator_broadcast_digest: digest(b"broadcast"),
        eligibility_digest: digest(b"eligibility"),
        evaluation_digest: digest(b"evaluation"),
        rollback_predecessor_digest: selected,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:adapter"),
            baseline_squared_l2_raw_q64: 1_000_000,
        }],
        candidates: vec![
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:no-change"),
                kind: ParameterCandidateKindV2::NoChange,
                parameter_deltas: Vec::new(),
            },
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:update"),
                kind: ParameterCandidateKindV2::Update,
                parameter_deltas: vec![ParameterDeltaV2 {
                    layer_id: id("layer:adapter"),
                    parameter_id: id("parameter:adapter"),
                    delta: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-10),
                    upper_bound: FixedQ32::from_raw(10),
                    evidence_digest: digest(b"delta-evidence"),
                }],
            },
        ],
    })
    .unwrap_or_else(|error| panic!("valid proposal: {error:?}"))
}

#[test]
fn append_reopen_and_anchor_preserve_exact_record() {
    let fixture = TestFile::new("reopen");
    let scope = digest(b"registry-scope");
    let expected = proposal("proposal:durable:1", b"window-a");
    let anchor = {
        let mut store = DurableProposalRegistry::open(fixture.create(), scope, 7, 8)
            .unwrap_or_else(|error| panic!("open: {error:?}"));
        let receipt = store
            .append_v2(Digest32::ZERO, expected.clone())
            .unwrap_or_else(|error| panic!("append: {error:?}"));
        assert_eq!(receipt.sequence, 1);
        assert_eq!(receipt.disposition, AppendDisposition::Inserted);
        assert!(!receipt.authority.grants_any());
        store
            .current_anchor()
            .unwrap_or_else(|error| panic!("anchor: {error:?}"))
            .unwrap_or_else(|| panic!("anchor must exist"))
    };

    let store = DurableProposalRegistry::open_anchored(fixture.open(), scope, 7, 8, anchor)
        .unwrap_or_else(|error| panic!("reopen: {error:?}"));
    assert_eq!(
        store
            .record_count()
            .unwrap_or_else(|error| panic!("count: {error:?}")),
        1
    );
    assert_eq!(
        store
            .get_v2_by_proposal_id(&expected.proposal_id)
            .unwrap_or_else(|error| panic!("read: {error:?}")),
        Some(&expected)
    );
}

#[test]
fn identical_retry_is_unchanged_and_does_not_consume_capacity() {
    let fixture = TestFile::new("retry");
    let mut store =
        DurableProposalRegistry::open(fixture.create(), digest(b"registry-scope"), 9, 1)
            .unwrap_or_else(|error| panic!("open: {error:?}"));
    let value = proposal("proposal:durable:retry", b"window-a");
    let first = store
        .append_v2(Digest32::ZERO, value.clone())
        .unwrap_or_else(|error| panic!("first append: {error:?}"));
    let replay = store
        .append_v2(first.frame_digest, value)
        .unwrap_or_else(|error| panic!("retry: {error:?}"));
    assert_eq!(replay.disposition, AppendDisposition::Unchanged);
    assert_eq!(replay.frame_digest, first.frame_digest);
    assert_eq!(store.record_count(), Ok(1));
}

#[test]
fn stale_predecessor_and_slot_drift_fail_closed() {
    let fixture = TestFile::new("conflict");
    let mut store =
        DurableProposalRegistry::open(fixture.create(), digest(b"registry-scope"), 11, 4)
            .unwrap_or_else(|error| panic!("open: {error:?}"));
    let first = proposal("proposal:durable:first", b"window-a");
    let receipt = store
        .append_v2(Digest32::ZERO, first)
        .unwrap_or_else(|error| panic!("append: {error:?}"));
    let other = proposal("proposal:durable:other", b"window-b");
    assert_eq!(
        store.append_v2(Digest32::ZERO, other.clone()),
        Err(DurableProposalRegistryError::Conflict)
    );
    assert!(matches!(
        store.append_v2(receipt.frame_digest, other),
        Err(DurableProposalRegistryError::Proposal(
            Error::RegistrySlotConflict(_)
        ))
    ));
}

#[test]
fn context_and_external_anchor_mismatch_reject_reopen() {
    let fixture = TestFile::new("anchor");
    let scope = digest(b"registry-scope");
    let anchor = {
        let mut store = DurableProposalRegistry::open(fixture.create(), scope, 13, 4)
            .unwrap_or_else(|error| panic!("open: {error:?}"));
        store
            .append_v2(
                Digest32::ZERO,
                proposal("proposal:durable:anchor", b"window-a"),
            )
            .unwrap_or_else(|error| panic!("append: {error:?}"));
        store
            .current_anchor()
            .unwrap_or_else(|error| panic!("anchor: {error:?}"))
            .unwrap_or_else(|| panic!("anchor must exist"))
    };
    assert!(matches!(
        DurableProposalRegistry::open(fixture.open(), digest(b"other-scope"), 13, 4),
        Err(DurableProposalRegistryError::ContextMismatch)
    ));
    assert!(matches!(
        DurableProposalRegistry::open(fixture.open(), scope, 14, 4),
        Err(DurableProposalRegistryError::ContextMismatch)
    ));
    let wrong = DurableRegistryAnchorV1 {
        sequence: anchor.sequence,
        frame_digest: digest(b"wrong-anchor"),
    };
    assert!(matches!(
        DurableProposalRegistry::open_anchored(fixture.open(), scope, 13, 4, wrong),
        Err(DurableProposalRegistryError::AnchorMismatch)
    ));
}

#[test]
fn incomplete_tail_is_removed_before_recovery_returns() {
    let fixture = TestFile::new("tail");
    let scope = digest(b"registry-scope");
    let anchor = {
        let mut store = DurableProposalRegistry::open(fixture.create(), scope, 15, 4)
            .unwrap_or_else(|error| panic!("open: {error:?}"));
        store
            .append_v2(
                Digest32::ZERO,
                proposal("proposal:durable:tail", b"window-a"),
            )
            .unwrap_or_else(|error| panic!("append: {error:?}"));
        store
            .current_anchor()
            .unwrap_or_else(|error| panic!("anchor: {error:?}"))
            .unwrap_or_else(|| panic!("anchor must exist"))
    };
    let valid_len = std::fs::metadata(&fixture.path)
        .unwrap_or_else(|error| panic!("metadata: {error}"))
        .len();
    {
        let mut file = OpenOptions::new()
            .append(true)
            .open(&fixture.path)
            .unwrap_or_else(|error| panic!("append tail: {error}"));
        file.write_all(&[0, 0, 0])
            .unwrap_or_else(|error| panic!("write tail: {error}"));
        file.sync_all()
            .unwrap_or_else(|error| panic!("sync tail: {error}"));
    }
    let store = DurableProposalRegistry::open_anchored(fixture.open(), scope, 15, 4, anchor)
        .unwrap_or_else(|error| panic!("recover: {error:?}"));
    assert_eq!(store.record_count(), Ok(1));
    assert_eq!(
        std::fs::metadata(&fixture.path)
            .unwrap_or_else(|error| panic!("metadata: {error}"))
            .len(),
        valid_len
    );
}

#[test]
fn a_second_writer_cannot_open_the_same_file() {
    let fixture = TestFile::new("lock");
    let first = DurableProposalRegistry::open(fixture.create(), digest(b"registry-scope"), 17, 4)
        .unwrap_or_else(|error| panic!("first open: {error:?}"));
    assert!(matches!(
        DurableProposalRegistry::open(fixture.open(), digest(b"registry-scope"), 17, 4,),
        Err(DurableProposalRegistryError::Busy)
    ));
    drop(first);
}

#[test]
fn rejected_anchor_does_not_truncate_recoverable_bytes() -> Result<(), Box<dyn StdError>> {
    for tail in [&[0, 0, 0][..], &[0, 0, 1, 0, 7][..]] {
        let fixture = TestFile::new("rejected-anchor-tail");
        let scope = digest(b"registry-scope");
        let anchor = {
            let mut store = DurableProposalRegistry::open(fixture.create(), scope, 19, 4)?;
            let receipt = store.append_v2(
                Digest32::ZERO,
                proposal("proposal:anchor-tail", b"window-a"),
            )?;
            DurableRegistryAnchorV1 {
                sequence: receipt.sequence,
                frame_digest: receipt.frame_digest,
            }
        };
        let valid_bytes = std::fs::read(&fixture.path)?;
        let mut file = OpenOptions::new().append(true).open(&fixture.path)?;
        file.write_all(tail)?;
        file.sync_all()?;
        drop(file);
        let incomplete_bytes = std::fs::read(&fixture.path)?;
        for (wrong, expected) in [
            (
                DurableRegistryAnchorV1 {
                    sequence: anchor.sequence,
                    frame_digest: digest(b"wrong-history"),
                },
                DurableProposalRegistryError::AnchorMismatch,
            ),
            (
                DurableRegistryAnchorV1 {
                    sequence: anchor.sequence + 1,
                    frame_digest: anchor.frame_digest,
                },
                DurableProposalRegistryError::AcknowledgedHistoryMissing,
            ),
        ] {
            let rejected =
                DurableProposalRegistry::open_anchored(fixture.open(), scope, 19, 4, wrong);
            assert_eq!(rejected.err(), Some(expected));
            assert_eq!(std::fs::read(&fixture.path)?, incomplete_bytes);
        }
        let recovered =
            DurableProposalRegistry::open_anchored(fixture.open(), scope, 19, 4, anchor)?;
        assert_eq!(recovered.current_anchor()?, Some(anchor));
        assert_eq!(std::fs::read(&fixture.path)?, valid_bytes);
    }
    Ok(())
}

#[test]
fn a_full_registry_can_recover_an_incomplete_tail() -> Result<(), Box<dyn StdError>> {
    let fixture = TestFile::new("full-registry-tail");
    let scope = digest(b"registry-scope");
    let expected = proposal("proposal:full-tail", b"window-a");
    let receipt = {
        let mut store = DurableProposalRegistry::open(fixture.create(), scope, 23, 1)?;
        store.append_v2(Digest32::ZERO, expected.clone())?
    };
    let valid_bytes = std::fs::read(&fixture.path)?;
    let mut file = OpenOptions::new().append(true).open(&fixture.path)?;
    file.write_all(&[0, 0, 0])?;
    file.sync_all()?;
    drop(file);
    let anchor = DurableRegistryAnchorV1 {
        sequence: receipt.sequence,
        frame_digest: receipt.frame_digest,
    };
    let mut recovered =
        DurableProposalRegistry::open_anchored(fixture.open(), scope, 23, 1, anchor)?;
    assert_eq!(
        recovered.get_v2_by_proposal_id(&expected.proposal_id)?,
        Some(&expected)
    );
    let mut retry = receipt;
    retry.disposition = AppendDisposition::Unchanged;
    assert_eq!(recovered.append_v2(Digest32::ZERO, expected)?, retry);
    assert_eq!(std::fs::read(&fixture.path)?, valid_bytes);
    Ok(())
}
