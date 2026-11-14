//! Native optimizer and original file/witness tests with explicit Dataset and
//! credential fixtures. No full StageOwner, production custody or B/C claim.

use std::sync::Mutex;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;

use super::*;
use crate::OriginalCellQ24TrainingStageErrorV1 as StageError;
use crate::OriginalCellQ24TrainingStageV1 as Stage;
use pretty_assertions::assert_eq;

#[cfg(target_os = "linux")]
#[path = "cell_q24_training_material_tests.rs"]
mod material;

fn retained(f: &ReceiptFixture) -> anyhow::Result<[Vec<u8>; 4]> {
    Ok([
        fs::read(f.root.path().join("job"))?,
        fs::read(f.root.path().join("witness"))?,
        fs::read(f.root.path().join("receipts"))?,
        fs::read(f.root.path().join("receipt-witness"))?,
    ])
}

#[tokio::test]
async fn original_training_stage_runs_both_outcomes_and_reopens_exactly() -> anyhow::Result<()> {
    for target in [2 * Q, Q] {
        let f = ReceiptFixture::new(target)?;
        let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
        let result = stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ false)))
            .await?;
        assert_eq!(
            matches!(&result.outcome, CellQ24TrainingOutcomeV1::NoUpdate { .. }),
            target == Q
        );
        let saved = retained(&f)?;
        let mut other = f.config.dataset.clone();
        other.request.source_run_id = StableId::new("wrong-stage-request")?;
        assert!(matches!(
            stage
                .execute_training(&other, Arc::new(AtomicBool::new(/*v*/ false)))
                .await,
            Err(StageError::Binding(_))
        ));
        let mut wrong = result.receipt.clone();
        wrong.observed_unix_seconds += 1;
        assert!(matches!(
            stage.receipt_attestation(&f.config.dataset, &wrong).await,
            Err(StageError::Binding(_))
        ));
        assert_eq!(
            stage
                .receipt_attestation(&f.config.dataset, &result.receipt)
                .await?,
            result.attestation
        );
        drop(stage);
        let stage =
            Stage::from_original_owners(f.recover_training()?, f.recover_receipts()?).await?;
        let restored = stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ true)))
            .await?;
        assert_eq!(
            result_identity(&restored.outcome)?,
            result_identity(&result.outcome)?
        );
        assert_eq!(
            (restored.receipt, restored.attestation),
            (result.receipt, result.attestation)
        );
        assert_eq!(retained(&f)?, saved);
    }
    Ok(())
}

#[tokio::test]
async fn original_training_stage_rejects_wrong_pair_and_pending_without_work() -> anyhow::Result<()>
{
    let mut f = ReceiptFixture::new(2 * Q)?;
    let training = f.create_training()?;
    let original_job = fs::read(f.root.path().join("job"))?;
    let mut other = f.config.dataset.clone();
    other.request.source_run_id = StableId::new("different-original-source")?;
    f.config = signing_config(&other, &f.data, f.rule)?;
    assert!(matches!(
        Stage::from_original_owners(training, f.create_receipts()?).await,
        Err(StageError::Training(OwnerError::Binding(_)))
    ));
    assert_eq!(fs::read(f.root.path().join("job"))?, original_job);

    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    assert!(matches!(
        training.fit_or_readback(&AtomicBool::new(/*v*/ true)),
        Err(OwnerError::Training(CellQ24TrainingErrorV1::Cancelled))
    ));
    let stage = Stage::from_original_owners(training, f.create_receipts()?).await?;
    let saved = retained(&f)?;
    assert!(matches!(
        stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ false)))
            .await,
        Err(StageError::Training(OwnerError::Pending))
    ));
    assert!(stage.readback(&f.config.dataset).await.is_err());
    assert_eq!(retained(&f)?, saved);

    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    training.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    let mut receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
        opened(f.root.path(), "receipts")?,
        FaultWitness {
            inner: f.receipt_witness()?,
            sequence: 2,
            fault: LostAck::AfterWrite,
        },
        f.config.clone(),
        SigningKey::from_bytes(&[79; 32]),
    )?;
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    drop(receipts);
    let saved = retained(&f)?;
    assert!(matches!(
        Stage::from_original_owners(training, f.recover_receipts()?).await,
        Err(StageError::Receipt(ReceiptError::Owner(
            LearningOriginalOwnerErrorV1::Pending
        )))
    ));
    assert_eq!(retained(&f)?, saved);
    Ok(())
}

