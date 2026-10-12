use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use tempfile::NamedTempFile;

use super::*;

fn id(raw: &str) -> StableId {
    StableId::new(raw).expect("valid fixture stable id")
}
fn digest(raw: &[u8]) -> Digest32 {
    Digest32::of_bytes(raw)
}
fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}
fn plan() -> CellSplitPlanV1 {
    CellSplitPlanV1 {
        split_id: id("split:case:1"),
        scope_digest: digest(b"scope"),
        artifact_storage_binding_digest: digest(b"artifact-store:partition-1"),
        predecessor_id: id("cell:parent"),
        child_id: id("cell:child"),
        predecessor_artifact_id: id("artifact:parent"),
        child_artifact_id: id("artifact:child"),
        selected_candidate_id: id("candidate:child-1"),
        objective_digest: digest(b"frozen objective"),
        no_change_baseline_id: id("candidate:no-change"),
        no_change_baseline_digest: digest(b"frozen no-change"),
        evaluation_dataset_digest: digest(b"held-out dataset"),
        minimum_future_window_micros: 1_000_000,
        predecessor_generation: generation(7),
        child_generation: generation(8),
        predecessor_artifact_digest: digest(b"old artifact"),
        child_artifact_digest: digest(b"new artifact"),
        state_migration_digest: digest(b"migration"),
        selection_digest: digest(b"independently signed evaluation and selection"),
        final_use_binding_digest: digest(b"external final-use binding"),
    }
}

#[derive(Default)]
struct MockOwners {
    actual: BTreeMap<u8, CellSplitExternalReceiptV1>,
    attempts: Vec<CellSplitStepV1>,
    fail_observe_once: Option<CellSplitStepV1>,
    fail_cutover: bool,
    fail_anchor_once: bool,
    fail_anchor_sequence_once: Option<u64>,
    anchors: BTreeMap<u64, Digest32>,
}

impl MockOwners {
    // Qualification mock only. Production evidence MUST be real owner-signed
    // receipts and current readback, never these deterministic fixture bytes.
    fn receipt(plan: &CellSplitPlanV1, step: CellSplitStepV1) -> CellSplitExternalReceiptV1 {
        CellSplitExternalReceiptV1 {
            operation_key: plan.operation_key(step),
            generation: plan.child_generation,
            evidence: vec![step as u8; 64],
        }
    }
    fn install(&mut self, plan: &CellSplitPlanV1, step: CellSplitStepV1) {
        self.actual.insert(step as u8, Self::receipt(plan, step));
    }
    fn execute(
        &mut self,
        plan: &CellSplitPlanV1,
        step: CellSplitStepV1,
        key: Digest32,
    ) -> Result<(), CellSplitErrorV1> {
        if key != plan.operation_key(step) {
            return Err(CellSplitErrorV1::Conflict);
        }
        if step == CellSplitStepV1::CnsRouteCutover && self.fail_cutover {
            return Err(CellSplitErrorV1::Conflict);
        }
        self.attempts.push(step);
        self.install(plan, step);
        Ok(())
    }
}

impl CellSplitExecutionPortsV1 for MockOwners {
    fn observe(
        &mut self,
        _plan: &CellSplitPlanV1,
        step: CellSplitStepV1,
    ) -> Result<CellSplitObservationV1, CellSplitErrorV1> {
        if self.fail_observe_once == Some(step) && self.actual.contains_key(&(step as u8)) {
            self.fail_observe_once = None;
            return Err(CellSplitErrorV1::Indeterminate);
        }
        Ok(self.actual.get(&(step as u8)).cloned().map_or(
            CellSplitObservationV1::Missing,
            CellSplitObservationV1::Applied,
        ))
    }
    fn verify(
        &mut self,
        plan: &CellSplitPlanV1,
        step: CellSplitStepV1,
        receipt: &CellSplitExternalReceiptV1,
    ) -> Result<(), CellSplitErrorV1> {
        if receipt == &Self::receipt(plan, step) {
            Ok(())
        } else {
            Err(CellSplitErrorV1::Conflict)
        }
    }
    fn retain_ledger_anchor(
        &mut self,
        _plan: &CellSplitPlanV1,
        anchor: CellSplitLedgerAnchorV1,
    ) -> Result<(), CellSplitErrorV1> {
        if self.fail_anchor_once || self.fail_anchor_sequence_once == Some(anchor.sequence) {
            self.fail_anchor_once = false;
            self.fail_anchor_sequence_once = None;
            return Err(CellSplitErrorV1::Indeterminate);
        }
        if let Some(previous) = self.anchors.get(&anchor.sequence)
            && *previous != anchor.head_digest
        {
            return Err(CellSplitErrorV1::Conflict);
        }
        self.anchors.insert(anchor.sequence, anchor.head_digest);
        Ok(())
    }

