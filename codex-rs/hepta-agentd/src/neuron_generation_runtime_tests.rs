use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use pretty_assertions::assert_eq;
use tokio::time::timeout;

use super::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

#[cfg(target_os = "linux")]
#[path = "neuron_generation_joint_tests.rs"]
mod joint;
#[path = "neuron_generation_observation_tests.rs"]
mod observation;
#[path = "neuron_generation_runtime_test_support.rs"]
mod support;
use support::Fixture;
use support::checked;
use support::cost;
use support::generation;
use support::host;
use support::poll_pending;
use support::request;

const SERVICE: &str = "neuron-generation";

#[tokio::test]
async fn absent_service_is_not_a_blocker_but_unstarted_or_closed_bootstrap_is() {
    let fixture = Fixture::new().await;
    assert_eq!(
        checked(fixture.state().neuron_generation_drain_blockers()),
        0
    );
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    checked(bootstrap.attach(fixture.state()));
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    fixture.begin_drain();
    assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
    assert!(
        timeout(
            Duration::from_millis(30),
            crate::runtime::drain_runtime(Arc::clone(fixture.state())),
        )
        .await
        .is_err()
    );
    drop(bootstrap);
    assert_eq!(
        handle.snapshot().await,
        Err(CellGenerationErrorV2::Unavailable)
    );
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn closing_the_last_handle_invalidates_an_idle_drain_observation_immediately() {
    let fixture = Fixture::new().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    checked(handle.snapshot().await);
    fixture.begin_drain();
    checked(handle.snapshot().await);
    assert_eq!(
        checked(fixture.state().neuron_generation_drain_blockers()),
        0
    );
    drop(handle);
    // No yield: closed transport invalidates the sample before the actor can
    // poll its receiver and quarantine itself.
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
    tasks.shutdown().await;
}

#[tokio::test]
async fn partial_startup_failure_preserves_the_configured_unknown_blocker() {
    let fixture = Fixture::new().await;
    let (_, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 1,
    ));
    checked(bootstrap.attach(fixture.state()));
    let (mut tasks, lifetime) = host();
    for index in 0..128 {
        checked(tasks.spawn_required(&format!("occupied-{index}"), std::future::pending()));
    }
    assert!(
        spawn_neuron_generation_service(
            &mut tasks,
            bootstrap,
            Arc::clone(fixture.state()),
            lifetime.clone()
        )
        .is_err()
    );
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    fixture.begin_drain();
    assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
    assert!(
        timeout(
            Duration::from_millis(30),
            crate::runtime::drain_runtime(Arc::clone(fixture.state()))
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
}

#[tokio::test]
async fn bounded_queue_and_drain_before_worker_start_prevent_model_entry() {
    let fixture = Fixture::new().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 1,
    ));
    checked(bootstrap.attach(fixture.state()));
    let first = handle.step(request("queued-first", fixture.config.initial.clone()));
    tokio::pin!(first);
    poll_pending(first.as_mut());
    assert_eq!(
        handle
            .step(request("queue-full", fixture.config.initial.clone()))
            .await,
        Err(CellGenerationErrorV2::Capacity)
    );
    fixture.begin_drain();
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    assert!(checked(timeout(Duration::from_secs(1), first).await).is_err());
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
}

#[tokio::test]
async fn queued_old_cancel_and_reconcile_cannot_target_a_new_pending_operation() {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    fixture
        .control
        .signals
        .readable
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let first = request("first", checked(handle.snapshot().await));
    let first_digest = checked(first.digest());
    assert!(handle.step(first).await.is_err());
    checked(handle.reconcile(first_digest).await);
    let first_chunk =
        checked(handle.pending_output().await).unwrap_or_else(|| panic!("first output"));
    checked(
        handle
            .acknowledge(first_chunk.clone(), [21; 32], cost())
            .await,
    );

    let second = request("second", checked(handle.snapshot().await));
    let second_digest = checked(second.digest());
    let step = handle.step(second.clone());
    let stale_cancel = handle.cancel(first_digest);
    tokio::pin!(step);
    tokio::pin!(stale_cancel);
    // Both messages enter before the worker is polled. The cancel still names A
    // after the preceding queued command has installed B as the pending request.
    poll_pending(step.as_mut());
    poll_pending(stale_cancel.as_mut());
    assert!(step.await.is_err());
    assert_eq!(stale_cancel.await, Err(CellGenerationErrorV2::Conflict));
    let reads = fixture.control.signals.reads.load(Ordering::SeqCst);
    assert_eq!(
        handle.reconcile(first_digest).await,
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), reads);
    assert_eq!(
        fixture.control.signals.cancellations.load(Ordering::SeqCst),
        0
    );
    assert_eq!(checked(handle.pending_request().await), Some(second));

    checked(handle.cancel(second_digest).await);
    let settled = checked(handle.reconcile(second_digest).await);
    assert_eq!(settled.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(checked(handle.snapshot().await).prefix, first_chunk.bytes);
    assert!(checked(handle.pending_output().await).is_none());
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        fixture.control.signals.cancellations.load(Ordering::SeqCst),
        1
    );
    tasks.shutdown().await;
}

