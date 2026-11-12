//! Actual Source/Ledger and native owner mechanisms for one bounded operation.
//! Same-UID evidence transport remains explicit fixture custody. These cases
//! do not constitute ordinary Root assembly, adoption, or restart acceptance.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use crate::OriginalCellQ24TrainingStageErrorV1 as StageError;

use super::*;

#[tokio::test]
async fn source_operation_candidate_and_model_keep_two_reads_per_lane() -> anyhow::Result<()> {
    let fixture = Harness::from_fixture(Fixture::candidate_pages().await?)?;
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
    let completed = stage
        .execute_training(&fixture.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(completed.outcome, CellQ24TrainingOutcomeV1::Candidate(_)));
    let retained = fixture.bytes()?;
    let model_file = fixture.file("source-operation-model", true)?;
    let model_witness = fixture.witness("source-operation-model-witness", true)?;
    let dataset = fixture.config.dataset.clone();
    let (stage, model, candidate) = tokio::task::spawn_blocking(move || {
        let model = stage.create_model_owner(model_file, model_witness)?;
        let candidate = stage.read_candidate_material(&dataset)?;
        Ok::<_, StageError>((stage, model, candidate))
    })
    .await??;
    assert!(!fs::read(fixture.root.join("source-operation-model"))?.is_empty());
    assert_ne!(candidate.bundle(), &fixture.config.dataset.request.selected_bundle);
    assert_eq!(candidate.receipt(), &completed.receipt);
    assert_eq!(candidate.attestation(), &completed.attestation);
    assert_eq!(candidate.heads().len(), 12 + 64 * 64 * 8);
    let reread = stage.readback(&fixture.config.dataset).await?;
    assert_eq!(reread.receipt, completed.receipt);
    assert_eq!(reread.attestation, completed.attestation);
    assert_eq!(fixture.bytes()?, retained);
    drop((candidate, model, stage));
    // Capture 2 + original admission 2 + SourceBound admission 2 +
    // first fit 8 (its legacy pre/post/signing checks remain) +
    // actual Model creation 2 + Candidate material 2 + final readback 2.
    assert_eq!(finish(peers)?, [20, 20]);
    Ok(())
}

struct GatedNativeRead {
    witness: FileAnchorWitnessStore,
    remaining: Arc<AtomicUsize>,
    entered: Arc<tokio::sync::Notify>,
    release: Mutex<std::sync::mpsc::Receiver<()>>,
}

impl AnchorWitnessStore for GatedNativeRead {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        if self
            .remaining
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |value| value.checked_sub(1))
            == Ok(1)
        {
            self.entered.notify_one();
            self.release
                .lock()
                .map_err(|_| WitnessStoreError::Indeterminate)?
                .recv_timeout(Duration::from_secs(5))
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        }
        self.witness.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.witness.compare_and_swap(expected, next)
    }
}

type GatedStage = SourceBoundCellQ24TrainingStageV1<GatedNativeRead, FileAnchorWitnessStore>;

async fn gated_completed_stage(
    fixture: &Harness,
) -> anyhow::Result<(
    Arc<GatedStage>,
    Peers,
    Arc<AtomicUsize>,
    Arc<tokio::sync::Notify>,
    std::sync::mpsc::SyncSender<()>,
)> {
    let (capture, peers) = fixture.capture().await?;
    let remaining = Arc::new(AtomicUsize::new(0));
    let entered = Arc::new(tokio::sync::Notify::new());
    let (release, receiver) = std::sync::mpsc::sync_channel(1);
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        GatedNativeRead {
            witness: fixture.witness("native-witness", true)?,
            remaining: Arc::clone(&remaining),
            entered: Arc::clone(&entered),
            release: Mutex::new(receiver),
        },
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = Arc::new(SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?);
    let completed = stage
        .execute_training(&fixture.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(completed.outcome, CellQ24TrainingOutcomeV1::NoUpdate { .. }));
    Ok((stage, peers, remaining, entered, release))
}

#[tokio::test]
async fn source_operation_after_read_withdrawal_fences_completed_native_result()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (stage, peers, remaining, entered, release) = gated_completed_stage(&fixture).await?;
    let retained = fixture.bytes()?;
    // Two witness reads precede Source begin. The third is actual native
    // readback during work, after the complete Source before read.
    remaining.store(3, Ordering::SeqCst);
    let running = Arc::clone(&stage);
    let dataset = fixture.config.dataset.clone();
    let waiting = tokio::spawn(async move { running.readback(&dataset).await });
    tokio::time::timeout(Duration::from_secs(5), entered.notified()).await?;
    fixture.source.withdraw_source(&fixture.config.dataset.request.source_run_id)?;
    release.send(())?;
    assert!(matches!(waiting.await?, Err(StageError::CommitUncertain)));
    assert!(matches!(
        stage.readback(&fixture.config.dataset).await,
        Err(StageError::CommitUncertain)
    ));
    assert_eq!(fixture.bytes()?, retained);
    drop(stage);
    assert_eq!(finish(peers)?, [16, 16]);
    Ok(())
}