    fn publish_artifact(
        &mut self, p: &CellSplitPlanV1, k: Digest32,
    ) -> Result<(), CellSplitErrorV1> {
        self.execute(p, CellSplitStepV1::ArtifactCas, k)
    }
    fn migrate_child(
        &mut self, p: &CellSplitPlanV1, k: Digest32,
    ) -> Result<(), CellSplitErrorV1> {
        self.execute(p, CellSplitStepV1::StateMigration, k)
    }
    fn start_shadow(
        &mut self, p: &CellSplitPlanV1, k: Digest32,
    ) -> Result<(), CellSplitErrorV1> {
        self.execute(p, CellSplitStepV1::ShadowChild, k)
    }
    fn fence_predecessor(
        &mut self, p: &CellSplitPlanV1, k: Digest32,
    ) -> Result<(), CellSplitErrorV1> {
        self.execute(p, CellSplitStepV1::SupervisorFence, k)
    }
    fn cutover_with_final_use(
        &mut self,
        p: &CellSplitPlanV1,
        k: Digest32,
        selection: &CellSplitExternalReceiptV1,
        final_use: &CellSplitExternalReceiptV1,
    ) -> Result<(), CellSplitErrorV1> {
        if selection != &Self::receipt(p, CellSplitStepV1::IndependentSelection)
            || final_use != &Self::receipt(p, CellSplitStepV1::FinalUseReady)
        {
            return Err(CellSplitErrorV1::Unapproved);
        }
        self.execute(p, CellSplitStepV1::CnsRouteCutover, k)
    }
}

fn reopen(file: &NamedTempFile) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(file.path())
        .expect("open fresh handle")
}

#[test]
fn split_requires_independent_selection_and_final_use_before_fence() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut owners = MockOwners::default();

    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Unapproved));
    assert_eq!(ledger.progress().accepted_steps, 3);
    assert_eq!(owners.attempts.len(), 3);

    owners.install(&p, CellSplitStepV1::IndependentSelection);
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Unapproved));
    assert_eq!(ledger.progress().accepted_steps, 4);
    assert!(!owners.attempts.contains(&CellSplitStepV1::SupervisorFence));

    owners.install(&p, CellSplitStepV1::FinalUseReady);
    let progress = ledger.drive(&mut owners).expect("approved cutover");
    assert!(progress.completed);
    assert_eq!(progress.accepted_steps, 7);
    assert_eq!(
        owners.attempts,
        vec![
            CellSplitStepV1::ArtifactCas,
            CellSplitStepV1::StateMigration,
            CellSplitStepV1::ShadowChild,
            CellSplitStepV1::SupervisorFence,
            CellSplitStepV1::CnsRouteCutover,
        ]
    );
    let latest = ledger.anchor();
    drop(ledger);

    let mut restored = CellSplitExecutionOwnerV1::recover(reopen(&file), p, latest)
        .expect("recover");
    assert!(restored.drive(&mut owners).expect("revalidate").completed);
    assert_eq!(owners.attempts.len(), 5);
}

