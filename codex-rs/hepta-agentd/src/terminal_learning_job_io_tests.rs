//! Delayed original-store I/O must yield without releasing the operation lane.

use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::oneshot;

#[derive(Clone, Copy, Eq, PartialEq)]
enum IoPoint {
    Read,
    Claim,
}

struct DelayedIo {
    point: IoPoint,
    entered: oneshot::Sender<()>,
    release: mpsc::Receiver<()>,
    finished: oneshot::Sender<()>,
}

struct DelayedCas {
    original: Arc<FileCas>,
    next: Mutex<Option<DelayedIo>>,
    reads: AtomicUsize,
}

impl DelayedCas {
    fn arm(
        &self,
        point: IoPoint,
    ) -> (
        oneshot::Receiver<()>,
        mpsc::SyncSender<()>,
        oneshot::Receiver<()>,
    ) {
        let (entered, waiting) = oneshot::channel();
        let (release, resumed) = mpsc::sync_channel(/*bound*/ 1);
        let (finished, returned) = oneshot::channel();
        *self.next.lock().unwrap() = Some(DelayedIo {
            point,
            entered,
            release: resumed,
            finished,
        });
        (waiting, release, returned)
    }

    fn delay(&self, point: IoPoint) -> Result<Option<oneshot::Sender<()>>, AuthorityTrustError> {
        let delayed = {
            let mut next = self.next.lock().unwrap();
            if next.as_ref().is_some_and(|next| next.point == point) {
                next.take()
            } else {
                None
            }
        };
        let Some(delayed) = delayed else {
            return Ok(None);
        };
        let _ = delayed.entered.send(());
        delayed
            .release
            .recv_timeout(Duration::from_secs(5))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(Some(delayed.finished))
    }
}

impl AuthorityFrontierStore<TerminalLearningJobRecordV1> for DelayedCas {
    fn load(&self, owner: &str) -> Result<TerminalLearningJobRecordV1, AuthorityTrustError> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        let finished = self.delay(IoPoint::Read)?;
        let result = self.original.load(owner);
        if let Some(finished) = finished {
            let _ = finished.send(());
        }
        result
    }

    fn compare_and_set(
        &self,
        owner: &str,
        expected: &TerminalLearningJobRecordV1,
        next: &TerminalLearningJobRecordV1,
    ) -> Result<(), AuthorityTrustError> {
        let finished = if serde_json::to_value(next).unwrap()["state"]["stage"] == "Computing" {
            self.delay(IoPoint::Claim)?
        } else {
            None
        };
        let result = self.original.compare_and_set(owner, expected, next);
        if let Some(finished) = finished {
            let _ = finished.send(());
        }
        result
    }
}

fn delayed_owner(
    fixtures: &FixtureOwners,
    original: Arc<FileCas>,
) -> (Arc<AgentdTerminalLearningOwnerV1>, Arc<DelayedCas>) {
    let store = Arc::new(DelayedCas {
        original,
        next: Mutex::new(None),
        reads: AtomicUsize::new(0),
    });
    let job = TerminalLearningJobOwnerV1::from_test(
        store.clone(),
        &fixtures.request,
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
    )
    .unwrap();
    (Arc::new(native(fixtures, job)), store)
}

