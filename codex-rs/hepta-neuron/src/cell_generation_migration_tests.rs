use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::super::support::*;
use super::*;
use crate::FileAnchorWitnessStore;
use crate::WitnessStoreError;
use crate::cell_task_cost::CellCostStageV2;
use crate::cell_test_support::checked;

// The test host owns its current selection and source view independently from
// caller-provided manifests. Production implementations authenticate this view
// through the existing artifact/source owner; a digest alone is never a grant.
struct QualifiedVerifier {
    selected: Option<CellGenerationConfigV2>,
    source_snapshot: CellRuntimeSnapshotV2,
    source_checkpoint: Digest32,
    source_frontier: [u8; 32],
    converted: CellGenerationMigratedStateV2,
    guard: Arc<AtomicBool>,
    calls: usize,
    lose_ack: bool,
}

impl QualifiedVerifier {
    fn new<W: AnchorWitnessStore>(
        owner: &CellGenerationJournalV2<W>,
        target: &CellGenerationConfigV2,
    ) -> Self {
        let source_snapshot = checked(owner.snapshot()).clone();
        let mut state = source_snapshot.state.clone();
        state.push(9);
        let mut cost = cost();
        checked(cost.record(charge(
            &format!("migration-{}", target.initial.generation),
            CellCostStageV2::Migration,
        )));
        Self {
            selected: Some(target.clone()),
            source_snapshot,
            source_checkpoint: checked(owner.continuity_checkpoint()),
            source_frontier: owner.source_frontier(),
            converted: CellGenerationMigratedStateV2 { state, cost },
            guard: Arc::new(AtomicBool::new(false)),
            calls: 0,
            lose_ack: false,
        }
    }
}

