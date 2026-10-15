#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "real external library integration fixture must fail immediately on setup errors"
)]

// This integration executable links codex-hepta-supervisor as an ordinary,
// non-cfg(test) library. In-crate mechanism tests alone cannot prove that the
// publicly constructible finalizer refuses a caller-supplied allow-all port.
use std::fs;
use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt as _;

use codex_hepta_supervisor::CellSplitFinalizationAuthorityV1;
use codex_hepta_supervisor::CellSplitFinalizationBindingV1;
use codex_hepta_supervisor::CellSplitFinalizationErrorV1;
use codex_hepta_supervisor::CellSplitSupervisorJournalFinalizerV1;
use codex_hepta_supervisor::DurableWriterHandoffJournalV1;
use codex_hepta_supervisor::WriterHandoffAdvanceV1;
use codex_hepta_supervisor::WriterHandoffCheckpointV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterHandoffPlanV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn id(name: &str) -> StableId {
    StableId::new(name).expect("valid original test owner id")
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

struct CallerSuppliedAllowAll;

impl CellSplitFinalizationAuthorityV1 for CallerSuppliedAllowAll {
    type Error = &'static str;

    fn verify_current_route(
        &mut self,
        _binding: &CellSplitFinalizationBindingV1,
        _checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        Ok(())
    }

    fn verify_current_final_use(
        &mut self,
        _binding: &CellSplitFinalizationBindingV1,
        _checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        Ok(())
    }
}

fn plan() -> WriterHandoffPlanV1 {
    WriterHandoffPlanV1 {
        operation_id: id("split.unverified"),
        domain_id: id("scope.supervisor"),
        source_writer: id("writer.old"),
        target_writer: id("writer.new"),
        old_generation: Generation::new(7).expect("old generation"),
        new_generation: Generation::new(8).expect("new generation"),
        authority_epoch: 11,
        migration_plan_digest: digest("migration plan"),
        schema_digest: digest("state schema"),
        rollback_predecessor_digest: digest("predecessor"),
    }
}

fn binding(plan: &WriterHandoffPlanV1) -> CellSplitFinalizationBindingV1 {
    CellSplitFinalizationBindingV1 {
        operation_id: plan.operation_id.clone(),
        domain_id: plan.domain_id.clone(),
        source_writer: plan.source_writer.clone(),
        target_writer: plan.target_writer.clone(),
        old_generation: plan.old_generation,
        new_generation: plan.new_generation,
        authority_epoch: plan.authority_epoch,
        migration_plan_digest: plan.migration_plan_digest,
        schema_digest: plan.schema_digest,
        rollback_predecessor_digest: plan.rollback_predecessor_digest,
        cns_cutover_receipt_digest: digest("unverified CNS effect"),
        successor_route_digest: digest("unverified successor route"),
        final_use_binding_digest: digest("unverified NDU/Final-use"),
    }
}

#[test]
fn product_finalizer_denies_even_when_caller_supplies_allow_all_authority() {
    let temp = tempfile::tempdir().expect("private durable journal root");
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o700))
        .expect("private original owner directory");
    let journal_path = temp.path().join("original-writer-handoff.log");
    let initial = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&journal_path)
        .expect("fresh original journal");
    let plan = plan();
    let mut journal =
        DurableWriterHandoffJournalV1::create(initial, plan.clone()).expect("real fsynced journal");
    for phase in [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
    ] {
        journal
            .advance(WriterHandoffAdvanceV1 {
                phase,
                evidence_digest: digest(&format!("signed-shaped fixture: {phase:?}")),
                outbox_watermark: (phase == WriterHandoffPhaseV1::Drained).then_some(37),
                unknown_effect_count: 0,
            })
            .expect("real handoff phase fsync");
    }
    let minimum = journal.checkpoint().clone();
    assert_eq!(minimum.phase, WriterHandoffPhaseV1::RoutePublished);
    drop(journal);

    // Deliberately supply both an owner-derived minimum and a fake positive
    // verifier. Neither is independently signed original Control B/C proof.
    let before = fs::read(&journal_path).expect("original bytes before denied effect");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("reopen original journal");
    let mut finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file,
        &minimum,
        binding(&plan),
        CallerSuppliedAllowAll,
    )
    .expect("the pre-existing read-only journal is valid");
    assert!(matches!(
        finalizer.finalize_once(),
        Err(CellSplitFinalizationErrorV1::OriginalControlUnverified)
    ));
    assert_eq!(finalizer.checkpoint().phase, WriterHandoffPhaseV1::RoutePublished);
    assert_eq!(
        fs::read(&journal_path).expect("durable bytes after denied effect"),
        before,
        "an unverified caller must never append a Retired journal record"
    );
    drop(finalizer);

    // Cold reopen must not resurrect a retired fourth-step success.
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("cold owner reopen");
    let reopened = DurableWriterHandoffJournalV1::recover_at_least(file, &minimum)
        .expect("recovered original bytes");
    assert_eq!(reopened.checkpoint().phase, WriterHandoffPhaseV1::RoutePublished);
}