#[tokio::test]
async fn original_training_stage_distinguishes_missing_receipt_from_missing_native()
-> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let trained = training.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    let native = (
        fs::read(f.root.path().join("job"))?,
        fs::read(f.root.path().join("witness"))?,
    );
    let stage = Stage::from_original_owners(training, f.create_receipts()?).await?;
    let completed = stage
        .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ true)))
        .await?;
    assert_eq!(
        result_identity(&completed.outcome)?,
        result_identity(&trained)?
    );
    assert_eq!(
        (
            fs::read(f.root.path().join("job"))?,
            fs::read(f.root.path().join("witness"))?
        ),
        native
    );
    drop(stage);
    let saved = retained(&f)?;
    let fresh = CellQ24TrainingOwnerV1::create(
        opened(f.root.path(), "replacement-job")?,
        FileAnchorWitnessStore::open(
            opened(f.root.path(), "replacement-witness")?,
            JournalScope {
                scope_digest: d("original-q24-trainer"),
                objective_digest: d("objective"),
            },
            Generation::new(/*value*/ 1)?,
            /*max_records*/ 16,
        )?,
        original_plan(Arc::clone(&f.baseline), &f.config.dataset, &f.data, f.rule)?,
        f.data.clone(),
        f.rule,
    )?;
    let missing = fs::read(f.root.path().join("replacement-job"))?;
    assert!(matches!(
        Stage::from_original_owners(fresh, f.recover_receipts()?).await,
        Err(StageError::Receipt(ReceiptError::Training(
            OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        )))
    ));
    assert_eq!(fs::read(f.root.path().join("replacement-job"))?, missing);
    assert_eq!(retained(&f)?, saved);
    Ok(())
}

#[tokio::test]
async fn original_training_stage_expired_missing_never_claims_or_attests() -> anyhow::Result<()> {
    let mut f = ReceiptFixture::new(2 * Q)?;
    let mut prefix = f.config.dataset.clone();
    prefix.request.envelope.expiry_unix_seconds = 100;
    f.config = signing_config(&prefix, &f.data, f.rule)?;
    let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
    let saved = retained(&f)?;
    assert!(f.config.signer.principal.expires_at > clock()?);
    assert!(matches!(
        stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ false)))
            .await,
        Err(StageError::DeadlineExceeded)
    ));
    assert!(matches!(
        stage.readback(&f.config.dataset).await,
        Err(StageError::Receipt(ReceiptError::Training(
            OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        )))
    ));
    assert_eq!(retained(&f)?, saved);
    Ok(())
}

#[tokio::test]
async fn original_training_stage_request_expiry_preserves_only_original_completed_receipts()
-> anyhow::Result<()> {
    let mut unsigned = ReceiptFixture::new(2 * Q)?;
    let mut signed = ReceiptFixture::new(Q)?;
    let expiry = clock()? + 5;
    for f in [&mut unsigned, &mut signed] {
        let mut prefix = f.config.dataset.clone();
        prefix.request.envelope.expiry_unix_seconds = expiry;
        f.config = signing_config(&prefix, &f.data, f.rule)?;
    }
    let mut native = unsigned.create_training()?;
    native.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    let unreceipted = Stage::from_original_owners(native, unsigned.create_receipts()?).await?;
    let completed =
        Stage::from_original_owners(signed.create_training()?, signed.create_receipts()?).await?;
    let original = completed
        .execute_training(
            &signed.config.dataset,
            Arc::new(AtomicBool::new(/*v*/ false)),
        )
        .await?;
    let unsigned_bytes = retained(&unsigned)?;
    let signed_bytes = retained(&signed)?;
    tokio::time::sleep(Duration::from_secs(expiry.saturating_sub(clock()?) + 1)).await;
    assert!(clock()? >= expiry);
    assert!(clock()? < original.attestation.expires_at);
    assert!(matches!(
        unreceipted
            .execute_training(
                &unsigned.config.dataset,
                Arc::new(AtomicBool::new(/*v*/ false))
            )
            .await,
        Err(StageError::DeadlineExceeded)
    ));
    assert_eq!(retained(&unsigned)?, unsigned_bytes);
    drop(completed);
    let reopened =
        Stage::from_original_owners(signed.recover_training()?, signed.recover_receipts()?).await?;
    let reread = reopened
        .execute_training(
            &signed.config.dataset,
            Arc::new(AtomicBool::new(/*v*/ true)),
        )
        .await?;
    assert_eq!(
        result_identity(&reread.outcome)?,
        result_identity(&original.outcome)?
    );
    assert_eq!(reread.receipt, original.receipt);
    assert_eq!(reread.attestation, original.attestation);
    assert_eq!(
        reopened
            .receipt_attestation(&signed.config.dataset, &original.receipt)
            .await?,
        original.attestation
    );
    assert_eq!(retained(&signed)?, signed_bytes);
    Ok(())
}

