use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use codex_hepta_types::{Digest32, Generation, StableId};

use super::*;

#[derive(Clone)]
struct LiveAuthority {
    cns_live: Arc<AtomicBool>,
    final_use_live: Arc<AtomicBool>,
}

impl LiveAuthority {
    fn allowed() -> Self {
        Self {
            cns_live: Arc::new(AtomicBool::new(true)),
            final_use_live: Arc::new(AtomicBool::new(true)),
        }
    }
}

impl CellSplitFinalizationAuthorityV1 for LiveAuthority {
    type Error = &'static str;

    fn verify_current_route(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        if self.cns_live.load(Ordering::Acquire)
            && checkpoint.phase != WriterHandoffPhaseV1::Prepared
            && binding.cns_cutover_receipt_digest == digest("original signed cns cutover")
            && binding.successor_route_digest == digest("live published successor")
        {
            Ok(())
        } else {
            Err("independent CNS owner no longer serves the original cutover")
        }
    }

    fn verify_current_final_use(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        _checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        if self.final_use_live.load(Ordering::Acquire)
            && binding.final_use_binding_digest == digest("independently verified NDU selection")
        {
            Ok(())
        } else {
            Err("independent final-use authority was revoked")
        }
    }
}

fn id(s: &str) -> StableId {
    StableId::new(s).expect("fixture ID")
}

fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}

fn gen(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn plan() -> crate::WriterHandoffPlanV1 {
    crate::WriterHandoffPlanV1 {
        operation_id: id("split-real-supervisor"),
        domain_id: id("scope.writer"),
        source_writer: id("writer.old"),
        target_writer: id("writer.new"),
        old_generation: gen(7),
        new_generation: gen(8),
        authority_epoch: 11,
        migration_plan_digest: digest("original migration plan"),
        schema_digest: digest("original state schema"),
        rollback_predecessor_digest: digest("retained rollback root"),
    }
}

fn binding() -> CellSplitFinalizationBindingV1 {
    CellSplitFinalizationBindingV1 {
        operation_id: plan().operation_id,
        domain_id: plan().domain_id,
        source_writer: plan().source_writer,
        target_writer: plan().target_writer,
        old_generation: gen(7),
        new_generation: gen(8),
        authority_epoch: 11,
        migration_plan_digest: plan().migration_plan_digest,
        schema_digest: plan().schema_digest,
        rollback_predecessor_digest: plan().rollback_predecessor_digest,
        cns_cutover_receipt_digest: digest("original signed cns cutover"),
        successor_route_digest: digest("live published successor"),
        final_use_binding_digest: digest("independently verified NDU selection"),
    }
}

fn file(root: &tempfile::TempDir) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(root.path().join("writer-handoff.log"))
        .expect("journal file")
}

fn phase(
    value: WriterHandoffPhaseV1,
    watermark: Option<u64>,
) -> WriterHandoffAdvanceV1 {
    WriterHandoffAdvanceV1 {
        phase: value,
        evidence_digest: digest(&format!("observed {value:?}")),
        outbox_watermark: watermark,
        unknown_effect_count: 0,
    }
}

/// Uses the existing real fsynced journal, including its parent drain and
/// predecessor result fencing phases, not an in-memory fake handoff.
fn prepare(root: &tempfile::TempDir, terminal_phase: WriterHandoffPhaseV1)
    -> WriterHandoffCheckpointV1
{
    let mut journal =
        DurableWriterHandoffJournalV1::create(file(root), plan()).expect("journal");
    for value in [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
    ] {
        if value == WriterHandoffPhaseV1::RoutePublished
            && terminal_phase != WriterHandoffPhaseV1::RoutePublished
        {
            break;
        }
        let watermark = (value == WriterHandoffPhaseV1::Drained).then_some(37);
        journal.advance(phase(value, watermark)).expect("real persisted phase");
    }
    let checkpoint = journal.checkpoint().clone();
    drop(journal);
    checkpoint
}

