//! Real native fit with test-key Memory/Ledger; file CAS fault injection is not
//! Root qualification. The explicitly ignored host test uses the real backend.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use super::*;
use crate::TerminalLearningJobOwnerV1;
use crate::TerminalLearningJobRecordV1;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;

const OWNER: &str = "terminal-test-owner";

struct FileCas {
    file: Mutex<File>,
    failure: AtomicU8,
    commits: AtomicUsize,
    load_delay_millis: AtomicUsize,
}
impl FileCas {
    fn create(path: &Path, fixtures: &FixtureOwners) -> Arc<Self> {
        let record = TerminalLearningJobRecordV1::vacant(
            &fixtures.request,
            &fixtures.daemon.identity.agent_id,
            &id("operator.native.owner"),
        )
        .unwrap();
        let mut file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(path)
            .unwrap();
        file.write_all(&serde_json::to_vec(&record).unwrap())
            .unwrap();
        file.sync_all().unwrap();
        File::open(path.parent().unwrap())
            .unwrap()
            .sync_all()
            .unwrap();
        Self::open(path)
    }
    fn open(path: &Path) -> Arc<Self> {
        Arc::new(Self {
            file: Mutex::new(
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(path)
                    .unwrap(),
            ),
            failure: AtomicU8::new(0),
            commits: AtomicUsize::new(0),
            load_delay_millis: AtomicUsize::new(0),
        })
    }
    fn locked<T>(
        &self,
        owner: &str,
        action: impl FnOnce(&mut File) -> Result<T, AuthorityTrustError>,
    ) -> Result<T, AuthorityTrustError> {
        if owner != OWNER {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut file = self
            .file
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        file.try_lock().map_err(|_| AuthorityTrustError::Conflict)?;
        let result = action(&mut file);
        file.unlock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        result
    }
}
fn read(file: &mut File) -> Result<TerminalLearningJobRecordV1, AuthorityTrustError> {
    file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
    let mut bytes = Vec::new();
    file.take(64 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() > 64 * 1024 {
        return Err(AuthorityTrustError::Invalid);
    }
    serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)
}
fn unavailable(_: std::io::Error) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}
impl AuthorityFrontierStore<TerminalLearningJobRecordV1> for FileCas {
    fn load(&self, owner: &str) -> Result<TerminalLearningJobRecordV1, AuthorityTrustError> {
        let delay = self.load_delay_millis.swap(0, Ordering::SeqCst);
        if delay > 0 {
            std::thread::sleep(std::time::Duration::from_millis(delay as u64));
        }
        self.locked(owner, read)
    }
    fn compare_and_set(
        &self,
        owner: &str,
        expected: &TerminalLearningJobRecordV1,
        next: &TerminalLearningJobRecordV1,
    ) -> Result<(), AuthorityTrustError> {
        self.locked(owner, |file| {
            if read(file)? != *expected {
                return Err(AuthorityTrustError::Conflict);
            }
            let value = serde_json::to_value(next).map_err(|_| AuthorityTrustError::Invalid)?;
            let fault = self.failure.load(Ordering::SeqCst);
            let inject = (value["state"]["stage"] == "Committed" && fault <= 2)
                || (value["state"]["stage"] == "Computing" && fault >= 3);
            let failure = if inject {
                self.failure.swap(0, Ordering::SeqCst)
            } else {
                0
            };
            if matches!(failure, 1 | 3) {
                return Err(AuthorityTrustError::Unavailable);
            }
            let bytes = serde_json::to_vec(next).map_err(|_| AuthorityTrustError::Invalid)?;
            file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
            file.set_len(0).map_err(unavailable)?;
            file.write_all(&bytes).map_err(unavailable)?;
            file.sync_all().map_err(unavailable)?;
            self.commits.fetch_add(1, Ordering::SeqCst);
            if matches!(failure, 2 | 4) {
                return Err(AuthorityTrustError::Unavailable);
            }
            Ok(())
        })
    }
}
fn job(fixtures: &FixtureOwners, store: Arc<FileCas>) -> TerminalLearningJobOwnerV1 {
    TerminalLearningJobOwnerV1::from_test(
        store,
        &fixtures.request,
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
    )
    .unwrap()
}
fn native(
    fixtures: &FixtureOwners,
    job: TerminalLearningJobOwnerV1,
) -> AgentdTerminalLearningOwnerV1 {
    AgentdTerminalLearningOwnerV1::from_registered_job(
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
        Arc::clone(&fixtures.ledger),
        Arc::clone(&fixtures.replay),
        job,
    )
    .unwrap()
}
async fn fixtures() -> FixtureOwners {
    let mut fixtures = FixtureOwners::new().await;
    fixtures.request.budget.maximum_artifact_bytes = 16 * 1024;
    fixtures
}