#[tokio::test]
async fn both_drain_paths_retain_unknown_work_and_unacknowledged_output() {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = request("drain-original", checked(handle.snapshot().await));
    let digest = checked(original.digest());
    assert!(handle.step(original).await.is_err());
    fixture.begin_drain();
    for has_result in [false, true] {
        fixture
            .control
            .signals
            .readable
            .store(has_result, Ordering::SeqCst);
        let result = handle.reconcile(digest).await;
        if has_result {
            checked(result);
            assert!(checked(handle.pending_output().await).is_some());
        } else {
            assert_eq!(result, Err(CellGenerationErrorV2::Pending));
            assert!(checked(handle.pending_request().await).is_some());
        }
        assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
        assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
        assert!(
            timeout(
                Duration::from_millis(30),
                crate::runtime::drain_runtime(Arc::clone(fixture.state()))
            )
            .await
            .is_err()
        );
    }
    let chunk = checked(handle.pending_output().await).unwrap_or_else(|| panic!("outbox"));
    let mut changed = chunk.clone();
    changed.bytes.push(0);
    assert!(handle.acknowledge(changed, [22; 32], cost()).await.is_err());
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    checked(handle.acknowledge(chunk, [23; 32], cost()).await);
    assert!(checked(handle.drain().await));
    assert_eq!(
        checked(fixture.state().neuron_generation_drain_blockers()),
        0
    );
    checked(checked(
        timeout(
            Duration::from_secs(1),
            crate::runtime::drain_runtime(Arc::clone(fixture.state())),
        )
        .await,
    ));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    // App Server's independent drain witness is intentionally not fabricated.
    assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
    tasks.shutdown().await;
}

#[tokio::test]
async fn host_fence_at_precontact_or_precommit_preserves_pending_without_publication() {
    for fence_at in [2_u64, 3] {
        let fixture = Fixture::new().await;
        let state = Arc::clone(fixture.state());
        let mut sampled = 0;
        let clock = move || {
            sampled += 1;
            if sampled == fence_at {
                state.mark_fenced();
            }
            20 + sampled
        };
        let (handle, bootstrap) = checked(neuron_generation_channel_v2(
            &fixture.identity,
            fixture.journal(),
            fixture.control.clone(),
            clock,
            /*capacity*/ 2,
        ));
        let (mut tasks, lifetime) = host();
        checked(spawn_neuron_generation_service(
            &mut tasks,
            bootstrap,
            Arc::clone(fixture.state()),
            lifetime.clone(),
        ));
        let original = request("fence-race", fixture.config.initial.clone());
        assert!(handle.step(original.clone()).await.is_err());
        assert!(checked(fixture.state().is_fenced()));
        tasks.shutdown().await;
        let journal = fixture.journal();
        assert_eq!(checked(journal.pending_request()), Some(&original));
        assert_eq!(checked(journal.snapshot()).revision, 0);
        assert!(checked(journal.snapshot()).prefix.is_empty());
        assert_eq!(
            fixture.control.signals.calls.load(Ordering::SeqCst),
            usize::from(fence_at == 3)
        );
    }
}

