use super::*;
use crate::RuntimeCellLifecyclePlanV2;
use crate::RuntimeCellStateComponentV2;
use crate::RuntimeCellStateManifestV2;
use crate::RuntimeCellStateRoleV2 as Role;
use crate::RuntimeCellVerifiedStateV2;
use crate::runtime_cell_state_transfer_digest_v2;

#[derive(Clone, Copy)]
enum Side { Predecessor, Successor }

fn materials(side: Side) -> Vec<Vec<u8>> {
    Role::ALL.into_iter().map(|role| {
        if role == Role::EffectLedger {
            b"effect:original-operation=applied;compensation=none".to_vec()
        } else {
            let label = match side { Side::Predecessor => "before", Side::Successor => "after" };
            format!("{label}:{role:?}:complete-partition-record").into_bytes()
        }
    }).collect()
}

fn manifest(plan: &RuntimeCellLifecyclePlanV1, side: Side, contents: &[Vec<u8>]) -> RuntimeCellStateManifestV2 {
    let (cells, generation, writer_id, writer_fence, topology, bundle) = match side {
        Side::Predecessor => (&plan.predecessors, plan.predecessor_generation, &plan.handoff.from_owner,
            plan.handoff.predecessor_writer_fence, plan.predecessor_topology, d("old-bundle")),
        Side::Successor => (&plan.successors, plan.successor_generation, &plan.handoff.to_owner,
            plan.handoff.successor_writer_fence, plan.successor_topology, plan.successor_bundle),
    };
    RuntimeCellStateManifestV2 {
        agent_id: plan.agent_id.clone(), principal_scope: plan.principal_scope, cells: cells.clone(),
        generation, writer_id: writer_id.clone(), writer_fence, topology, bundle,
        source_frontier: d("current-source-frontier"), inflight_requests: 0, unknown_effects: 0,
        components: Role::ALL.into_iter().zip(contents).map(|(role, bytes)| RuntimeCellStateComponentV2 {
            role,
            owner_id: if role == Role::PrivateState { writer_id.clone() } else { id(&format!("owner:{role:?}")) },
            owner_checkpoint: d(&format!("checkpoint:{role:?}")), schema: d(&format!("schema:{role:?}")),
            content_digest: Digest32::of_bytes(bytes), encoded_bytes: bytes.len() as u64,
        }).collect(),
    }
}

fn bind(
    mut plan: RuntimeCellLifecyclePlanV1,
    before: &RuntimeCellVerifiedStateV2<'_>,
    after: &RuntimeCellVerifiedStateV2<'_>,
) -> RuntimeCellLifecyclePlanV1 {
    plan.predecessor_state_root = before.state_root();
    plan.successor_state_root = after.state_root();
    plan.handoff = build_writer_handoff_plan_v1(
        plan.handoff.module_id.clone(), plan.handoff.from_owner.clone(), plan.handoff.to_owner.clone(),
        plan.handoff.predecessor_writer_fence, plan.handoff.successor_writer_fence,
        plan.handoff.source_store_digest,
        runtime_cell_state_transfer_digest_v2(before, after, d("transform"), d("qualification")).unwrap(),
        plan.handoff.rollback_digest, plan.handoff.acknowledgement_contract_digest,
    ).unwrap();
    plan
}

#[test]
fn complete_state_requires_every_role_and_exact_bytes_within_the_declared_budget() {
    let plan = plan(RuntimeCellStructuralChangeV1::Replace);
    let contents = materials(Side::Predecessor);
    let refs: Vec<&[u8]> = contents.iter().map(Vec::as_slice).collect();
    let original = manifest(&plan, Side::Predecessor, &contents);
    let verified = RuntimeCellVerifiedStateV2::verify(&original, &refs, /*maximum_bytes*/ 10_000).unwrap();
    assert_eq!(verified.state_root(), original.state_root().unwrap());
    assert_eq!(verified.manifest(), &original);
    assert_eq!(RuntimeCellVerifiedStateV2::verify(&original, &refs, /*maximum_bytes*/ 1).unwrap_err(), RuntimeCellLifecycleError::Capacity);
    let mut missing = original.clone();
    missing.components.remove(1);
    assert_eq!(RuntimeCellVerifiedStateV2::verify(&missing, &refs, /*maximum_bytes*/ 10_000).unwrap_err(), RuntimeCellLifecycleError::InvalidPlan);
    let mut changed = contents.clone();
    changed[1][0] ^= 1; // Same-size optimizer corruption cannot pass a root-only check.
    let changed_refs: Vec<&[u8]> = changed.iter().map(Vec::as_slice).collect();
    assert_eq!(RuntimeCellVerifiedStateV2::verify(&original, &changed_refs, /*maximum_bytes*/ 10_000).unwrap_err(), RuntimeCellLifecycleError::InvalidObservation);
    let mut oversized = original;
    oversized.components[0].encoded_bytes = u64::MAX;
    assert_eq!(RuntimeCellVerifiedStateV2::verify(&oversized, &refs, /*maximum_bytes*/ 10_000).unwrap_err(), RuntimeCellLifecycleError::Capacity);
}