#[tokio::test]
async fn durable_native_result_reopens_without_refit_and_rechecks_current_permission() {
    let fixtures = fixtures().await;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("original-job");
    let store = FileCas::create(&path, &fixtures);
    let owner = native(&fixtures, job(&fixtures, store.clone()));
    let receipt = owner
        .train(fixtures.request.clone(), /*now*/ 50)
        .await
        .unwrap();
    assert_eq!(store.commits.load(Ordering::SeqCst), 2);
    let bytes = std::fs::read(&path).unwrap();
    drop(owner);
    drop(store);
    // A changed head invalidates the original freeze signature for a second
    // fit, while the original dataset remains currently eligible for readback.
    collect(
        &mut fixtures.ledger.lock().unwrap(),
        "later",
        "read",
        FixedQ32::ONE.raw(),
        fixtures.request.expected_source_support_digest,
    );
    let reopened_store = FileCas::open(&path);
    let recovered = native(&fixtures, job(&fixtures, reopened_store.clone()));
    assert_eq!(
        recovered
            .readback(fixtures.request.clone(), /*now*/ 51)
            .await
            .unwrap(),
        receipt
    );
    assert_eq!(
        recovered
            .train(fixtures.request.clone(), /*now*/ 51)
            .await
            .unwrap(),
        receipt
    );
    assert_eq!(reopened_store.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    let mut foreign = fixtures.request.clone();
    foreign.dataset_evidence.signature[0] ^= 1;
    assert_eq!(
        recovered.train(foreign, /*now*/ 51).await.unwrap_err(),
        TerminalLearningErrorV1::Conflict
    );
    // The serialized producer fields do not renew its original expiry.
    assert!(matches!(
        recovered
            .readback(fixtures.request.clone(), /*now*/ 101)
            .await,
        Err(TerminalLearningErrorV1::Owner(_))
    ));
    fixtures
        .source
        .revoke_shared_experience(&fixtures.access, &fixtures.grant)
        .await
        .unwrap();
    assert!(matches!(
        recovered
            .readback(fixtures.request.clone(), /*now*/ 51)
            .await,
        Err(TerminalLearningErrorV1::Owner(_))
    ));
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}

#[tokio::test]
async fn durable_failed_commit_is_unknown_but_lost_ack_recovers_original_cost() {
    for failure in [1, 2] {
        let fixtures = fixtures().await;
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("original-job");
        let store = FileCas::create(&path, &fixtures);
        store.failure.store(failure, Ordering::SeqCst);
        let owner = native(&fixtures, job(&fixtures, store.clone()));
        assert_eq!(
            owner
                .train(fixtures.request.clone(), /*now*/ 50)
                .await
                .unwrap_err(),
            TerminalLearningErrorV1::CommitUncertain
        );
        drop(owner);
        drop(store);
        let bytes = std::fs::read(&path).unwrap();
        let reopened_store = FileCas::open(&path);
        let recovered = native(&fixtures, job(&fixtures, reopened_store.clone()));
        let result = recovered.train(fixtures.request.clone(), /*now*/ 51).await;
        if failure == 1 {
            assert_eq!(
                result.unwrap_err(),
                TerminalLearningErrorV1::CommitUncertain
            );
        } else {
            let receipt = result.unwrap();
            let persisted: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(
                receipt.elapsed_microseconds,
                persisted["state"]["result"]["elapsed_microseconds"]
                    .as_u64()
                    .unwrap()
            );
            assert_eq!(
                receipt,
                recovered
                    .readback(fixtures.request.clone(), /*now*/ 51)
                    .await
                    .unwrap()
            );
        }
        assert_eq!(reopened_store.commits.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        std::fs::write(&path, b"{truncated").unwrap();
        assert_eq!(
            recovered
                .train(fixtures.request.clone(), /*now*/ 51)
                .await
                .unwrap_err(),
            TerminalLearningErrorV1::CommitUncertain
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"{truncated");
    }
}

#[tokio::test]
async fn durable_unfinished_fence_and_changed_binding_never_restart_native_work() {
    let fixtures = fixtures().await;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("original-job");
    let store = FileCas::create(&path, &fixtures);
    job(&fixtures, store.clone()).claim().unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let recovered = native(&fixtures, job(&fixtures, FileCas::open(&path)));
    assert_eq!(
        recovered
            .train(fixtures.request.clone(), /*now*/ 50)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
    assert_eq!(
        recovered
            .readback(fixtures.request.clone(), /*now*/ 50)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
    let mut oversized = fixtures.request.clone();
    oversized.budget.maximum_artifact_bytes = 16 * 1024 + 1;
    assert_eq!(
        TerminalLearningJobRecordV1::vacant(
            &oversized,
            &fixtures.daemon.identity.agent_id,
            &id("operator.native.owner")
        )
        .unwrap_err(),
        TerminalLearningErrorV1::Capacity
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}

#[path = "terminal_learning_job_process_tests.rs"]
mod process_tests;

#[tokio::test]
async fn durable_claim_lost_ack_and_competing_reopen_owners_cannot_start_twice() {
    for lost_ack in [false, true] {
        let fixtures = fixtures().await;
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("original-job");
        let store = FileCas::create(&path, &fixtures);
        if lost_ack {
            store.failure.store(4, Ordering::SeqCst);
            assert_eq!(
                job(&fixtures, store.clone()).claim(),
                Err(TerminalLearningErrorV1::CommitUncertain)
            );
            assert_eq!(
                job(&fixtures, FileCas::open(&path)).claim(),
                Err(TerminalLearningErrorV1::CommitUncertain)
            );
            assert_eq!(store.commits.load(Ordering::SeqCst), 1);
        } else {
            let first = job(&fixtures, store.clone());
            let other_store = FileCas::open(&path);
            let second = job(&fixtures, other_store.clone());
            let barrier = std::sync::Barrier::new(2);
            let results = std::thread::scope(|scope| {
                let first = scope.spawn(|| {
                    barrier.wait();
                    first.claim()
                });
                let second = scope.spawn(|| {
                    barrier.wait();
                    second.claim()
                });
                [first.join().unwrap(), second.join().unwrap()]
            });
            assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
            assert_eq!(
                store.commits.load(Ordering::SeqCst) + other_store.commits.load(Ordering::SeqCst),
                1
            );
        }
        let bytes = std::fs::read(&path).unwrap();
        let recovered = native(&fixtures, job(&fixtures, FileCas::open(&path)));
        assert_eq!(
            recovered
                .train(fixtures.request.clone(), /*now*/ 50)
                .await
                .unwrap_err(),
            TerminalLearningErrorV1::CommitUncertain
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[tokio::test]
async fn durable_current_read_time_counts_before_any_native_admission() {
    let fixtures = fixtures().await;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("original-job");
    let store = FileCas::create(&path, &fixtures);
    let owner = native(&fixtures, job(&fixtures, store.clone()));
    let bytes = std::fs::read(&path).unwrap();
    store.load_delay_millis.store(2_000, Ordering::SeqCst);
    assert_eq!(
        owner
            .train(fixtures.request.clone(), /*now*/ 89)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::DeadlineExceeded
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}
