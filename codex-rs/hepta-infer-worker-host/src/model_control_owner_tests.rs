use super::*;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test]
async fn shared_wait_preserves_the_original_deadline_and_terminal_record() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original.control");
    let mut journal = DurableInferenceControl::open(&path, 8)?;
    super::super::tests::settle_fixture(&mut journal);
    let original = journal.native_record_resolved("assessment-1")?;
    let bytes = std::fs::read(&path)?;
    let shared = Arc::new(tokio::sync::Mutex::new(journal));
    let held = shared.clone().lock_owned().await;
    let owner = ModelControlOwner(shared.clone());
    assert!(matches!(
        owner.acquire(Duration::from_millis(10)).await,
        Err(SelfIterationModelErrorV1::TimedOut)
    ));
    assert!(DurableInferenceControl::open(&path, 8).is_err());
    drop(held);
    let lease = owner.acquire(Duration::from_secs(1)).await?;
    assert_eq!(lease.native_record_resolved("assessment-1")?, original);
    drop(lease);
    assert_eq!(std::fs::read(&path)?, bytes);
    Ok(())
}

#[tokio::test]
async fn cancellation_returns_the_same_exclusive_owner_without_reopening() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original.control");
    let mut journal = DurableInferenceControl::open(&path, 8)?;
    super::super::tests::settle_fixture(&mut journal);
    let original = journal.native_record_resolved("assessment-1")?;
    let bytes = std::fs::read(&path)?;
    let shared = Arc::new(tokio::sync::Mutex::new(journal));
    let borrowed = shared.clone();
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        let owner = ModelControlOwner(borrowed);
        let _lease = owner.acquire(Duration::from_secs(1)).await?;
        sender
            .send(())
            .map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?;
        std::future::pending::<()>().await;
        Ok::<(), SelfIterationModelErrorV1>(())
    });
    receiver.await?;
    assert!(shared.try_lock().is_err());
    task.abort();
    assert!(task.await.err().is_some_and(|error| error.is_cancelled()));
    let owner = ModelControlOwner(shared);
    assert_eq!(
        owner
            .try_acquire()?
            .native_record_resolved("assessment-1")?,
        original
    );
    assert_eq!(std::fs::read(&path)?, bytes);
    assert!(DurableInferenceControl::open(&path, 8).is_err());
    Ok(())
}