#[test]
fn lost_ack_recovers_from_authoritative_readback_without_repeating_effect() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut owners = MockOwners {
        fail_observe_once: Some(CellSplitStepV1::ArtifactCas),
        ..Default::default()
    };

    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Indeterminate));
    assert_eq!(owners.attempts, vec![CellSplitStepV1::ArtifactCas]);
    // The independently retained witness must cover the pending intent
    // BEFORE the external CAS call. No effect is allowed on an unwitnessed intent.
    let independent_witness = ledger.anchor();
    assert_eq!(
        owners.anchors.get(&independent_witness.sequence),
        Some(&independent_witness.head_digest),
    );
    drop(ledger);

    let mut recovered = CellSplitExecutionOwnerV1::recover(
        reopen(&file), p.clone(), independent_witness,
    ).expect("reconcile unacknowledged effect");
    owners.install(&p, CellSplitStepV1::IndependentSelection);
    owners.install(&p, CellSplitStepV1::FinalUseReady);
    assert!(recovered.drive(&mut owners).expect("resume").completed);
    assert_eq!(
        owners.attempts.iter().filter(|step| **step == CellSplitStepV1::ArtifactCas).count(),
        1
    );
}

#[test]
fn externally_acknowledged_history_cannot_be_rolled_back() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut owners = MockOwners::default();
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Unapproved));
    let anchored = ledger.anchor();
    assert!(anchored.sequence > 0);
    drop(ledger);

    let truncated = reopen(&file);
    truncated.set_len(HEADER_SIZE as u64).expect("truncate journal");
    drop(truncated);
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover(reopen(&file), p, anchored),
        Err(CellSplitErrorV1::AnchorMismatch)
    ));
}

#[test]
fn complete_invalid_frame_is_never_silently_repaired() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let initial = ledger.anchor();
    assert_eq!(ledger.drive(&mut MockOwners::default()), Err(CellSplitErrorV1::Unapproved));
    drop(ledger);

    let mut raw = reopen(&file);
    raw.seek(SeekFrom::Start((HEADER_SIZE + 12) as u64)).expect("seek");
    raw.write_all(&[0x8a]).expect("tamper");
    raw.sync_all().expect("sync");
    drop(raw);
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover(reopen(&file), p, initial),
        Err(CellSplitErrorV1::Corrupt)
    ));
}

#[test]
fn incomplete_tail_is_repaired_only_beyond_authenticated_anchor() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let anchor = ledger.anchor();
    drop(ledger);

    let mut raw = reopen(&file);
    raw.seek(SeekFrom::End(0)).expect("seek");
    raw.write_all(&[0, 0]).expect("partial frame length");
    raw.sync_all().expect("sync");
    drop(raw);
    let recovered = CellSplitExecutionOwnerV1::recover(reopen(&file), p, anchor)
        .expect("repair partial tail");
    assert_eq!(recovered.anchor(), anchor);
    drop(recovered);
    assert_eq!(reopen(&file).metadata().expect("metadata").len(), HEADER_SIZE as u64);
}

#[test]
fn stale_observation_blocks_further_mutations() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut owners = MockOwners::default();
    owners.install(&p, CellSplitStepV1::IndependentSelection);
    owners.install(&p, CellSplitStepV1::FinalUseReady);
    assert!(ledger.drive(&mut owners).expect("cutover").completed);
    owners.actual.remove(&(CellSplitStepV1::StateMigration as u8));
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Conflict));
    // A historical terminal ledger+observer ACK is not a current-production
    // readiness claim after a failed external re-observation.
    assert!(!ledger.progress().completed);
    assert_eq!(owners.attempts.len(), 5);

    // Reinstating authoritative state allows full readback+observer revalidation,
    // without replaying any of the already committed external effects.
    owners.install(&p, CellSplitStepV1::StateMigration);
    assert!(ledger.drive(&mut owners).expect("verified recovery").completed);
    assert_eq!(owners.attempts.len(), 5);
}

#[test]
fn owner_locks_are_exclusive_and_scope_bound() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let anchor = ledger.anchor();
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover(reopen(&file), p.clone(), anchor),
        Err(CellSplitErrorV1::Busy)
    ));
    drop(ledger);
    let mut other = p.clone();
    other.child_artifact_digest = digest(b"different artifact");
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover(reopen(&file), other, anchor),
        Err(CellSplitErrorV1::ScopeMismatch)
    ));
    assert!(CellSplitExecutionOwnerV1::recover(reopen(&file), p, anchor).is_ok());
}