#[tokio::test]
async fn quarantine_is_a_drain_blocker_and_never_a_retirement_acknowledgement() {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = request("panic-readback", checked(handle.snapshot().await));
    let digest = checked(original.digest());
    assert!(handle.step(original).await.is_err());
    fixture
        .control
        .signals
        .panic_on_read
        .store(/*val*/ true, Ordering::SeqCst);
    assert_eq!(
        handle.reconcile(digest).await,
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    checked(tasks.observe_next().await);
    assert!(!tasks.failures().is_empty());
    fixture.begin_drain();
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    assert!(!checked(fixture.state().drain_snapshot(/*automation_blockers*/ 0)).drained);
    assert!(
        timeout(
            Duration::from_millis(30),
            crate::runtime::drain_runtime(Arc::clone(fixture.state()))
        )
        .await
        .is_err()
    );
    assert!(
        tasks
            .retire_optional_generation(SERVICE, generation(1))
            .await
            .is_err()
    );
    tasks.shutdown().await;
}

#[tokio::test]
async fn ordinary_shutdown_reopens_original_pending_and_exact_committed_outbox() {
    let mut fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 3,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = request("reopen-original", checked(handle.snapshot().await));
    assert!(handle.step(original.clone()).await.is_err());
    tasks.shutdown().await;
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    drop(handle);

    fixture.reopen_state().await;
    fixture
        .control
        .signals
        .readable
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 3,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    assert_eq!(
        checked(handle.pending_request().await),
        Some(original.clone())
    );
    checked(handle.reconcile(checked(original.digest())).await);
    let snapshot = checked(handle.snapshot().await);
    let outbox =
        checked(handle.pending_output().await).unwrap_or_else(|| panic!("recovered outbox"));
    assert_eq!(snapshot.generation, 41);
    assert_eq!(snapshot.prefix, outbox.bytes);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
    drop(handle);

    fixture.reopen_state().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 3,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    assert_eq!(checked(handle.snapshot().await), snapshot);
    assert_eq!(checked(handle.pending_output().await), Some(outbox.clone()));
    checked(handle.acknowledge(outbox, [24; 32], cost()).await);
    assert!(checked(handle.drain().await));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

#[tokio::test]
async fn retirement_waits_for_exact_ack_and_only_then_permits_same_owner_successor() {
    let fixture = Fixture::new().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(tasks.spawn_required("sibling", std::future::pending()));
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = request("retire-original", checked(handle.snapshot().await));
    assert!(handle.step(original.clone()).await.is_err());
    assert!(
        tasks
            .retire_optional_generation(SERVICE, generation(1))
            .await
            .is_err()
    );
    assert_eq!(tasks.active_count(), 2);
    assert!(
        tasks
            .spawn_optional_service_generation(
                SERVICE,
                generation(2),
                Some(generation(1)),
                |_| async { Ok(()) },
                || Ok(()),
                || Ok(()),
            )
            .is_err()
    );

    fixture
        .control
        .signals
        .readable
        .store(/*val*/ true, Ordering::SeqCst);
    checked(handle.reconcile(checked(original.digest())).await);
    assert!(
        tasks
            .retire_optional_generation(SERVICE, generation(1))
            .await
            .is_err()
    );
    let chunk = checked(handle.pending_output().await).unwrap_or_else(|| panic!("retiring output"));
    checked(handle.acknowledge(chunk.clone(), [25; 32], cost()).await);
    checked(
        tasks
            .retire_optional_generation(SERVICE, generation(1))
            .await,
    );
    assert_eq!(tasks.active_count(), 1);
    assert_eq!(
        checked(fixture.state().neuron_generation_drain_blockers()),
        0
    );
    drop(handle);

    let retired = fixture.journal();
    let retired_checkpoint = checked(retired.continuity_checkpoint());
    let retired_snapshot = checked(retired.snapshot()).clone();
    assert_eq!(retired_snapshot.prefix, chunk.bytes);
    drop(retired);

    // This branch has the same full runtime snapshot, config and completed
    // output as the predecessor. Extra owner events still make it a different
    // commit cut; matching only scope, manifest or prefix would admit it.
    for suffix in ["journal", "witness"] {
        checked(std::fs::copy(
            fixture
                .directory
                .path()
                .join(format!("generation-{suffix}")),
            fixture.directory.path().join(format!("branched-{suffix}")),
        ));
    }
    let mut branched = fixture.journal_with("branched", fixture.config.clone());
    assert_eq!(
        checked(branched.continuity_checkpoint()),
        retired_checkpoint
    );
    checked(branched.resume());
    checked(branched.drain());
    assert_eq!(checked(branched.snapshot()), &retired_snapshot);
    assert!(checked(branched.is_drained()));

    let mut changed_scope = fixture.config.clone();
    changed_scope.initial.scope.cell_id = "another-cell".into();
    let mut changed_manifest = fixture.config.clone();
    changed_manifest.manifest.bundle_digest = [26; 32];
    changed_manifest.initial.manifest_digest = checked(changed_manifest.manifest.digest());
    for (name, journal) in [
        (
            "fresh",
            fixture.journal_with("fresh", fixture.config.clone()),
        ),
        ("branched", branched),
        ("scope", fixture.journal_with("scope", changed_scope)),
        (
            "manifest",
            fixture.journal_with("manifest", changed_manifest),
        ),
    ] {
        assert_ne!(checked(journal.continuity_checkpoint()), retired_checkpoint);
        let (_rejected, bootstrap) = checked(neuron_generation_channel_v2(
            &fixture.identity,
            journal,
            fixture.control.clone(),
            fixture.clock(),
            /*capacity*/ 3,
        ));
        let bootstrap =
            checked(bootstrap.with_service_generation(generation(2), Some(generation(1))));
        assert!(
            spawn_neuron_generation_service(
                &mut tasks,
                bootstrap,
                Arc::clone(fixture.state()),
                lifetime.clone(),
            )
            .is_err(),
            "{name} journal must not replace the retired owner"
        );
        // A rejected attachment must retain the acknowledged predecessor and
        // leave its generation slot available for the exact original journal.
        assert_eq!(
            checked(fixture.state().neuron_generation_drain_blockers()),
            0
        );
        assert_eq!(tasks.active_count(), 1);
    }

    let (successor, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 3,
    ));
    let bootstrap = checked(bootstrap.with_service_generation(generation(2), Some(generation(1))));
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    checked(successor.resume().await);
    assert_eq!(checked(successor.snapshot().await).prefix, chunk.bytes);
    assert!(
        tasks
            .retire_optional_generation(SERVICE, generation(1))
            .await
            .is_err()
    );
    assert_eq!(tasks.active_count(), 2);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}
