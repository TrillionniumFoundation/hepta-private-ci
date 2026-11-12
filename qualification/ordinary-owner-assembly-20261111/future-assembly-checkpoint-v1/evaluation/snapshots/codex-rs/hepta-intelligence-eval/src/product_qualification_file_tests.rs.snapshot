//! Data-publication components use explicit synthetic decision bytes. Actual
//! runner/signature composition is covered in product_file_backed_tests.

use super::*;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;

use crate::IndependentEvaluationDecisionV1;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

struct ComponentJournal(PathBuf);

impl ComponentJournal {
    fn create() -> (Self, LockedFileProductQualificationEvidenceSinkV1) {
        let path = std::env::temp_dir().join(format!(
            "hepta-qualification-file-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed)
        ));
        let mut options: OpenOptions = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        let file: File = options.open(&path).expect("actual component evidence file");
        let sink = LockedFileProductQualificationEvidenceSinkV1::create(
            file,
            digest("component evidence owner"),
        )
        .expect("new original durable store");
        (Self(path), sink)
    }

    fn open(&self) -> File {
        let mut options: OpenOptions = OpenOptions::new();
        options.read(true).write(true);
        options.open(&self.0).expect("component evidence custody")
    }

    fn recover(
        &self,
        minimum: ProductEvaluationExecutionAnchorV1,
    ) -> Result<LockedFileProductQualificationEvidenceSinkV1, FileError> {
        LockedFileProductQualificationEvidenceSinkV1::recover(
            self.open(),
            digest("component evidence owner"),
            minimum,
        )
    }
}

impl Drop for ComponentJournal {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision() -> SignedEvaluationDecisionV1 {
    let id = |name: &str| StableId::new(name).expect("component identifier");
    SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id: id("component-evaluation"),
            candidate_id: id("component-candidate"),
            baseline_id: id("component-baseline"),
            disposition: IndependentEvaluationDispositionV1::InsufficientEvidence,
            failed_metrics: vec![id("component-metric")],
            evidence_digest: digest("component-evidence"),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("component-trust"),
        authentication_digest: digest("component-authentication"),
    }
}

#[test]
fn committed_publication_is_exact_and_conflict_never_changes_the_journal() {
    let (journal, mut sink) = ComponentJournal::create();
    let decision = decision();
    let execution = digest("component-execution");
    let publication = sink.persist(execution, &decision).expect("actual fsynced publication");
    let anchor = sink.anchor();
    let bytes = std::fs::read(&journal.0).expect("actual journal");
    assert_eq!(anchor.sequence, 2);
    assert_eq!(sink.persist(execution, &decision), Ok(publication));
    assert_eq!(sink.anchor(), anchor);
    let mut conflicting = decision.clone();
    conflicting.authentication_digest = digest("different-authentication");
    assert_eq!(sink.persist(execution, &conflicting), Err(SinkError::Rejected));
    assert_eq!(sink.readback(execution, &conflicting), Err(SinkError::Rejected));
    let mut renamed = decision.clone();
    renamed.decision.evaluation_id =
        StableId::new("different-evaluation-id").expect("component alternate ID");
    assert_eq!(sink.persist(execution, &renamed), Err(SinkError::Rejected));
    assert_eq!(sink.readback(execution, &renamed), Err(SinkError::Rejected));
    assert_eq!(sink.anchor(), anchor);
    assert_eq!(std::fs::read(&journal.0).expect("same journal"), bytes);
    drop(sink);
    let mut recovered = journal.recover(anchor).expect("exact witnessed recovery");
    assert_eq!(recovered.persist(execution, &decision), Ok(publication));
    assert_eq!(recovered.anchor(), anchor);
    assert_eq!(std::fs::read(&journal.0).expect("unchanged readback"), bytes);
}

#[test]
fn durable_pending_is_not_completed_by_recovery_or_repeat_publication() {
    let (journal, mut sink) = ComponentJournal::create();
    let decision = decision();
    let execution = digest("component-pending-execution");
    let key = publication_key(sink.owner_binding, execution).expect("actual execution key");
    assert_eq!(
        ProductEvaluationExecutionStoreV1::claim(&mut sink.publication_store, &key),
        Ok(ProductEvaluationExecutionClaimV1::Claimed)
    );
    let anchor = sink.anchor();
    let bytes = std::fs::read(&journal.0).expect("actual fsynced pending claim");
    drop(sink);
    let mut recovered = journal.recover(anchor).expect("recover pending state, not success");
    assert_eq!(recovered.persist(execution, &decision), Err(SinkError::Indeterminate));
    assert_eq!(recovered.readback(execution, &decision), Err(SinkError::Indeterminate));
    assert_eq!(recovered.anchor(), anchor);
    assert_eq!(std::fs::read(&journal.0).expect("pending stays original"), bytes);
}

#[test]
fn original_lock_and_recovery_anchor_refuse_busy_rollback_and_torn_history() {
    let (journal, mut sink) = ComponentJournal::create();
    let initial_anchor = sink.anchor();
    let initial = std::fs::read(&journal.0).expect("initial original header");
    assert_eq!(
        LockedFileProductQualificationEvidenceSinkV1::create(
            journal.open(),
            digest("component evidence owner"),
        )
        .err(),
        Some(FileError::Busy)
    );
    sink.persist(digest("component-execution"), &decision())
        .expect("actual publication");
    let committed_anchor = sink.anchor();
    let committed = std::fs::read(&journal.0).expect("complete original history");
    drop(sink);
    std::fs::write(&journal.0, &initial).expect("simulate old backup");
    assert_eq!(journal.recover(committed_anchor).err(), Some(FileError::Rollback));
    std::fs::write(&journal.0, &committed[..committed.len() - 1])
        .expect("simulate torn committed frame");
    assert_eq!(journal.recover(initial_anchor).err(), Some(FileError::Corrupt));
}

#[test]
fn changed_file_length_fences_publication_and_never_turns_into_success() {
    let (journal, mut sink) = ComponentJournal::create();
    let initial = std::fs::read(&journal.0).expect("initial header");
    let decision = decision();
    let execution = digest("component-execution");
    journal
        .open()
        .set_len(initial.len() as u64 + 1)
        .expect("simulate noncooperating file mutation");
    assert_eq!(sink.persist(execution, &decision), Err(SinkError::Indeterminate));
    std::fs::write(&journal.0, &initial).expect("restore bytes cannot clear poisoned owner");
    assert_eq!(sink.persist(execution, &decision), Err(SinkError::Indeterminate));
    assert_eq!(sink.readback(execution, &decision), Err(SinkError::Indeterminate));
    assert_eq!(sink.anchor().sequence, 0);
}
