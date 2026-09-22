use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_types::Generation;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::RuntimeTasks;
use crate::AgentdError;

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("nonzero generation")
}

fn start(host: &mut RuntimeTasks, epoch: u64, previous: Option<u64>) -> Result<(), AgentdError> {
    host.spawn_optional_service_generation(
        "optional.timer",
        generation(epoch),
        previous.map(generation),
        |stop| async move {
            stop.cancelled().await;
            Ok(())
        },
        || Ok(()),
        || Ok(()),
    )
}

#[tokio::test]
async fn replacements_reuse_one_slot_even_at_full_identity_capacity() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).unwrap();
    for index in 0..127 {
        let child = stop.child_token();
        host.spawn_required(&format!("core.{index}"), async move {
            child.cancelled().await;
            Ok(())
        })
        .unwrap();
    }
    for epoch in 1..=1_024 {
        start(&mut host, epoch, (epoch > 1).then_some(epoch - 1)).unwrap();
        assert_eq!(host.active_count(), 128);
        assert_eq!(host.remaining_admission_slots(), 0);
        host.retire_optional_generation("optional.timer", generation(epoch))
            .await
            .unwrap();
        assert_eq!(host.active_count(), 127);
        assert_eq!(host.admitted_names.len(), 128);
        assert_eq!(host.retired_names.len(), 1);
        assert_eq!(host.service_generations.len(), 1);
        assert!(!stop.is_cancelled());
    }
    assert!(host.spawn_required("extra", async { Ok(()) }).is_err());
    host.shutdown().await;
}

#[tokio::test]
async fn stale_and_unversioned_requests_cannot_stop_or_resurrect_a_successor() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).unwrap();
    start(&mut host, 1, None).unwrap();
    assert!(start(&mut host, 2, Some(1)).is_err());
    host.retire_optional_generation("optional.timer", generation(1))
        .await
        .unwrap();
    assert!(start(&mut host, 1, Some(1)).is_err());
    start(&mut host, 2, Some(1)).unwrap();
    assert!(
        host.retire_optional_generation("optional.timer", generation(1))
            .await
            .is_err()
    );
    assert!(host.retire_optional("optional.timer").await.is_err());
    assert!(
        host.spawn_optional_service("optional.timer", |_| async { Ok(()) }, || Ok(()), || Ok(()),)
            .is_err()
    );
    assert!(start(&mut host, 3, Some(1)).is_err());
    assert_eq!(host.active_count(), 1);
    assert!(!stop.is_cancelled());
    host.retire_optional_generation("optional.timer", generation(2))
        .await
        .unwrap();
    host.shutdown().await;
}

#[tokio::test]
async fn rejected_registration_never_invokes_factory_or_advances_fence() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop, Duration::from_secs(2)).unwrap();
    start(&mut host, 1, None).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    assert!(
        host.spawn_optional_service_generation(
            "optional.timer",
            generation(2),
            Some(generation(1)),
            move |_| {
                observed.fetch_add(1, Ordering::SeqCst);
                async { Ok(()) }
            },
            || Ok(()),
            || Ok(()),
        )
        .is_err()
    );
    tokio::task::yield_now().await;
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(host.service_generations["optional.timer"], generation(1));
    host.retire_optional_generation("optional.timer", generation(1))
        .await
        .unwrap();
    host.shutdown().await;
    assert!(start(&mut host, 2, Some(1)).is_err());
    assert_eq!(host.service_generations["optional.timer"], generation(1));
    assert!(host.retired_names.contains("optional.timer"));
    assert_eq!(host.admitted_names.len(), 1);
}

#[tokio::test]
async fn a_drain_timeout_does_not_free_the_slot_or_acknowledge_retirement() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_millis(10)).unwrap();
    let (release, released) = oneshot::channel::<()>();
    host.spawn_optional_service_generation(
        "optional.timer",
        generation(1),
        None,
        |stop| async move {
            stop.cancelled().await;
            released.await.unwrap();
            Ok(())
        },
        || Ok(()),
        || Ok(()),
    )
    .unwrap();
    assert!(
        host.retire_optional_generation("optional.timer", generation(1))
            .await
            .is_err()
    );
    assert!(start(&mut host, 2, Some(1)).is_err());
    assert!(!host.retired_names.contains("optional.timer"));
    assert_eq!(host.active_count(), 1);
    assert!(!stop.is_cancelled());
    release.send(()).unwrap();
    host.retire_optional_generation("optional.timer", generation(1))
        .await
        .unwrap();
    start(&mut host, 2, Some(1)).unwrap();
    host.shutdown().await;
}

#[tokio::test]
async fn quarantined_failure_is_not_an_acknowledged_retirement() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).unwrap();
    host.spawn_optional_service_generation(
        "optional.timer",
        generation(1),
        None,
        |_| async { Err(AgentdError::Protocol("injected owner failure".to_string())) },
        || Ok(()),
        || Ok(()),
    )
    .unwrap();
    host.observe_next().await.unwrap();
    assert_eq!(host.active_count(), 0);
    assert_eq!(host.failures().len(), 1);
    assert!(!stop.is_cancelled());
    assert!(start(&mut host, 2, Some(1)).is_err());
    assert_eq!(host.service_generations["optional.timer"], generation(1));
    host.shutdown().await;
}

#[tokio::test]
async fn failed_retirement_callback_fences_host_without_releasing_identity() {
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).unwrap();
    host.spawn_optional_service_generation(
        "optional.timer",
        generation(1),
        None,
        |stop| async move {
            stop.cancelled().await;
            Ok(())
        },
        || Ok(()),
        || {
            Err(AgentdError::Protocol(
                "unresolved owner effects".to_string(),
            ))
        },
    )
    .unwrap();
    assert!(
        host.retire_optional_generation("optional.timer", generation(1))
            .await
            .is_err()
    );
    assert!(stop.is_cancelled());
    assert!(!host.retired_names.contains("optional.timer"));
    assert!(start(&mut host, 2, Some(1)).is_err());
    assert!(host.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn retired_legacy_name_cannot_bypass_its_single_use_contract() {
    let mut host = RuntimeTasks::new(CancellationToken::new(), Duration::from_secs(2)).unwrap();
    host.spawn_optional_service(
        "optional.timer",
        |stop| async move {
            stop.cancelled().await;
            Ok(())
        },
        || Ok(()),
        || Ok(()),
    )
    .unwrap();
    host.retire_optional("optional.timer").await.unwrap();
    assert!(start(&mut host, 1, None).is_err());
    assert!(host.service_generations.is_empty());
    assert!(host.retired_names.contains("optional.timer"));
    host.shutdown().await;
}
