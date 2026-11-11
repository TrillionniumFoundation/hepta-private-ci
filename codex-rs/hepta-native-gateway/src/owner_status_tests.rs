use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

struct SyntheticOwner(OwnerLeaseObservation);
fn inspect(owner: &SyntheticOwner) -> OwnerObservationFuture<'_> {
    Box::pin(async move { Ok(owner.0) })
}

#[tokio::test]
async fn weak_provider_neither_creates_nor_retains_an_owner() {
    let provider = OwnerStatusProvider::default();
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::NotAttached
    );
    let owner = Arc::new(SyntheticOwner(OwnerLeaseObservation {
        generation: Some(7),
        disposition: OwnerLeaseDisposition::Active,
    }));
    let provider = OwnerStatusProvider::from_weak(Arc::downgrade(&owner), inspect);
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::Observed {
            generation: Some(7),
            disposition: OwnerLeaseDisposition::Active,
        }
    );
    assert_eq!(Arc::strong_count(&owner), 1);
    drop(owner);
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::NotAttached
    );
}

#[tokio::test]
async fn unsigned_max_is_a_lossless_wire_value_not_a_claim_sqlite_admits_it() -> anyhow::Result<()>
{
    let owner = Arc::new(SyntheticOwner(OwnerLeaseObservation {
        generation: Some(u64::MAX),
        disposition: OwnerLeaseDisposition::Released,
    }));
    let provider = OwnerStatusProvider::from_weak(Arc::downgrade(&owner), inspect);
    let bytes = provider.json().await?;
    assert!(bytes.len() < 1024);
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes)?,
        serde_json::json!({
            "schema":"hepta.owner-lease-observation.v1",
            "observation":{"status":"observed","generation":u64::MAX,"disposition":"released"}
        })
    );
    Ok(())
}

#[tokio::test]
async fn inconsistent_missing_generation_is_sanitized() {
    for observation in [
        OwnerLeaseObservation {
            generation: Some(9),
            disposition: OwnerLeaseDisposition::Missing,
        },
        OwnerLeaseObservation {
            generation: None,
            disposition: OwnerLeaseDisposition::Active,
        },
    ] {
        let owner = Arc::new(SyntheticOwner(observation));
        let provider = OwnerStatusProvider::from_weak(Arc::downgrade(&owner), inspect);
        assert_eq!(
            provider.observe(OBSERVATION_TIMEOUT).await,
            Observation::Unavailable {
                reason: OwnerReadFailure::InvalidObservation,
            }
        );
    }
}

struct SlowSyntheticOwner {
    reads: Arc<AtomicUsize>,
    release: Arc<Notify>,
}
fn slow(owner: &SlowSyntheticOwner) -> OwnerObservationFuture<'_> {
    Box::pin(async move {
        owner.reads.fetch_add(1, Ordering::SeqCst);
        owner.release.notified().await;
        Ok(OwnerLeaseObservation {
            generation: None,
            disposition: OwnerLeaseDisposition::Missing,
        })
    })
}

#[tokio::test]
async fn timeout_does_not_accumulate_detached_reads_and_releases_the_weak_upgrade() {
    let reads = Arc::new(AtomicUsize::new(0));
    let release = Arc::new(Notify::new());
    let owner = Arc::new(SlowSyntheticOwner {
        reads: Arc::clone(&reads),
        release: Arc::clone(&release),
    });
    let weak = Arc::downgrade(&owner);
    let provider = OwnerStatusProvider::from_weak(weak.clone(), slow);
    assert_eq!(
        provider.observe(Duration::from_millis(20)).await,
        Observation::Unavailable {
            reason: OwnerReadFailure::TimedOut,
        }
    );
    for _ in 0..8 {
        assert_eq!(
            provider.observe(OBSERVATION_TIMEOUT).await,
            Observation::Unavailable {
                reason: OwnerReadFailure::Busy,
            }
        );
    }
    assert_eq!(reads.load(Ordering::SeqCst), 1);
    drop(owner);
    release.notify_one();
    tokio::time::timeout(Duration::from_secs(2), async {
        while weak.strong_count() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("read must finish");
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::NotAttached
    );
}

#[tokio::test]
async fn cancelling_a_request_does_not_release_the_single_flight_while_scan_is_alive() {
    let reads = Arc::new(AtomicUsize::new(0));
    let release = Arc::new(Notify::new());
    let owner = Arc::new(SlowSyntheticOwner {
        reads: Arc::clone(&reads),
        release: Arc::clone(&release),
    });
    let weak = Arc::downgrade(&owner);
    let provider = OwnerStatusProvider::from_weak(weak.clone(), slow);
    let task_provider = provider.clone();
    let request = tokio::spawn(async move { task_provider.observe(OBSERVATION_TIMEOUT).await });
    tokio::time::timeout(Duration::from_secs(2), async {
        while reads.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("scan must start");
    request.abort();
    let _ = request.await;
    drop(owner);
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::Unavailable {
            reason: OwnerReadFailure::Busy
        }
    );
    assert_eq!(
        weak.strong_count(),
        1,
        "in-flight read still owns its temporary upgrade"
    );
    release.notify_one();
    tokio::time::timeout(Duration::from_secs(2), async {
        while weak.strong_count() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("scan must release upgrade");
    assert_eq!(
        provider.observe(OBSERVATION_TIMEOUT).await,
        Observation::NotAttached
    );
}
