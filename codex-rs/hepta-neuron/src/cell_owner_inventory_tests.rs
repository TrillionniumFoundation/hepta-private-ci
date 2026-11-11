use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::cell_test_support::definition;
use crate::cell_test_support::input;
use crate::cell_test_support::proposal;
use crate::cell_test_support::scope;
use crate::*;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-owner-inventory-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&path));
        Self(path)
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(self.0.join(name)),
        )
    }

    fn witness(&self, name: &str) -> FileAnchorWitnessStore {
        checked(FileAnchorWitnessStore::open(
            self.file(&format!("{name}-witness")),
            JournalScope {
                scope_digest: d(name),
                objective_digest: d("inventory"),
            },
            checked(Generation::new(1)),
            /*max_records*/ 128,
        ))
    }

    fn decision(&self) -> CellOwnerJournalV1<FileAnchorWitnessStore> {
        checked(CellOwnerJournalV1::open(
            self.file("decision"),
            self.witness("decision"),
            vec![CellJournalPartitionV1 {
                scope: scope("run"),
                definition: definition(),
                source_frontier: d("frontier"),
                writer_epoch: 1,
            }],
            /*max_records*/ 128,
        ))
    }

    fn generation(&self, cell: &str, run: &str) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        let manifest = CellBackendManifestV2 {
            profile: "inventory-fixture".into(),
            source_digest: [1; 32],
            bundle_digest: [2; 32],
            encoder: Some([3; 32]),
            head: None,
            memory: Some([4; 32]),
            world_model: None,
            decoder: None,
            runtime_digest: [6; 32],
            device_digest: [7; 32],
            input_schema: [8; 32],
            state_schema: [9; 32],
            output_schema: [10; 32],
            learning: CellLearningBindingV2::Resumable {
                weights: [11; 32],
                optimizer: [12; 32],
                rng: [13; 32],
                sampler: [14; 32],
                training_cursor: [15; 32],
            },
            evolution: CellEvolutionBindingV2 {
                structure: [16; 32],
                lineage: [17; 32],
                source_dependencies: [18; 32],
                adoption_receipt: [19; 32],
            },
            max_input_bytes: 64,
            max_state_bytes: 256,
            max_delta_bytes: 64,
            max_prefix_bytes: 256,
            max_step_cost_entries: 32,
            max_ack_cost_entries: 16,
        };
        let initial = CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: scope(run).principal_digest.into_array(),
                agent_id: "agent".into(),
                cell_id: cell.into(),
                run_id: run.into(),
            },
            manifest_digest: checked(manifest.digest()),
            generation: 2,
            writer_epoch: 4,
            revision: 0,
            state: vec![1],
            prefix: Vec::new(),
            stopped: false,
        };
        checked(CellGenerationJournalV2::open(
            self.file("generation"),
            self.witness("generation"),
            CellGenerationConfigV2 {
                manifest,
                initial,
                source_frontier: [21; 32],
                task_digest: [22; 32],
            },
            /*max_records*/ 128,
        ))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn request(
    owner: &CellGenerationJournalV2<FileAnchorWitnessStore>,
    id: &str,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: id.into(),
        task_digest: [22; 32],
        source_frontier: [21; 32],
        predecessor: checked(owner.snapshot()).clone(),
        input: vec![2],
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

fn generation_proposal(request: &CellGenerationRequestV2) -> CellGenerationProposalV2 {
    CellGenerationProposalV2 {
        request_digest: checked(request.digest()),
        bundle_digest: [2; 32],
        runtime_digest: [6; 32],
        device_digest: [7; 32],
        successor_state: vec![2],
        output_delta: b"ok".to_vec(),
        disposition: CellGenerationDispositionV2::Advanced,
        cost: checked(CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: [22; 32],
            source_digest: [1; 32],
        })),
    }
}

#[test]
fn decision_view_tracks_real_admission_commit_reset_and_reopen() {
    let fixture = Fixture::new();
    let mut owner = fixture.decision();
    let original = checked(owner.observe_inventory(&scope("run")))
        .record()
        .clone();
    assert_eq!((&original.learning, &original.evolution), (&None, &None));
    let initial_bytes = checked(fs::read(fixture.0.join("decision")));
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&checked(
            owner.observe_inventory(&scope("run"))
        )]))
        .active_instance_count,
        0
    );
    assert_eq!(checked(fs::read(fixture.0.join("decision"))), initial_bytes);
    let proposed = proposal(&mut owner, input("run"));
    let view = checked(owner.observe_inventory(&scope("run")));
    assert_eq!(
        view.require_fence(original.fence),
        Err(CellOwnerInventoryErrorV1::StaleObservation)
    );
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&view])).active_instance_count,
        1
    );
    assert!(view.record().bytes.reserved_journal > 0);
    checked(commit_cell_step(
        &mut owner, proposed, /*now_micros*/ 13,
    ));
    let committed = checked(owner.observe_inventory(&scope("run")))
        .record()
        .clone();
    assert_eq!(
        (
            committed.revision,
            committed.pending_operation_digest,
            committed.bytes.reserved_journal
        ),
        (1, None, 0)
    );
    assert!(committed.checkpoint_digest.is_some());
    checked(owner.reset_at_frontier(
        &scope("run"),
        d("corrected-frontier"),
        /*writer_epoch*/ 2,
    ));
    let reset = checked(owner.observe_inventory(&scope("run")));
    assert_eq!(
        reset.require_fence(committed.fence),
        Err(CellOwnerInventoryErrorV1::StaleObservation)
    );
    assert_eq!(
        (
            reset.record().writer_epoch,
            reset.record().checkpoint_digest,
            reset.record().source_frontier
        ),
        (2, None, d("corrected-frontier"))
    );
    let expected = reset.record().clone();
    drop(owner);
    let reopened = fixture.decision();
    assert_eq!(
        checked(reopened.observe_inventory(&scope("run"))).record(),
        &expected
    );
    assert!(matches!(
        reopened.observe_inventory(&scope("other")),
        Err(CellExecutionError::ScopeMismatch)
    ));
}