impl CellGenerationMigrationVerifierV2 for QualifiedVerifier {
    fn with_verified_migration<T>(
        &mut self,
        context: &CellGenerationMigrationContextV2,
        apply: impl FnOnce(CellGenerationMigratedStateV2) -> Result<T, CellGenerationErrorV2>,
    ) -> Result<T, CellGenerationErrorV2> {
        self.calls += 1;
        if self.selected.as_ref() != Some(&context.target_config)
            || self.source_snapshot != context.source_snapshot
            || self.source_checkpoint != context.source_checkpoint
            || self.source_frontier != context.source_config.source_frontier
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.guard.store(true, Ordering::SeqCst);
        let result = apply(self.converted.clone());
        self.guard.store(false, Ordering::SeqCst);
        if self.lose_ack && result.is_ok() {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        result
    }
}

fn target<W: AnchorWitnessStore>(
    owner: &CellGenerationJournalV2<W>,
    manifest: CellBackendManifestV2,
) -> CellGenerationConfigV2 {
    let mut target = owner.config.clone();
    target.initial.manifest_digest = checked(manifest.digest());
    target.initial.generation = checked(owner.snapshot()).generation + 1;
    target.initial.writer_epoch = checked(owner.snapshot()).writer_epoch + 1;
    target.manifest = manifest;
    target
}

fn next_model() -> CellBackendManifestV2 {
    let mut manifest = config().manifest;
    manifest.bundle_digest = [40; 32];
    manifest.encoder = Some([41; 32]);
    manifest.learning = CellLearningBindingV2::Frozen { weights: [42; 32] };
    manifest.evolution.lineage = [43; 32];
    manifest.evolution.adoption_receipt = [44; 32];
    manifest
}

fn append<W: AnchorWitnessStore>(
    owner: &mut CellGenerationJournalV2<W>,
    operation: &str,
    admitted_at: u64,
    byte: u8,
) -> (CellGenerationRequestV2, CellGenerationReceiptV2) {
    let mut request = request(owner, operation);
    request.admitted_at_micros = admitted_at;
    request.deadline_micros = admitted_at + 100;
    checked(owner.admit(request.clone(), admitted_at));
    let mut proposal = proposal(&request);
    proposal.bundle_digest = owner.manifest().bundle_digest;
    proposal.successor_state = request.predecessor.state.clone();
    proposal.successor_state.push(byte);
    proposal.output_delta = vec![byte];
    let receipt = checked(owner.commit(proposal, admitted_at + 1));
    let chunk = checked(checked(owner.pending_output()).cloned().ok_or("outbox"));
    checked(owner.acknowledge(
        chunk,
        Digest32::of_bytes(operation.as_bytes()).into_array(),
        cost(),
    ));
    (request, receipt)
}

#[test]
fn upgrade_new_write_and_rollback_keep_latest_prefix_receipts_and_cost() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let (first_request, first_receipt) =
        append(&mut owner, "before", /*admitted_at*/ 10, b'A');
    let mut stale_consumer = request(&owner, "stale-consumer");
    stale_consumer.admitted_at_micros = 40;
    checked(owner.drain());
    let before = owner.state.clone();
    let target_v2 = target(&owner, next_model());
    let mut verifier = QualifiedVerifier::new(&owner, &target_v2);
    let receipt = checked(owner.migrate_to(
        fixture.file("v2"),
        target_v2.clone(),
        &mut verifier,
        /*now_micros*/ 30,
    ));
    let mut expected = before;
    expected.snapshot.manifest_digest = checked(target_v2.manifest.digest());
    expected.snapshot.generation = 2;
    expected.snapshot.writer_epoch = 2;
    expected.snapshot.state = verifier.converted.state.clone();
    expected.last_observed_micros = 30;
    for entry in verifier.converted.cost.entries() {
        checked(expected.cost.record(entry.clone()));
    }
    assert_eq!(owner.state, expected);
    assert_eq!(
        (receipt.generation, receipt.writer_epoch, verifier.calls),
        (2, 2, 1)
    );
    assert_eq!(checked(owner.is_drained()), true);
    drop(owner);
    assert_eq!(
        CellGenerationJournalV2::open(
            fixture.file("v2"),
            fixture.witness(),
            config(),
            /*max_records*/ 128
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("v2"),
        fixture.witness(),
        target_v2,
        /*max_records*/ 128,
    ));
    assert_eq!(owner.state, expected);
    checked(owner.resume());
    assert_eq!(
        owner.admit(stale_consumer, /*now_micros*/ 40),
        Err(CellGenerationErrorV2::Conflict)
    );
    let (second_request, second_receipt) =
        append(&mut owner, "after-upgrade", /*admitted_at*/ 50, b'B');
    checked(owner.drain());
    let latest = owner.state.clone();
    let target_v3 = target(&owner, config().manifest);
    let mut verifier = QualifiedVerifier::new(&owner, &target_v3);
    checked(owner.migrate_to(
        fixture.file("rollback"),
        target_v3.clone(),
        &mut verifier,
        /*now_micros*/ 70,
    ));
    let mut expected = latest;
    expected.snapshot.manifest_digest = checked(target_v3.manifest.digest());
    expected.snapshot.generation = 3;
    expected.snapshot.writer_epoch = 3;
    expected.snapshot.state = verifier.converted.state.clone();
    expected.last_observed_micros = 70;
    for entry in verifier.converted.cost.entries() {
        checked(expected.cost.record(entry.clone()));
    }
    assert_eq!(owner.state, expected);
    assert_eq!(checked(owner.snapshot()).prefix, b"AB");
    assert_eq!(checked(owner.snapshot()).state, vec![1, b'A', 9, b'B', 9]);
    assert_eq!(checked(owner.lookup(&first_request)), Some(first_receipt));
    assert_eq!(checked(owner.lookup(&second_request)), Some(second_receipt));
    assert_eq!(checked(owner.task_cost()).entries().len(), 4);
    drop(owner);
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("rollback"),
        fixture.witness(),
        target_v3,
        /*max_records*/ 128,
    ));
    assert_eq!(owner.state, expected);
    checked(owner.resume());
    append(&mut owner, "after-rollback", /*admitted_at*/ 80, b'C');
    assert_eq!(checked(owner.snapshot()).prefix, b"ABC");
}

#[test]
fn pending_unknown_or_unacknowledged_output_cannot_enter_migration() {
    for settle in [false, true] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let request = request(&owner, "in-flight");
        checked(owner.admit(request.clone(), /*now_micros*/ 10));
        checked(owner.observe_dispatch_time(checked(request.digest()), /*observed_at_micros*/ 11));
        if settle {
            checked(owner.commit(proposal(&request), /*now_micros*/ 20));
        }
        checked(owner.drain());
        let before = owner.state.clone();
        let bytes = fixture.bytes();
        let target = target(&owner, next_model());
        let mut verifier = QualifiedVerifier::new(&owner, &target);
        assert_eq!(
            owner.migrate_to(
                fixture.file("v2"),
                target,
                &mut verifier,
                /*now_micros*/ 30
            ),
            Err(CellGenerationErrorV2::Pending)
        );
        assert_eq!(owner.state, before);
        assert_eq!(fixture.bytes(), bytes);
        assert_eq!(checked(fs::metadata(fixture.0.join("v2"))).len(), 0);
        assert_eq!(verifier.calls, 0);
    }
}

