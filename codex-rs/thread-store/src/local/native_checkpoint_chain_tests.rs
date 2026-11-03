//! Real original LocalThreadStore evidence; these reads never obtain a host permit.
use super::*;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test]
async fn complete_chain_survives_real_store_reopen_and_keeps_every_original_revision() -> TestResult {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    let first = fixture.live.commit_native_checkpoint(
        &session, NativeCheckpointExpected::Absent, fixture.state(""),
    ).await?;
    let second = fixture.live.commit_native_checkpoint(
        &session, NativeCheckpointExpected::Version(first.version.clone()), fixture.state("response:original"),
    ).await?;
    assert_eq!(fixture.live.load_native_checkpoint_chain(&session).await?, vec![first.clone(), second.clone()]);
    fixture.live.shutdown().await?;
    assert!(fixture.live.load_native_checkpoint_chain(&session).await.is_err());
    *fixture.authority.current.write().await = (8, "lease:successor".to_string());
    let reopened = Arc::new(LocalThreadStore::new(test_config(fixture.home.path()), None));
    let live = LiveThread::resume(reopened, ThreadHistoryMode::Legacy, fixture.resume.clone()).await?;
    let resumed = live.open_native_checkpoint(
        fixture.binding.clone(), NativeCheckpointOpenMode::Recover, fixture.authority.clone(),
    ).await?;
    assert_eq!(live.load_native_checkpoint_chain(&resumed).await?, vec![first, second]);
    live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn complete_chain_rejects_corrupt_old_revision_even_when_head_is_unchanged() -> TestResult {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    let first = fixture.live.commit_native_checkpoint(
        &session, NativeCheckpointExpected::Absent, fixture.state(""),
    ).await?;
    fixture.live.commit_native_checkpoint(
        &session, NativeCheckpointExpected::Version(first.version), fixture.state("response:original"),
    ).await?;
    let pool = database(&fixture.store, NativeCheckpointOpenMode::Inspect).await?;
    sqlx::query("UPDATE checkpoint_rows SET payload = X'01' WHERE revision = 1").execute(pool).await?;
    assert!(fixture.live.load_native_checkpoint_chain(&session).await.is_err());
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn complete_chain_counts_utf8_bytes_and_all_metadata_before_collecting() -> TestResult {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    let mut state = fixture.state("");
    state.payload = "原始完整结果".as_bytes().to_vec();
    let record = fixture.live.commit_native_checkpoint(&session, NativeCheckpointExpected::Absent, state).await?;
    let pool = database(&fixture.store, NativeCheckpointOpenMode::Inspect).await?;
    let mut transaction = pool.begin().await?;
    let bytes = serde_json::to_vec(&record.state.binding)?.len() as u64
        + record.rollout_id.to_string().len() as u64
        + record.version.sha256.len() as u64
        + record.state.payload.len() as u64
        + 8 + 64 + 8; // row revision plus original head hash and revision
    assert_eq!(super::super::chain::read_bounded(&mut transaction, &session, 1, bytes).await?, vec![record]);
    assert!(super::super::chain::read_bounded(&mut transaction, &session, 1, bytes - 1).await.is_err());
    assert!(super::super::chain::read_bounded(&mut transaction, &session, 0, bytes).await.is_err());
    transaction.commit().await?;
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn complete_chain_inspection_never_creates_storage_and_rejects_wrong_binding() -> TestResult {
    let fixture = Fixture::new().await;
    let inspect = fixture.session(NativeCheckpointOpenMode::Inspect).await;
    assert!(fixture.live.load_native_checkpoint_chain(&inspect).await?.is_empty());
    assert!(!fixture.home.path().join(DATABASE).exists());
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    fixture.live.commit_native_checkpoint(&session, NativeCheckpointExpected::Absent, fixture.state("")).await?;
    let mut other = fixture.binding.clone();
    other.generation += 1;
    let other = fixture.live.open_native_checkpoint(other, NativeCheckpointOpenMode::Recover, fixture.authority.clone()).await?;
    assert!(fixture.live.load_native_checkpoint_chain(&other).await.is_err());
    fixture.live.shutdown().await?;
    Ok(())
}