#[test]
fn generation_view_preserves_unknown_work_learning_closure_and_delivery() {
    let fixture = Fixture::new();
    let mut owner = fixture.generation("generation-cell", "run");
    let req = request(&owner, "cancel");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let admitted = checked(owner.observe_inventory()).record().clone();
    checked(owner.cancel(checked(req.digest())));
    checked(owner.drain());
    let cancelled = checked(owner.observe_inventory());
    assert_eq!(
        cancelled.require_fence(admitted.fence),
        Err(CellOwnerInventoryErrorV1::StaleObservation)
    );
    assert_eq!(
        cancelled.backend(),
        CellOwnerBackendV1::GenerationV2(owner.manifest())
    );
    assert_eq!(
        cancelled.record().control,
        CellOwnerControlStateV1::GenerationV2 {
            draining: true,
            stopped: false,
            cancelled: true,
            dispatch_observed: false
        }
    );
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&cancelled])).active_instance_count,
        1
    );
    let retained = cancelled.record().clone();
    assert_eq!(
        (&retained.learning, &retained.evolution),
        (
            &Some(owner.manifest().learning.clone()),
            &Some(owner.manifest().evolution.clone())
        )
    );
    drop(owner);
    let mut owner = fixture.generation("generation-cell", "run");
    assert_eq!(checked(owner.observe_inventory()).record(), &retained);
    checked(owner.commit(generation_proposal(&req), /*now_micros*/ 20));
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&checked(
            owner.observe_inventory()
        )]))
        .active_instance_count,
        0
    );
    checked(owner.resume());
    let req = request(&owner, "deliver");
    checked(owner.admit(req.clone(), /*now_micros*/ 21));
    let proposed = generation_proposal(&req);
    let cost = proposed.cost.clone();
    checked(owner.commit(proposed, /*now_micros*/ 30));
    let delivering = checked(owner.observe_inventory()).record().clone();
    assert_eq!(
        (
            delivering.pending_operation_digest,
            delivering.pending_output_bytes
        ),
        (None, 2)
    );
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&checked(
            owner.observe_inventory()
        )]))
        .active_instance_count,
        1
    );
    let chunk = checked(
        checked(owner.pending_output())
            .cloned()
            .ok_or("pending delivery"),
    );
    checked(owner.acknowledge(chunk, [1; 32], cost));
    let complete = checked(owner.observe_inventory());
    assert_eq!(complete.record().revision, delivering.revision);
    assert_eq!(
        complete.require_fence(delivering.fence),
        Err(CellOwnerInventoryErrorV1::StaleObservation)
    );
    assert_eq!(
        checked(cell_owner_inventory_census_v1(&[&complete])).active_instance_count,
        0
    );
}

#[test]
fn census_rejects_count_inflation_cross_scope_and_dual_backend_slot_aliases() {
    let fixture = Fixture::new();
    let decision = fixture.decision();
    let first = checked(decision.observe_inventory(&scope("run")));
    assert_eq!(
        cell_owner_inventory_census_v1(&[&first, &first]),
        Err(CellOwnerInventoryErrorV1::DuplicateSlot)
    );
    let generation = fixture.generation("cell", "run");
    let alias = checked(generation.observe_inventory());
    assert_eq!(
        cell_owner_inventory_census_v1(&[&first, &alias]),
        Err(CellOwnerInventoryErrorV1::DuplicateSlot)
    );
    let separate = Fixture::new();
    let generation = separate.generation("generation-cell", "run");
    let second = checked(generation.observe_inventory());
    let census = checked(cell_owner_inventory_census_v1(&[&first, &second]));
    assert_eq!(
        (
            census.instance_count,
            census.active_instance_count,
            census.parameter_bundle_count
        ),
        (2, 0, 2)
    );
    let outside = Fixture::new();
    let generation = outside.generation("other-cell", "another-run");
    let wrong_scope = checked(generation.observe_inventory());
    assert_eq!(
        cell_owner_inventory_census_v1(&[&first, &wrong_scope]),
        Err(CellOwnerInventoryErrorV1::ScopeMismatch)
    );
    assert_eq!(
        wrong_scope.require_fence(second.record().fence),
        Err(CellOwnerInventoryErrorV1::ScopeMismatch)
    );
}

#[test]
fn uncertain_journal_cannot_export_a_healthy_population_view() {
    let fixture = Fixture::new();
    let mut owner = fixture.generation("generation-cell", "run");
    checked(
        checked(
            OpenOptions::new()
                .append(true)
                .open(fixture.0.join("generation")),
        )
        .write_all(b"partial"),
    );
    assert_eq!(owner.drain(), Err(CellGenerationErrorV2::CommitUncertain));
    assert!(matches!(
        owner.observe_inventory(),
        Err(CellGenerationErrorV2::CommitUncertain)
    ));
}