#[tokio::test]
async fn source_operation_cancelled_waiter_keeps_lane_then_fences() -> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (stage, peers, remaining, entered, release) = gated_completed_stage(&fixture).await?;
    let retained = fixture.bytes()?;
    remaining.store(3, Ordering::SeqCst);
    let running = Arc::clone(&stage);
    let dataset = fixture.config.dataset.clone();
    let waiting = tokio::spawn(async move { running.readback(&dataset).await });
    tokio::time::timeout(Duration::from_secs(5), entered.notified()).await?;
    waiting.abort();
    assert!(matches!(waiting.await, Err(error) if error.is_cancelled()));
    assert!(matches!(stage.readback(&fixture.config.dataset).await, Err(StageError::Busy)));
    assert_eq!(fixture.bytes()?, retained);
    release.send(())?;
    let after = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            match stage.readback(&fixture.config.dataset).await {
                Err(StageError::Busy) => tokio::task::yield_now().await,
                other => break other,
            }
        }
    })
    .await?;
    assert!(matches!(after, Err(StageError::CommitUncertain)));
    assert_eq!(fixture.bytes()?, retained);
    drop(stage);
    assert_eq!(finish(peers)?, [16, 16]);
    Ok(())
}

#[tokio::test]
async fn source_operation_rejects_equal_capture_from_different_arc() -> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (first, first_peers) = fixture.capture().await?;
    let (second, second_peers) = fixture.capture().await?;
    assert_eq!(first.source_capture_binding(), second.source_capture_binding());
    tokio::task::spawn_blocking(move || {
        let first = Arc::new(first);
        let second = Arc::new(second);
        let operation = OriginalCellQ24TrainingSourceV1::begin_source_operation(&first)?;
        assert!(operation.require_original_source(&second).is_err());
        drop(operation);
        assert!(first.source_operation_fenced());
        assert!(!second.source_operation_fenced());
        assert!(matches!(
            first.require_current_in_lane(),
            Err(OriginalCellQ24TrainingSourceErrorV1::CaptureUncertain)
        ));
        second.require_current_in_lane()?;
        Ok::<_, OriginalCellQ24TrainingSourceErrorV1>(())
    })
    .await??;
    assert_eq!(finish(first_peers)?, [3, 3]);
    assert_eq!(finish(second_peers)?, [4, 4]);
    Ok(())
}

#[tokio::test]
async fn source_operation_abandoned_finish_preserves_real_native_effect_and_fences()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (capture, peers) = fixture.capture().await?;
    let mut training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        capture,
    )?;
    drop(fixture.receipts(true)?);
    let before = fixture.bytes()?;
    tokio::task::spawn_blocking(move || {
        let source = training.original_source_for_operation()?.expect("actual sealed Source");
        let operation = OriginalCellQ24TrainingSourceV1::begin_source_operation(&source)?;
        let completed = training.fit_or_readback(&AtomicBool::new(false))?;
        assert!(matches!(completed, CellQ24TrainingOutcomeV1::NoUpdate { .. }));
        // Simulate loss of the occupied operation before its after read/finish.
        drop(operation);
        assert!(matches!(training.readback(), Err(CellQ24TrainingOwnerErrorV1::CommitUncertain)));
        Ok::<_, CellQ24TrainingOwnerErrorV1>(())
    })
    .await??;
    assert_eq!(finish(peers)?, [7, 7]);
    let after = fixture.bytes()?;
    assert_ne!(before[0], after[0]);
    assert_ne!(before[1], after[1]);
    assert_eq!(before[2..], after[2..], "no Generator receipt was claimed");

    let (capture, peers) = fixture.capture().await?;
    let mut recovered = CellQ24TrainingOwnerV1::recover_from_original_source(
        fixture.file("native-training", false)?,
        fixture.witness("native-witness", false)?,
        capture,
    )?;
    assert!(matches!(recovered.readback()?, CellQ24TrainingOutcomeV1::NoUpdate { .. }));
    drop(recovered);
    assert_eq!(finish(peers)?, [2, 2]);
    assert_eq!(fixture.bytes()?, after);
    Ok(())
}