struct GatedWitness {
    inner: FileAnchorWitnessStore,
    armed: Arc<AtomicBool>,
    entered: Arc<tokio::sync::Notify>,
    release: Mutex<std::sync::mpsc::Receiver<()>>,
}

impl AnchorWitnessStore for GatedWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        if self.armed.swap(/*val*/ false, Ordering::SeqCst) {
            self.entered.notify_one();
            self.release
                .lock()
                .map_err(|_| WitnessStoreError::Indeterminate)?
                .recv_timeout(Duration::from_secs(/*secs*/ 5))
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        }
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn original_training_stage_keeps_lane_until_cancelled_waiter_worker_exits()
-> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let armed = Arc::new(AtomicBool::new(/*v*/ false));
    let entered = Arc::new(tokio::sync::Notify::new());
    let (release, receiver) = std::sync::mpsc::sync_channel(/*bound*/ 1);
    let training = CellQ24TrainingOwnerV1::create(
        opened(f.root.path(), "job")?,
        GatedWitness {
            inner: witness(f.root.path())?,
            armed: Arc::clone(&armed),
            entered: Arc::clone(&entered),
            release: Mutex::new(receiver),
        },
        original_plan(Arc::clone(&f.baseline), &f.config.dataset, &f.data, f.rule)?,
        f.data.clone(),
        f.rule,
    )?;
    let stage = Arc::new(Stage::from_original_owners(training, f.create_receipts()?).await?);
    armed.store(/*val*/ true, Ordering::SeqCst);
    let running = Arc::clone(&stage);
    let dataset = f.config.dataset.clone();
    let waiting = tokio::spawn(async move {
        running
            .execute_training(&dataset, Arc::new(AtomicBool::new(/*v*/ false)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), entered.notified()).await?;
    let before = retained(&f)?;
    assert!(matches!(
        stage.readback(&f.config.dataset).await,
        Err(StageError::Busy)
    ));
    assert!(matches!(
        stage
            .receipt_attestation(&f.config.dataset, &f.config.dataset.receipts[0])
            .await,
        Err(StageError::Busy)
    ));
    waiting.abort();
    assert!(matches!(waiting.await, Err(error) if error.is_cancelled()));
    assert!(matches!(
        stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ false)))
            .await,
        Err(StageError::Busy)
    ));
    assert_eq!(retained(&f)?, before);
    release.send(())?;
    let result = tokio::time::timeout(Duration::from_secs(/*secs*/ 10), async {
        loop {
            match stage.readback(&f.config.dataset).await {
                Err(StageError::Busy) => tokio::task::yield_now().await,
                other => break other,
            }
        }
    })
    .await??;
    let saved = retained(&f)?;
    assert_ne!(saved, before);
    let repeated = stage
        .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(/*v*/ true)))
        .await?;
    assert_eq!(
        (repeated.receipt, repeated.attestation),
        (result.receipt, result.attestation)
    );
    assert_eq!(retained(&f)?, saved);
    Ok(())
}