async fn observe_yield(entered: oneshot::Receiver<()>) {
    let started = Instant::now();
    tokio::time::timeout(Duration::from_secs(2), entered)
        .await
        .unwrap()
        .unwrap();
    // A synchronous wait on this single-thread executor would last until the
    // store's five-second watchdog, preventing this observer from resuming.
    assert!(started.elapsed() < Duration::from_secs(2));
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_current_read_retains_lane_until_io_returns_then_uses_same_job() {
    let fixtures = fixtures().await;
    let directory = tempfile::tempdir().unwrap();
    let original = FileCas::create(&directory.path().join("original-job"), &fixtures);
    let (owner, store) = delayed_owner(&fixtures, original.clone());
    let (entered, release, finished) = store.arm(IoPoint::Read);
    let pending_owner = Arc::clone(&owner);
    let request = fixtures.request.clone();
    let pending = tokio::spawn(async move {
        pending_owner.train(request, /*now*/ 50).await
    });
    observe_yield(entered).await;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    let reads = store.reads.load(Ordering::SeqCst);
    assert_eq!(
        owner.readback(fixtures.request.clone(), /*now*/ 50).await,
        Err(TerminalLearningErrorV1::CommitUncertain)
    );
    assert_eq!(store.reads.load(Ordering::SeqCst), reads);
    assert_eq!(original.commits.load(Ordering::SeqCst), 0);
    release.send(()).unwrap();
    finished.await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        while store.reads.load(Ordering::SeqCst) == reads {
            assert_eq!(
                owner.readback(fixtures.request.clone(), /*now*/ 50).await,
                Err(TerminalLearningErrorV1::CommitUncertain)
            );
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let receipt = owner
        .train(fixtures.request.clone(), /*now*/ 50)
        .await
        .unwrap();
    assert_eq!(receipt.operation_id, fixtures.request.operation_id);
    assert_eq!(
        owner
            .readback(fixtures.request.clone(), /*now*/ 51)
            .await
            .unwrap(),
        receipt
    );
    assert_eq!(original.commits.load(Ordering::SeqCst), 2);
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_claim_yields_and_keeps_original_unfinished_operation() {
    let fixtures = fixtures().await;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("original-job");
    let original = FileCas::create(&path, &fixtures);
    let (owner, store) = delayed_owner(&fixtures, original.clone());
    let (entered, release, finished) = store.arm(IoPoint::Claim);
    let pending_owner = Arc::clone(&owner);
    let request = fixtures.request.clone();
    let pending = tokio::spawn(async move {
        pending_owner.train(request, /*now*/ 50).await
    });
    observe_yield(entered).await;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    let reads = store.reads.load(Ordering::SeqCst);
    assert_eq!(
        owner.train(fixtures.request.clone(), /*now*/ 50).await,
        Err(TerminalLearningErrorV1::CommitUncertain)
    );
    assert_eq!(store.reads.load(Ordering::SeqCst), reads);
    release.send(()).unwrap();
    finished.await.unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let record: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(record["state"]["stage"], "Computing");
    assert_eq!(original.commits.load(Ordering::SeqCst), 1);
    assert_eq!(
        owner.readback(fixtures.request.clone(), /*now*/ 51).await,
        Err(TerminalLearningErrorV1::CommitUncertain)
    );
    assert_eq!(
        owner.train(fixtures.request.clone(), /*now*/ 51).await,
        Err(TerminalLearningErrorV1::CommitUncertain)
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}

#[test]
fn queued_native_deadline_reconciles_without_claim_or_refit() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(/*val*/ 1)
        .build()
        .unwrap();
    runtime.block_on(async {
        let mut fixtures = fixtures().await;
        fixtures.request.budget.maximum_wall_milliseconds = 1_000;
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("original-job");
        let original = FileCas::create(&path, &fixtures);
        let (owner, store) = delayed_owner(&fixtures, original.clone());
        let bytes = std::fs::read(&path).unwrap();
        let (entered, release, finished) = store.arm(IoPoint::Read);
        let pending_owner = Arc::clone(&owner);
        let request = fixtures.request.clone();
        let pending = tokio::spawn(async move {
            pending_owner.train(request, /*now*/ 50).await
        });
        observe_yield(entered).await;
        // Queue a bounded unrelated blocking task immediately behind CURRENT
        // readback. The native fit can then be admitted but cannot start yet.
        let (started, waiting) = oneshot::channel();
        let (resume, resumed) = mpsc::sync_channel(/*bound*/ 1);
        let blocker = tokio::task::spawn_blocking(move || {
            let _ = started.send(());
            resumed.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        release.send(()).unwrap();
        finished.await.unwrap();
        observe_yield(waiting).await;
        assert_eq!(
            pending.await.unwrap(),
            Err(TerminalLearningErrorV1::CommitUncertain)
        );
        resume.send(()).unwrap();
        blocker.await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                match owner.readback(fixtures.request.clone(), /*now*/ 51).await {
                    Err(TerminalLearningErrorV1::CommitUncertain) => {
                        tokio::task::yield_now().await;
                    }
                    result => {
                        assert_eq!(result, Err(TerminalLearningErrorV1::DeadlineExceeded));
                        break;
                    }
                }
            }
        })
        .await
        .unwrap();
        assert_eq!(
            owner.train(fixtures.request.clone(), /*now*/ 51).await,
            Err(TerminalLearningErrorV1::DeadlineExceeded)
        );
        assert_eq!(original.commits.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    });
}