#[test]
fn actually_appends_retired_checkpoint_and_reopens_identical_receipt() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let auth = LiveAuthority::allowed();
    let original;
    {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, binding(), auth.clone()
        ).expect("authenticated journal reopen");
        assert!(owner.read_retired().expect("route published").is_none());
        original = owner.finalize_once().expect("fsynced Retired state");
        assert_eq!(original.phase, WriterHandoffPhaseV1::Retired);
        assert_eq!(original.revision, minimum.revision + 1);
        assert_eq!(original.previous_receipt_digest, minimum.receipt_digest);
        assert_eq!(original.evidence_digest, binding().retirement_evidence_digest());
        assert!(!original.old_writer_valid());
        assert!(original.new_writer_admission_open());
        assert_eq!(owner.read_retired().expect("real state"), Some(original.clone()));
        let original_bytes = owner.read_retired_receipt_bytes()
            .expect("original signed-record input").expect("committed bytes");
        assert_eq!(original_bytes, original.canonical_receipt_bytes_v1().expect("record"));
        let journal_file = fs::read(root.path().join("writer-handoff.log")).expect("disk");
        let raw_last = journal_file.split(|byte| *byte == b'\n')
            .rev().find(|record| !record.is_empty()).expect("last durable record");
        assert_eq!(original_bytes.as_slice(), raw_last);
        assert_eq!(owner.finalize_once().expect("one original commit"), original);
    }
    let mut recovered = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root), &minimum, binding(), auth
    ).expect("journal recovery after process shutdown");
    assert_eq!(recovered.read_retired().expect("fresh readback"), Some(original.clone()));
    assert_eq!(
        recovered.read_retired_receipt_bytes().expect("recovered bytes"),
        Some(original.canonical_receipt_bytes_v1().expect("canonical original"))
    );
}

#[test]
fn final_use_revocation_fences_both_mutation_and_readback() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let auth = LiveAuthority::allowed();
    let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root), &minimum, binding(), auth.clone()
    ).expect("reopen");
    auth.final_use_live.store(false, Ordering::Release);
    assert!(matches!(
        owner.finalize_once(),
        Err(CellSplitFinalizationErrorV1::Revoked(_))
    ));
    assert_eq!(owner.checkpoint().phase, WriterHandoffPhaseV1::RoutePublished);
    auth.final_use_live.store(true, Ordering::Release);
    owner.finalize_once().expect("real append");
    auth.cns_live.store(false, Ordering::Release);
    assert!(matches!(
        owner.read_retired(),
        Err(CellSplitFinalizationErrorV1::Revoked(_))
    ));
}

#[test]
fn pre_route_generation_cannot_retire_or_skip_writer_fences() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::NewWriterFenced);
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, binding(), LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::NotRoutePublished)
    ));
}

#[test]
fn independent_minimum_rejects_restoring_valid_older_journal() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let stale_bytes = fs::read(root.path().join("writer-handoff.log")).expect("prefix");
    let durable = {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, binding(), LiveAuthority::allowed()
        ).expect("reopen");
        owner.finalize_once().expect("commit")
    };
    fs::write(root.path().join("writer-handoff.log"), stale_bytes)
        .expect("externally restored old-but-valid prefix");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &durable, binding(), LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::AcknowledgedCheckpointMissing
        ))
    ));
}

#[test]
fn different_original_cns_or_handoff_plan_cannot_replay_same_retirement() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, binding(), LiveAuthority::allowed()
        ).expect("open");
        owner.finalize_once().expect("real terminal receipt");
    }
    let mut changed = binding();
    changed.cns_cutover_receipt_digest = digest("different signed CNS effect");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, changed, LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::InvalidBinding)
    ));
    let mut changed = binding();
    changed.migration_plan_digest = digest("other migration");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, changed, LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::InvalidBinding)
    ));
}

#[test]
fn independent_writer_lock_blocks_second_owner() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let _first = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root), &minimum, binding(), LiveAuthority::allowed()
    ).expect("first owner");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root), &minimum, binding(), LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::Handoff(WriterHandoffErrorV1::Busy))
    ));
}


#[test]
fn schema_rollback_and_writer_identity_are_frozen_for_retirement() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let changed_fields = [
        {
            let mut alternate = binding();
            alternate.schema_digest = digest("different checkpoint schema");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.rollback_predecessor_digest = digest("different rollback lineage");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.source_writer = id("untrusted-old-writer");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.target_writer = id("untrusted-successor");
            alternate
        },
    ];
    for alternate in changed_fields {
        assert!(matches!(
            CellSplitSupervisorJournalFinalizerV1::recover_at_least(
                file(&root), &minimum, alternate, LiveAuthority::allowed()
            ),
            Err(CellSplitFinalizationErrorV1::InvalidBinding)
        ));
    }
}