#[test]
fn route_cas_failure_keeps_predecessor_fenced_and_cutover_pending() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut owners = MockOwners {
        fail_cutover: true,
        ..Default::default()
    };
    owners.install(&p, CellSplitStepV1::IndependentSelection);
    owners.install(&p, CellSplitStepV1::FinalUseReady);
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Conflict));
    assert_eq!(ledger.progress().accepted_steps, 6);
    assert_eq!(owners.attempts.last(), Some(&CellSplitStepV1::SupervisorFence));
    let anchor = ledger.anchor();
    drop(ledger);

    let mut recovered = CellSplitExecutionOwnerV1::recover(reopen(&file), p, anchor)
        .expect("recover pending cutover");
    // No automatic rollback, and no route mutation on failed final-use/CAS.
    assert_eq!(recovered.drive(&mut owners), Err(CellSplitErrorV1::Conflict));
    assert_eq!(recovered.progress().accepted_steps, 6);
}

#[test]
fn observer_ack_is_required_before_first_external_mutation() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut ledger = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p)
        .expect("bootstrap");
    let mut owners = MockOwners {
        fail_anchor_once: true,
        ..Default::default()
    };
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Indeterminate));
    assert!(owners.attempts.is_empty());
    assert_eq!(ledger.progress().accepted_steps, 0);
    // The intent survived; the next attempt starts with an independently
    // acknowledged anchor and one idempotent effect, never duplicate intents.
    assert_eq!(ledger.drive(&mut owners), Err(CellSplitErrorV1::Unapproved));
    assert_eq!(owners.attempts.len(), 3);
    assert!(owners.anchors.contains_key(&ledger.anchor().sequence));
}


#[test]
fn canonical_plan_binding_separates_identity_boundaries() {
    let mut left = plan();
    left.split_id = id("s");
    left.predecessor_id = id("abc");
    left.child_id = id("d");
    let mut right = left.clone();
    right.split_id = id("sa");
    right.predecessor_id = id("bc");

    // Both ID triplets concatenate to "sabcd" without length tags.
    assert_eq!(
        format!(
            "{}{}{}",
            left.split_id, left.predecessor_id, left.child_id
        ),
        format!(
            "{}{}{}",
            right.split_id, right.predecessor_id, right.child_id
        )
    );
    assert_ne!(left.binding_digest(), right.binding_digest());
    for step in STEPS {
        assert_ne!(left.operation_key(step), right.operation_key(step));
    }
}

#[test]
fn bootstrap_repositions_nonzero_cursor_on_an_empty_file() {
    let file = NamedTempFile::new().expect("temp ledger");
    let mut handle = reopen(&file);
    handle.seek(SeekFrom::Start(4096)).expect("seek empty handle");
    assert_eq!(handle.metadata().expect("metadata").len(), 0);
    let p = plan();
    let owner = CellSplitExecutionOwnerV1::bootstrap(handle, p.clone())
        .expect("bootstrap normalized header");
    let initial = owner.anchor();
    assert_eq!(reopen(&file).metadata().expect("metadata").len(), HEADER_SIZE as u64);
    drop(owner);
    let recovered = CellSplitExecutionOwnerV1::recover(reopen(&file), p, initial)
        .expect("recovery from normalized header");
    assert_eq!(recovered.anchor(), initial);
}

#[derive(Default)]
struct MockRecoveryObserver {
    binding: Option<Digest32>,
    acknowledged: Option<CellSplitLedgerAnchorV1>,
}

impl CellSplitRecoveryObserverV1 for MockRecoveryObserver {
    fn verified_anchor(
        &mut self,
        plan: &CellSplitPlanV1,
    ) -> Result<CellSplitLedgerAnchorV1, CellSplitErrorV1> {
        if self.binding != Some(plan.binding_digest()) {
            return Err(CellSplitErrorV1::ScopeMismatch);
        }
        self.acknowledged.ok_or(CellSplitErrorV1::Unapproved)
    }
}

