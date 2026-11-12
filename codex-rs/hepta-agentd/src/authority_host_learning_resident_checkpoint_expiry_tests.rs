//! A real protected Root CAS crosses a first-issued fixture Observer window.
//! Only the acknowledgement is paused. The OS/HostAuthorityClock, grants and
//! persisted checkpoint remain original. This metadata mechanism is not A/B/C.

use std::io;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::super::super::authentication;
use super::super::super::store::ResidentCheckpointV3;
use super::metadata::ResidentMetadata;
use super::support::ResidentRootFixture;
use crate::LearningIterationRuntimeErrorV1 as Error;

struct Pause {
    binding: Digest32,
    owner: Weak<ResidentCheckpointV3>,
    expected: LearningIterationSnapshotV1,
    expires_ms: u64,
    record_path: PathBuf,
    observed: Arc<Mutex<Option<Vec<u8>>>>,
}

// Each entry names one actual Root profile. Other parallel fixtures cannot
// consume it, and taking the entry before waiting makes this hook one-shot.
static PAUSES: Mutex<Vec<Pause>> = Mutex::new(Vec::new());

struct ArmedPause {
    binding: Digest32,
    observed: Arc<Mutex<Option<Vec<u8>>>>,
}

impl Drop for ArmedPause {
    fn drop(&mut self) {
        if let Ok(mut pauses) = PAUSES.lock() {
            pauses.retain(|pause| !Arc::ptr_eq(&pause.observed, &self.observed));
        }
    }
}

fn wall_ms() -> io::Result<u64> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_millis(),
    )
    .map_err(io::Error::other)
}

