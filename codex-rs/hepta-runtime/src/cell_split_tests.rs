use super::*;
use codex_hepta_types::Generation;
use tempfile::tempdir;

#[derive(Debug)]
struct FixtureChild {
    id: String,
    fail: bool,
}

impl CellSplitChildMigrationV1 for FixtureChild {
    fn child_id(&self) -> &str {
        &self.id
    }

    fn migrate(
        &mut self,
        input: &CellSplitChildInputV1<'_>,
    ) -> Result<CellSplitChildStateV1, CellSplitMigrationError> {
        if self.fail {
            return Err(CellSplitMigrationError::ChildFailed {
                child_id: self.id.clone(),
            });
        }
        Ok(CellSplitChildStateV1 {
            child_id: self.id.clone(),
            candidate_weights: input.spec.candidate_weights,
            selected_weights: input.parent.selected_weights,
            recurrent_state: [input.parent.recurrent_state.as_slice(), self.id.as_bytes()].concat(),
            eligibility_state: input.parent.eligibility_state.clone(),
            optimizer_state: input.parent.optimizer_state.clone(),
            cache: input.parent.cache.clone(),
            cache_generation: input.candidate_generation,
            message_fence: input.parent.message_fence(),
        })
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn parent() -> CellSplitParentStateV1 {
    CellSplitParentStateV1 {
        checkpoint: CellSplitCheckpointV1 {
            generation: 7,
            digest: digest("parent-checkpoint"),
            committed: true,
        },
        selected_weights: digest("selected-weights"),
        recurrent_state: b"recurrent".to_vec(),
        eligibility_state: b"eligibility".to_vec(),
        optimizer_state: b"optimizer".to_vec(),
        cache: b"cache".to_vec(),
        cache_generation: 7,
        in_flight: Vec::new(),
    }
}

fn plan(parent: &CellSplitParentStateV1) -> CellSplitPlanV1 {
    CellSplitPlanV1 {
        parent_generation: 7,
        candidate_generation: 8,
        predecessor_writer_fence: 7,
        successor_writer_fence: 8,
        selected_weights: parent.selected_weights,
        migration_digest: digest("migration"),
        rollback_digest: digest("rollback"),
        children: vec![
            CellSplitChildSpecV1 {
                child_id: "child-a".to_owned(),
                candidate_weights: digest("candidate-a"),
                transform_digest: digest("transform-a"),
            },
            CellSplitChildSpecV1 {
                child_id: "child-b".to_owned(),
                candidate_weights: digest("candidate-b"),
                transform_digest: digest("transform-b"),
            },
        ],
    }
}

fn children() -> Vec<Box<dyn CellSplitChildMigrationV1>> {
    vec![
        Box::new(FixtureChild {
            id: "child-a".to_owned(),
            fail: false,
        }),
        Box::new(FixtureChild {
            id: "child-b".to_owned(),
            fail: false,
        }),
    ]
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

#[test]
fn split_migrates_all_state_domains_without_selecting_weights() {
    let parent = parent();
    let original = parent.clone();
    let plan = plan(&parent);
    let mut owner =
        CellSplitMigrationOwnerV1::new_in_memory(plan, digest("handoff"), parent, children())
            .expect("owner");

    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    owner
        .migrate(&snapshot, generation(7), generation(8))
        .expect("migration");

    assert_eq!(owner.phase(), CellSplitPhaseV1::Committed);
    assert_eq!(owner.state().parent, original);
    assert_eq!(owner.state().children.len(), 2);
    assert_eq!(
        owner.state().children[0].selected_weights,
        original.selected_weights
    );
    assert_eq!(owner.state().children[0].cache_generation, 8);
    assert!(owner.state().children.iter().all(|child| {
        child.selected_weights == original.selected_weights
            && child.message_fence == original.message_fence()
    }));
}

#[test]
fn in_flight_messages_are_a_deterministic_fence() {
    let mut parent = parent();
    parent.in_flight.push(CellSplitInFlightMessageV1 {
        message_id: "message-1".to_owned(),
        source_generation: 7,
        payload: b"payload".to_vec(),
    });
    let result = CellSplitMigrationOwnerV1::new_in_memory(
        plan(&parent),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner")
    .snapshot(generation(7));
    assert!(matches!(result, Err(OrganMigrationError::Callback(_))));
}

#[test]
fn child_failure_rolls_back_the_complete_split() {
    let parent = parent();
    let original = parent.clone();
    let mut callbacks = children();
    callbacks[1] = Box::new(FixtureChild {
        id: "child-b".to_owned(),
        fail: true,
    });
    let mut owner = CellSplitMigrationOwnerV1::new_in_memory(
        plan(&parent),
        digest("handoff"),
        parent,
        callbacks,
    )
    .expect("owner");
    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    assert!(
        owner
            .migrate(&snapshot, generation(7), generation(8))
            .is_err()
    );
    owner
        .rollback(&snapshot, generation(7), generation(8))
        .expect("rollback");
    assert_eq!(owner.state().parent, original);
    assert!(owner.state().children.is_empty());
    assert_eq!(owner.phase(), CellSplitPhaseV1::RolledBack);
}

#[test]
fn committed_candidate_can_roll_back_when_predecessor_stop_fails() {
    let parent = parent();
    let original = parent.clone();
    let mut owner = CellSplitMigrationOwnerV1::new_in_memory(
        plan(&parent),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner");
    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    owner
        .migrate(&snapshot, generation(7), generation(8))
        .expect("migration");
    assert_eq!(owner.writer_fence(), 8);
    owner
        .rollback(&snapshot, generation(7), generation(8))
        .expect("rollback");
    assert_eq!(owner.state().parent, original);
    assert!(owner.state().children.is_empty());
    assert_eq!(owner.writer_fence(), 7);
}

#[test]
fn rollback_failure_quarantines_after_partial_child() {
    let parent = parent();
    let mut owner = CellSplitMigrationOwnerV1::new_in_memory(
        plan(&parent),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner");
    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    owner.set_failpoint(CellSplitFailPointV1::Child("child-b".to_owned()));
    assert!(
        owner
            .migrate(&snapshot, generation(7), generation(8))
            .is_err()
    );
    owner.set_failpoint(CellSplitFailPointV1::Rollback);
    assert!(
        owner
            .rollback(&snapshot, generation(7), generation(8))
            .is_err()
    );
    assert!(owner.is_quarantined());
}

#[test]
fn crash_after_prepare_reopens_quarantined() {
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("cell-split.journal");
    let parent = parent();
    let plan = plan(&parent);
    let mut owner = CellSplitMigrationOwnerV1::create_persistent(
        &path,
        plan.clone(),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner");
    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    owner.set_failpoint(CellSplitFailPointV1::CrashAfterPrepare);
    assert!(
        owner
            .migrate(&snapshot, generation(7), generation(8))
            .is_err()
    );
    drop(owner);

    let reopened =
        CellSplitMigrationOwnerV1::reopen_persistent(&path, plan, digest("handoff"), children())
            .expect("reopen");
    assert!(reopened.is_quarantined());
}

#[test]
fn committed_journal_reopens_with_children_and_witness() {
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("cell-split-committed.journal");
    let parent = parent();
    let plan = plan(&parent);
    let mut owner = CellSplitMigrationOwnerV1::create_persistent(
        &path,
        plan.clone(),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner");
    let snapshot = owner.snapshot(generation(7)).expect("snapshot");
    owner
        .migrate(&snapshot, generation(7), generation(8))
        .expect("migration");
    let head = owner.journal_head();
    drop(owner);

    let reopened =
        CellSplitMigrationOwnerV1::reopen_persistent(&path, plan, digest("handoff"), children())
            .expect("reopen");
    assert_eq!(reopened.phase(), CellSplitPhaseV1::Committed);
    assert_eq!(reopened.journal_head(), head);
    assert_eq!(reopened.state().children.len(), 2);
    assert_eq!(reopened.writer_fence(), 8);
}

#[test]
fn stale_reopened_writer_loses_the_journal_cas() {
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("cell-split-cas.journal");
    let parent = parent();
    let plan = plan(&parent);
    let mut owner = CellSplitMigrationOwnerV1::create_persistent(
        &path,
        plan.clone(),
        digest("handoff"),
        parent,
        children(),
    )
    .expect("owner");
    let mut stale =
        CellSplitMigrationOwnerV1::reopen_persistent(&path, plan, digest("handoff"), children())
            .expect("stale reopen");
    let _snapshot = owner.snapshot(generation(7)).expect("snapshot");
    assert!(stale.snapshot(generation(7)).is_err());
}

#[test]
fn stale_writer_and_immutable_weight_bindings_are_rejected() {
    let parent = parent();
    let mut stale_plan = plan(&parent);
    stale_plan.predecessor_writer_fence = 6;
    assert!(matches!(
        CellSplitMigrationOwnerV1::new_in_memory(
            stale_plan,
            digest("handoff"),
            parent.clone(),
            children(),
        ),
        Err(CellSplitMigrationError::InvalidPlan("generation/fence"))
    ));

    let original_plan = plan(&parent);
    let mut changed = parent;
    changed.selected_weights = digest("other-weights");
    assert!(matches!(
        CellSplitMigrationOwnerV1::new_in_memory(
            original_plan,
            digest("handoff"),
            changed,
            children(),
        ),
        Err(CellSplitMigrationError::InvalidState("parent checkpoint"))
    ));
}

#[test]
fn missing_child_is_rejected_before_any_snapshot() {
    let parent = parent();
    let callbacks = vec![Box::new(FixtureChild {
        id: "child-a".to_owned(),
        fail: false,
    }) as Box<dyn CellSplitChildMigrationV1>];
    assert!(matches!(
        CellSplitMigrationOwnerV1::new_in_memory(
            plan(&parent),
            digest("handoff"),
            parent,
            callbacks,
        ),
        Err(CellSplitMigrationError::PartialChild { child_id }) if child_id == "child-b"
    ));
}