#[test]
fn public_recovery_requires_independently_authenticated_observer_anchor() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let anchored = owner.anchor();
    drop(owner);

    let mut missing = MockRecoveryObserver::default();
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover_from_observer(reopen(&file), p.clone(), &mut missing),
        Err(CellSplitErrorV1::ScopeMismatch)
    ));

    let mut forged_scope = MockRecoveryObserver {
        binding: Some(digest(b"wrong identity")),
        acknowledged: Some(anchored),
    };
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover_from_observer(
            reopen(&file),
            p.clone(),
            &mut forged_scope,
        ),
        Err(CellSplitErrorV1::ScopeMismatch)
    ));

    let mut acknowledged = MockRecoveryObserver {
        binding: Some(p.binding_digest()),
        acknowledged: Some(anchored),
    };
    let recovered = CellSplitExecutionOwnerV1::recover_from_observer(
        reopen(&file),
        p,
        &mut acknowledged,
    )
    .expect("observer-validated journal");
    assert_eq!(recovered.anchor(), anchored);
}

#[test]
fn terminal_receipt_without_independent_ack_is_not_completed() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let mut actors = MockOwners {
        // Seven steps each write a pending frame and accepted frame.
        // The completed cutover receipt is sequence 14, not an approved
        // terminal outcome until the independent observer retains it.
        fail_anchor_sequence_once: Some(14),
        ..Default::default()
    };
    actors.install(&p, CellSplitStepV1::IndependentSelection);
    actors.install(&p, CellSplitStepV1::FinalUseReady);

    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Indeterminate));
    assert_eq!(owner.progress().accepted_steps, 7);
    assert!(!owner.progress().completed);
    assert_eq!(owner.anchor().sequence, 14);
    assert!(!actors.anchors.contains_key(&14));

    assert!(owner.drive(&mut actors).expect("revalidate and retain").completed);
    assert_eq!(actors.attempts.len(), 5);
    assert_eq!(actors.anchors.get(&14), Some(&owner.anchor().head_digest));
}

#[test]
fn selection_candidate_mapping_changes_operation_keys() {
    let left = plan();
    let mut right = left.clone();
    right.selected_candidate_id = id("candidate:other");
    assert_eq!(left.child_id, right.child_id);
    assert_ne!(left.binding_digest(), right.binding_digest());
    assert_ne!(
        left.operation_key(CellSplitStepV1::CnsRouteCutover),
        right.operation_key(CellSplitStepV1::CnsRouteCutover)
    );
}

#[test]
fn split_binding_rejects_rebound_baseline_and_future_window() {
    let frozen = plan();
    let mut different_baseline = frozen.clone();
    different_baseline.no_change_baseline_digest = digest(b"other baseline");
    assert_ne!(frozen.binding_digest(), different_baseline.binding_digest());
    assert_ne!(
        frozen.operation_key(CellSplitStepV1::CnsRouteCutover),
        different_baseline.operation_key(CellSplitStepV1::CnsRouteCutover)
    );
    let mut wrong_objective = frozen.clone();
    wrong_objective.objective_digest = digest(b"other objective");
    assert_ne!(frozen.binding_digest(), wrong_objective.binding_digest());
    let mut too_short = frozen.clone();
    too_short.minimum_future_window_micros = 0;
    assert_eq!(too_short.validate(), Err(CellSplitErrorV1::InvalidPlan));
    let mut no_change_as_candidate = frozen.clone();
    no_change_as_candidate.no_change_baseline_id = frozen.selected_candidate_id.clone();
    assert_eq!(no_change_as_candidate.validate(), Err(CellSplitErrorV1::InvalidPlan));
}