#[test]
fn topology_binding_refuses_unknown_work_effect_rewinds_and_changed_frozen_candidates() {
    let initial = plan(RuntimeCellStructuralChangeV1::Replace);
    let before_bytes = materials(Side::Predecessor);
    let after_bytes = materials(Side::Successor);
    let before_refs: Vec<&[u8]> = before_bytes.iter().map(Vec::as_slice).collect();
    let after_refs: Vec<&[u8]> = after_bytes.iter().map(Vec::as_slice).collect();
    let before = manifest(&initial, Side::Predecessor, &before_bytes);
    let after = manifest(&initial, Side::Successor, &after_bytes);
    let before_pin = RuntimeCellVerifiedStateV2::verify(&before, &before_refs, /*maximum_bytes*/ 10_000).unwrap();
    let after_pin = RuntimeCellVerifiedStateV2::verify(&after, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
    let frozen = bind(initial, &before_pin, &after_pin);
    RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &after_pin, d("transform"), d("qualification")).unwrap();
    for unknown in [false, true] {
        let mut busy = before.clone();
        if unknown { busy.unknown_effects = 1; } else { busy.inflight_requests = 1; }
        let busy_pin = RuntimeCellVerifiedStateV2::verify(&busy, &before_refs, /*maximum_bytes*/ 10_000).unwrap();
        let bound = bind(frozen.clone(), &busy_pin, &after_pin);
        assert_eq!(RuntimeCellLifecyclePlanV2::new(&bound, &busy_pin, &after_pin, d("transform"), d("qualification")).unwrap_err(), RuntimeCellLifecycleError::ReconciliationRequired);
    }
    let mut rewound = after.clone();
    rewound.components.last_mut().unwrap().owner_checkpoint = d("older-effect-checkpoint");
    let rewind_pin = RuntimeCellVerifiedStateV2::verify(&rewound, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
    let rewind_plan = bind(frozen.clone(), &before_pin, &rewind_pin);
    assert_eq!(RuntimeCellLifecyclePlanV2::new(&rewind_plan, &before_pin, &rewind_pin, d("transform"), d("qualification")).unwrap_err(), RuntimeCellLifecycleError::InvalidObservation);
    for role in [Role::PrivateState, Role::Parameters] {
        let mut changed = after.clone();
        changed.components.iter_mut().find(|component| component.role == role).unwrap().owner_checkpoint = d("unfrozen-update");
        let changed_pin = RuntimeCellVerifiedStateV2::verify(&changed, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
        assert_eq!(RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &changed_pin, d("transform"), d("qualification")).unwrap_err(), RuntimeCellLifecycleError::InvalidPlan);
    }
    let mut foreign = after;
    foreign.principal_scope = d("another-principal");
    let foreign_pin = RuntimeCellVerifiedStateV2::verify(&foreign, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
    assert_eq!(RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &foreign_pin, d("transform"), d("qualification")).unwrap_err(), RuntimeCellLifecycleError::ScopeMismatch);
}

#[tokio::test]
async fn complete_state_uses_the_original_owner_observer_and_recovery_identity() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("complete-state-owner.sqlite");
    let initial = plan(RuntimeCellStructuralChangeV1::Split);
    let before_bytes = materials(Side::Predecessor);
    let after_bytes = materials(Side::Successor);
    let before_refs: Vec<&[u8]> = before_bytes.iter().map(Vec::as_slice).collect();
    let after_refs: Vec<&[u8]> = after_bytes.iter().map(Vec::as_slice).collect();
    let before = manifest(&initial, Side::Predecessor, &before_bytes);
    let after = manifest(&initial, Side::Successor, &after_bytes);
    let before_pin = RuntimeCellVerifiedStateV2::verify(&before, &before_refs, /*maximum_bytes*/ 10_000).unwrap();
    let after_pin = RuntimeCellVerifiedStateV2::verify(&after, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
    let frozen = bind(initial, &before_pin, &after_pin);
    let bound = RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &after_pin, d("transform"), d("qualification")).unwrap();
    let witness = Witness::new(&frozen.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(pool(&path).await, frozen.agent_id.clone(), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100).await.unwrap();
    let mut snapshot = bound.create(&mut journal, /*now_ms*/ 100).await.unwrap();
    let mut now = 101;
    while snapshot.stage().is_some() {
        let intent = bound.prepare_next(&mut journal, snapshot.revision(), now).await.unwrap();
        assert_eq!(intent.authority, codex_hepta_types::AuthorityPosture::DENY_ALL);
        journal.pool.close().await;
        drop(journal);
        journal = RuntimeCellLifecycleJournalV1::attach(pool(&path).await, frozen.agent_id.clone(), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100).await.unwrap();
        assert_eq!(journal.pending_intent(&frozen).await.unwrap(), Some(intent.clone()));
        let observed = observation(&frozen, &intent, now);
        let pending = journal.read(&frozen).await.unwrap();
        let mut wrong_bundle = observed.clone();
        wrong_bundle.bundle = d("authentic-but-unfrozen-bundle").to_string();
        assert_eq!(bound.record_observation(&mut journal, intent.prepared_revision, wrong_bundle, &Observer).await.unwrap_err(), RuntimeCellLifecycleError::InvalidObservation);
        if intent.stage == RuntimeCellLifecycleStageV1::TransferState {
            let mut absent = observed.clone();
            absent.outcome = RuntimeCellLifecycleNativeOutcomeV1::NotApplied;
            absent.state_root = frozen.predecessor_state_root.to_string();
            assert_eq!(bound.record_observation(&mut journal, intent.prepared_revision, absent.clone(), &Observer).await.unwrap_err(), RuntimeCellLifecycleError::InvalidObservation);
            absent.bundle = before.bundle.to_string();
            bound.validate_observed_bundle(&absent).unwrap();
        }
        assert_eq!(journal.read(&frozen).await.unwrap(), pending);
        assert_eq!(bound.record_observation(&mut journal, intent.prepared_revision, observed.clone(), &RevokedObserver).await.unwrap_err(), RuntimeCellLifecycleError::Authentication);
        assert_eq!(journal.read(&frozen).await.unwrap(), pending);
        snapshot = bound.record_observation(&mut journal, intent.prepared_revision, observed.clone(), &Observer).await.unwrap();
        assert_eq!(journal.read_observation(&frozen, intent.stage).await.unwrap(), Some(observed));
        now += 1;
    }
    assert!(snapshot.completed());
    assert_eq!((snapshot.revision(), witness.current().unwrap().sequence), (14, 15));
    assert_eq!(bound.plan_digest().unwrap(), frozen.digest().unwrap());
}


#[tokio::test]
async fn complete_state_recovery_reauthenticates_without_issuing_a_second_attempt() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("complete-state-recovery.sqlite");
    let initial = plan(RuntimeCellStructuralChangeV1::Split);
    let before_bytes = materials(Side::Predecessor);
    let after_bytes = materials(Side::Successor);
    let before_refs: Vec<&[u8]> = before_bytes.iter().map(Vec::as_slice).collect();
    let after_refs: Vec<&[u8]> = after_bytes.iter().map(Vec::as_slice).collect();
    let before = manifest(&initial, Side::Predecessor, &before_bytes);
    let after = manifest(&initial, Side::Successor, &after_bytes);
    let before_pin = RuntimeCellVerifiedStateV2::verify(&before, &before_refs, /*maximum_bytes*/ 10_000).unwrap();
    let after_pin = RuntimeCellVerifiedStateV2::verify(&after, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
    let frozen = bind(initial, &before_pin, &after_pin);
    let bound = RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &after_pin, d("transform"), d("qualification")).unwrap();
    let witness = Witness::new(&frozen.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(pool(&path).await, frozen.agent_id.clone(), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100).await.unwrap();
    bound.create(&mut journal, /*now_ms*/ 100).await.unwrap();
    let intent = bound.prepare_next(&mut journal, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    let observed = observation(&frozen, &intent, /*at*/ 102);
    let anchored_before = witness.current().unwrap();
    witness.refuse_once.store(true, Ordering::SeqCst);
    assert_eq!(bound.record_observation(&mut journal, intent.prepared_revision, observed.clone(), &Observer).await.unwrap_err(), RuntimeCellLifecycleError::CommitUncertain);
    assert_eq!(witness.current().unwrap(), anchored_before);
    journal.pool.close().await;
    drop(journal);

    let denied = bound.recover(pool(&path).await, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &RevokedObserver).await;
    assert!(matches!(denied, Err(RuntimeCellLifecycleError::Authentication)));
    assert_eq!(witness.current().unwrap(), anchored_before);
    let recovered = bound.recover(pool(&path).await, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &Observer).await.unwrap();
    assert_eq!(recovered.read_observation(&frozen, intent.stage).await.unwrap(), Some(observed.clone()));
    assert_eq!(recovered.pending_intent(&frozen).await.unwrap(), None);
    assert_eq!(witness.current().unwrap().sequence, anchored_before.sequence + 1);
    recovered.pool.close().await;
    drop(recovered);

    let acknowledged = witness.current().unwrap();
    let recovered = bound.recover(pool(&path).await, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &Observer).await.unwrap();
    assert_eq!(recovered.read_observation(&frozen, intent.stage).await.unwrap(), Some(observed));
    assert_eq!(witness.current().unwrap(), acknowledged);
    let event_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ?")
        .bind(frozen.agent_id.as_str()).fetch_one(&recovered.pool).await.unwrap();
    assert_eq!(event_count, 3);
}

#[tokio::test]
async fn complete_state_recovery_rejects_wrong_bundles_before_advancing_the_anchor() {
    // Check both a late observation and an already anchored observation before
    // an uncertain prepare. Validating only the unacknowledged tail is too weak.
    for wrong_bundle_in_prefix in [false, true] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("complete-state-profile.sqlite");
        let initial = plan(RuntimeCellStructuralChangeV1::Split);
        let before_bytes = materials(Side::Predecessor);
        let after_bytes = materials(Side::Successor);
        let before_refs: Vec<&[u8]> = before_bytes.iter().map(Vec::as_slice).collect();
        let after_refs: Vec<&[u8]> = after_bytes.iter().map(Vec::as_slice).collect();
        let before = manifest(&initial, Side::Predecessor, &before_bytes);
        let after = manifest(&initial, Side::Successor, &after_bytes);
        let before_pin = RuntimeCellVerifiedStateV2::verify(&before, &before_refs, /*maximum_bytes*/ 10_000).unwrap();
        let after_pin = RuntimeCellVerifiedStateV2::verify(&after, &after_refs, /*maximum_bytes*/ 10_000).unwrap();
        let frozen = bind(initial, &before_pin, &after_pin);
        let bound = RuntimeCellLifecyclePlanV2::new(&frozen, &before_pin, &after_pin, d("transform"), d("qualification")).unwrap();
        let witness = Witness::new(&frozen.agent_id);
        let mut journal = RuntimeCellLifecycleJournalV1::attach(pool(&path).await, frozen.agent_id.clone(), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100).await.unwrap();
        bound.create(&mut journal, /*now_ms*/ 100).await.unwrap();
        let intent = bound.prepare_next(&mut journal, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
        let mut observed = observation(&frozen, &intent, /*at*/ 102);
        observed.bundle = d("authenticated-but-unfrozen-predecessor-bundle").to_string();
        if wrong_bundle_in_prefix {
            let snapshot = journal.record_observation(&frozen, intent.prepared_revision, observed.clone(), &Observer).await.unwrap();
            witness.refuse_once.store(true, Ordering::SeqCst);
            assert_eq!(bound.prepare_next(&mut journal, snapshot.revision(), /*now_ms*/ 103).await.unwrap_err(), RuntimeCellLifecycleError::CommitUncertain);
        } else {
            witness.refuse_once.store(true, Ordering::SeqCst);
            assert_eq!(journal.record_observation(&frozen, intent.prepared_revision, observed.clone(), &Observer).await.unwrap_err(), RuntimeCellLifecycleError::CommitUncertain);
        }
        let anchored_before = witness.current().unwrap();
        journal.pool.close().await;
        drop(journal);

        let denied = bound.recover(pool(&path).await, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &Observer).await;
        assert!(matches!(denied, Err(RuntimeCellLifecycleError::InvalidObservation)));
        assert_eq!(witness.current().unwrap(), anchored_before);

        // V1 history keeps its original rules. A profile upgrade must still
        // reject an incompatible prefix even after V1 has acknowledged it.
        let recovered_v1 = RuntimeCellLifecycleJournalV1::recover(pool(&path).await, &frozen, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &Observer).await.unwrap();
        assert_eq!(recovered_v1.read_observation(&frozen, intent.stage).await.unwrap(), Some(observed));
        let event_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ?")
            .bind(frozen.agent_id.as_str()).fetch_one(&recovered_v1.pool).await.unwrap();
        assert_eq!(event_count, if wrong_bundle_in_prefix { 4 } else { 3 });
        recovered_v1.pool.close().await;
        drop(recovered_v1);
        let acknowledged = witness.current().unwrap();
        let denied = bound.recover(pool(&path).await, /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100, &Observer).await;
        assert!(matches!(denied, Err(RuntimeCellLifecycleError::InvalidObservation)));
        assert_eq!(witness.current().unwrap(), acknowledged);
    }
}