#[test]
fn withdrawal_invalid_conversion_and_stale_source_view_cannot_publish() {
    for case in 0..3 {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        append(&mut owner, "before", /*admitted_at*/ 10, b'A');
        checked(owner.drain());
        let target = target(&owner, next_model());
        let mut verifier = QualifiedVerifier::new(&owner, &target);
        let expected_error = match case {
            0 => {
                verifier.selected = None;
                CellGenerationErrorV2::InvalidBinding
            }
            1 => {
                verifier.converted.state = vec![0; 65_537];
                CellGenerationErrorV2::Capacity
            }
            2 => {
                verifier.source_frontier = [99; 32];
                CellGenerationErrorV2::InvalidBinding
            }
            _ => unreachable!(),
        };
        let before = owner.state.clone();
        let archive = fixture.bytes();
        assert_eq!(
            owner.migrate_to(
                fixture.file("v2"),
                target,
                &mut verifier,
                /*now_micros*/ 30
            ),
            Err(expected_error)
        );
        assert_eq!(owner.state, before);
        assert_eq!(fixture.bytes(), archive);
        assert_eq!(checked(fs::metadata(fixture.0.join("v2"))).len(), 0);
        assert_eq!(verifier.calls, 1);
    }
}

#[test]
fn incompatible_source_code_schema_scope_or_epoch_is_refused_before_verifier() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    checked(owner.drain());
    for case in 0..12 {
        let mut target = target(&owner, next_model());
        match case {
            0 => target.task_digest = [88; 32],
            1 => target.manifest.source_digest = [88; 32],
            2 => target.manifest.runtime_digest = [88; 32],
            3 => target.manifest.device_digest = [88; 32],
            4 => target.manifest.input_schema = [88; 32],
            5 => target.manifest.state_schema = [88; 32],
            6 => target.manifest.output_schema = [88; 32],
            7 => target.initial.scope.run_id = "other-run".to_string(),
            8 => target.initial.generation = 3,
            9 => target.initial.writer_epoch = 1,
            10 => target.manifest.max_step_cost_entries = 31,
            11 => target.source_frontier = [88; 32],
            _ => unreachable!(),
        }
        target.initial.manifest_digest = checked(target.manifest.digest());
        let mut verifier = QualifiedVerifier::new(&owner, &target);
        let before = owner.state.clone();
        assert_eq!(
            owner.migrate_to(
                fixture.file("v2"),
                target,
                &mut verifier,
                /*now_micros*/ 30
            ),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
        assert_eq!(owner.state, before);
        assert_eq!(verifier.calls, 0);
        assert_eq!(checked(fs::metadata(fixture.0.join("v2"))).len(), 0);
    }
}

struct GuardedWitness {
    inner: FileAnchorWitnessStore,
    guard: Arc<AtomicBool>,
    enforce: Arc<AtomicBool>,
}

impl AnchorWitnessStore for GuardedWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.enforce.load(Ordering::SeqCst) {
            assert!(self.guard.load(Ordering::SeqCst));
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn migration_witness_switch_stays_inside_live_source_barrier_even_with_lost_ack() {
    let fixture = Fixture::new();
    let guard = Arc::new(AtomicBool::new(false));
    let enforce = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        GuardedWitness {
            inner: fixture.witness(),
            guard: Arc::clone(&guard),
            enforce: Arc::clone(&enforce),
        },
        config(),
        /*max_records*/ 128,
    ));
    append(&mut owner, "before", /*admitted_at*/ 10, b'A');
    checked(owner.drain());
    let target = target(&owner, next_model());
    let mut verifier = QualifiedVerifier::new(&owner, &target);
    verifier.guard = Arc::clone(&guard);
    verifier.lose_ack = true;
    enforce.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.migrate_to(
            fixture.file("v2"),
            target.clone(),
            &mut verifier,
            /*now_micros*/ 30
        ),
        Err(CellGenerationErrorV2::Unavailable)
    );
    assert!(!guard.load(Ordering::SeqCst));
    assert_eq!(
        owner.snapshot(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    drop(owner);
    assert_eq!(
        CellGenerationJournalV2::open(
            fixture.file("journal"),
            fixture.witness(),
            config(),
            /*max_records*/ 128
        )
        .err(),
        Some(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    let owner = checked(CellGenerationJournalV2::open(
        fixture.file("v2"),
        fixture.witness(),
        target,
        /*max_records*/ 128,
    ));
    assert_eq!(checked(owner.snapshot()).prefix, b"A");
    assert_eq!(checked(owner.snapshot()).generation, 2);
    assert_eq!(checked(owner.is_drained()), true);
}