#[test]
fn artifact_identity_is_independent_from_cell_and_candidate_ids() {
    let p = plan();
    assert_ne!(p.child_id, p.child_artifact_id);
    assert_ne!(p.selected_candidate_id, p.child_artifact_id);
    let mut switched_artifact = p.clone();
    switched_artifact.child_artifact_id = id("artifact:other-child");
    assert_ne!(p.binding_digest(), switched_artifact.binding_digest());
    assert_ne!(
        p.operation_key(CellSplitStepV1::ArtifactCas),
        switched_artifact.operation_key(CellSplitStepV1::ArtifactCas)
    );
    let mut other_storage = p.clone();
    other_storage.artifact_storage_binding_digest = digest(b"artifact-store:partition-2");
    assert_ne!(p.binding_digest(), other_storage.binding_digest());
    let mut stale_lineage = p.clone();
    stale_lineage.predecessor_artifact_id = id("artifact:wrong-parent");
    assert_ne!(p.binding_digest(), stale_lineage.binding_digest());
    let mut invalid_lineage = p.clone();
    invalid_lineage.child_artifact_id = invalid_lineage.predecessor_artifact_id.clone();
    assert_eq!(invalid_lineage.validate(), Err(CellSplitErrorV1::InvalidPlan));
}

#[test]
fn live_owner_rejects_a_truncated_ledger_before_any_side_effect() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p)
        .expect("bootstrap");
    let truncated = reopen(&file);
    truncated.set_len(0).expect("simulate out-of-band truncation");
    drop(truncated);

    let mut actors = MockOwners::default();
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Poisoned));
    assert!(!owner.progress().completed);
    assert!(actors.attempts.is_empty());
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Poisoned));
}

#[test]
fn live_owner_rejects_same_length_header_tampering_before_any_external_effect() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p)
        .expect("bootstrap");
    let original_length = reopen(&file).metadata().expect("metadata").len();

    let mut tamper = reopen(&file);
    tamper.seek(SeekFrom::Start(12)).expect("seek header");
    tamper.write_all(&[0xf5]).expect("change scope bytes");
    tamper.sync_all().expect("sync same-length corruption");
    drop(tamper);
    assert_eq!(reopen(&file).metadata().expect("metadata").len(), original_length);

    let mut actors = MockOwners::default();
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Poisoned));
    assert!(actors.attempts.is_empty());
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Poisoned));
}

#[test]
fn live_owner_rejects_same_length_accepted_frame_tampering_before_resume() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let mut owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p)
        .expect("bootstrap");
    let mut actors = MockOwners::default();
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Unapproved));
    assert_eq!(actors.attempts.len(), 3);

    let frame_boundary = HEADER_SIZE as u64 + 4 + FRAME_FIXED_SIZE as u64 - 1;
    let original_length = reopen(&file).metadata().expect("metadata").len();
    let mut tamper = reopen(&file);
    tamper.seek(SeekFrom::Start(frame_boundary)).expect("seek frame");
    tamper.write_all(&[0x5a]).expect("corrupt same-size frame checksum");
    tamper.sync_all().expect("sync frame corruption");
    drop(tamper);
    assert_eq!(reopen(&file).metadata().expect("metadata").len(), original_length);

    actors.install(&owner.plan, CellSplitStepV1::IndependentSelection);
    assert_eq!(owner.drive(&mut actors), Err(CellSplitErrorV1::Poisoned));
    assert_eq!(actors.attempts.len(), 3);
    assert_eq!(owner.progress().accepted_steps, 3);
}

#[test]
fn recovery_rejects_oversized_journal_without_mutating_it() {
    let file = NamedTempFile::new().expect("temp ledger");
    let p = plan();
    let owner = CellSplitExecutionOwnerV1::bootstrap(reopen(&file), p.clone())
        .expect("bootstrap");
    let anchor = owner.anchor();
    drop(owner);

    let oversized = reopen(&file);
    oversized
        .set_len(MAX_LEDGER_SIZE as u64 + 1)
        .expect("simulate oversized backing file");
    oversized.sync_all().expect("sync oversized file");
    drop(oversized);
    assert!(matches!(
        CellSplitExecutionOwnerV1::recover(reopen(&file), p, anchor),
        Err(CellSplitErrorV1::Corrupt)
    ));
    assert_eq!(
        reopen(&file).metadata().expect("metadata").len(),
        MAX_LEDGER_SIZE as u64 + 1
    );
}