pub(in super::super) fn after_checkpoint_for_fixture(
    binding: Digest32,
    owner: &ResidentCheckpointV3,
) -> io::Result<()> {
    let pause = {
        let mut pauses = PAUSES.lock().map_err(|_| io::Error::other("fixture pause poisoned"))?;
        pauses
            .iter()
            .position(|pause| {
                pause.binding == binding
                    && pause.owner.upgrade().is_some_and(|actual| {
                        std::ptr::eq(actual.as_ref(), owner)
                    })
            })
            .map(|index| pauses.remove(index))
    };
    let Some(pause) = pause else {
        return Ok(());
    };
    let saved = owner.read()?;
    if saved.snapshot.as_ref() != Some(&pause.expected) || saved.dispatch_pending {
        return Err(io::Error::other("fixture must pause after the exact durable CAS"));
    }
    let bytes = std::fs::read(&pause.record_path)?;
    if wall_ms()? >= pause.expires_ms {
        return Err(io::Error::other("fixture Observer expired before the post-CAS pause"));
    }
    let started = Instant::now();
    while wall_ms()? < pause.expires_ms {
        if started.elapsed() >= Duration::from_millis(1_500) {
            return Err(io::Error::other("bounded post-CAS fixture pause elapsed"));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    if std::fs::read(&pause.record_path)? != bytes {
        return Err(io::Error::other("checkpoint changed during its post-CAS pause"));
    }
    *pause.observed.lock().map_err(|_| io::Error::other("fixture bytes poisoned"))? = Some(bytes);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_checkpoint_expiry_stops_next_stage_and_preserves_committed_bytes()
-> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let mut fixture = ResidentRootFixture::new(
        metadata.initial.clone(),
        metadata.scope.clone(),
        &metadata.verifier,
    )?;
    let original = Arc::clone(
        &fixture.registration.as_ref().expect("original Root registration").owner,
    );
    let cancellation = CancellationToken::new();
    let continuation = original
        .admit(&cancellation)
        .await?
        .ok_or_else(|| anyhow::anyhow!("actual vacant Root admission"))?;
    let gate = Arc::clone(&continuation.gate);
    gate.begin(&metadata.initial, LearningIterationStageV1::Experience).await?;

    // Leave almost a full second for the real pre-CAS reads. The one-shot
    // post-CAS pause then crosses the next boundary using the actual OS time.
    let at = wall_ms()?;
    let aligned = (at / 1_000 + 1) * 1_000 + 50;
    tokio::time::sleep(Duration::from_millis(aligned - at)).await;
    let expires_at = wall_ms()? / 1_000 + 1;
    let (metadata_result, signatures) =
        metadata.completed_metadata_with_observer_expiry(expires_at)?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(metadata.initial.clone())?;
    coordinator.record(
        metadata_result.receipts[0].clone(),
        metadata_result.receipts[0].observed_unix_seconds,
    )?;
    let next = coordinator.snapshot().clone();
    let signatures = &signatures[..1];
    let (before, before_ms) = original.read(&cancellation).await?;
    assert_eq!(before.snapshot.as_ref(), Some(&metadata.initial));
    assert!(before.dispatch_pending);
    assert!(before_ms / 1_000 < expires_at);
    authentication::verify_original_evidence(
        &fixture.profile,
        &metadata.verifier,
        &next,
        signatures,
        None,
        before_ms / 1_000,
    )?;
    // Pure positive control at the actual pre-CAS clock. This does not claim
    // that a checkpoint happened, and rejects an always-uncertain verifier.
    authentication::verify_checkpoint_evidence(
        &fixture.profile,
        &metadata.verifier,
        &next,
        signatures,
        None,
        before_ms,
        before_ms,
    )?;
    let record_path = fixture.config.state_dir.join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(fixture.profile.owner_id().as_bytes())
    ));
    let observed = Arc::new(Mutex::new(None));
    let armed = ArmedPause { binding: fixture.profile.binding(), observed: Arc::clone(&observed) };
    PAUSES.lock().expect("fixture pause table").push(Pause {
        binding: armed.binding,
        owner: Arc::downgrade(&original.checkpoint),
        expected: next.clone(),
        expires_ms: expires_at * 1_000,
        record_path: record_path.clone(),
        observed,
    });

    let next_dispatches = AtomicUsize::new(0);
    let result = async {
        // Own the same real continuation across CAS and its production pure
        // verifier. Every error drops it before any next-stage dispatch.
        let continuation = continuation;
        let committed_at = continuation.gate.checkpoint(&metadata.initial, next.clone()).await?;
        assert!(committed_at >= expires_at * 1_000);
        authentication::verify_checkpoint_evidence(
            &fixture.profile,
            &metadata.verifier,
            &next,
            signatures,
            None,
            before_ms,
            committed_at,
        )?;
        next_dispatches.fetch_add(1, Ordering::SeqCst);
        continuation.gate.begin(&next, LearningIterationStageV1::Dataset).await?;
        Ok::<_, Error>(())
    }.await;
    assert!(matches!(result, Err(Error::CommitUncertain)));
    assert_eq!(next_dispatches.load(Ordering::SeqCst), 0);
    assert!(gate.training_cancellation().load(Ordering::Acquire));
    assert!(gate.begin(&next, LearningIterationStageV1::Dataset).await.is_err());
    let committed_bytes = armed.observed.lock().expect("post-CAS bytes")
        .clone().expect("one actual profile-bound post-CAS pause");
    assert_eq!(std::fs::read(&record_path)?, committed_bytes);
    let (saved, after_ms) = original.read(&cancellation).await?;
    assert_eq!(saved.snapshot.as_ref(), Some(&next));
    assert!(!saved.dispatch_pending);
    assert!(original.admit(&cancellation).await?.is_none());
    assert!(authentication::verify_original_evidence(
        &fixture.profile, &metadata.verifier, &next, signatures, None, after_ms / 1_000,
    ).is_err());
    drop(gate);
    drop(original);

    // Raw durable state remains observable under the separately provisioned
    // readonly grant. Expired role evidence never becomes an outward CURRENT.
    fixture.recover()?;
    let cold = &fixture.registration.as_ref().expect("readonly Root registration").owner;
    assert!(cold.authority.readonly());
    let saved = cold.read(&cancellation).await?.0;
    assert_eq!(saved.snapshot.as_ref(), Some(&next));
    assert!(!saved.dispatch_pending);
    assert!(cold.admit(&cancellation).await.is_err());
    assert_eq!(std::fs::read(&record_path)?, committed_bytes);
    Ok(())
}
