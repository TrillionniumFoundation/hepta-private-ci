//! True ordinary Q24 A -> authenticated ledger Dataset -> original training
//! owner/signature -> cold readback. Keys, terminal scores, prefix stage receipts
//! and CURRENT custody are fixtures. This is not independent B, C adoption,
//! production original-owner custody, or an OS daemon/Root recovery claim.

use std::fs;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;

use super::*;
use crate::CellQ24TrainingOutcomeV1;
use crate::OriginalCellQ24TrainingSourceV1;
use crate::OriginalCellQ24TrainingStageErrorV1 as StageError;
use crate::OriginalCellQ24TrainingStageV1 as Stage;

#[path = "cell_q24_dataset_training_ingress_support_tests.rs"]
mod fixtures;
use fixtures::Native;
use fixtures::Training;

#[tokio::test]
async fn original_dataset_native_stage_runs_candidate_and_no_update_and_reopens_exactly()
-> anyhow::Result<()> {
    for (target, unchanged) in [(2_i64 << 32, false), (1_i64 << 32, true)] {
        let native = Native::new(target).await?;
        let f = Training::new(
            &native,
            native.material.profile().principal_id.clone(),
            native.material.batch().clone(),
        )?;
        let source_before = native.source_bytes()?;
        let stage = f.stage(false).await?;
        let result = stage
            .execute_training_from_original_dataset(
                &f.config.dataset,
                native.context(),
                Arc::new(AtomicBool::new(false)),
            )
            .await?;
        pretty_assertions::assert_eq!(
            matches!(&result.outcome, CellQ24TrainingOutcomeV1::NoUpdate { .. }),
            unchanged
        );
        match &result.outcome {
            CellQ24TrainingOutcomeV1::NoUpdate {
                retained_bundle,
                metrics,
            } => {
                pretty_assertions::assert_eq!(
                    (
                        *retained_bundle,
                        metrics.optimizer_steps,
                        metrics.squared_error_before_q48,
                        metrics.squared_error_after_q48
                    ),
                    (native.bundle.digest()?, 2, 0, 0)
                );
            }
            CellQ24TrainingOutcomeV1::Candidate(candidate) => {
                assert_ne!(
                    candidate.bundle.components.heads,
                    native.bundle.components.heads
                );
                pretty_assertions::assert_eq!(
                    candidate.bundle.rollback_predecessor,
                    Some(native.bundle.digest()?)
                );
                pretty_assertions::assert_eq!(candidate.metrics.optimizer_steps, 2);
            }
        }
        pretty_assertions::assert_eq!(
            stage
                .receipt_attestation_from_original_dataset(
                    &f.config.dataset,
                    native.context(),
                    &result.receipt
                )
                .await?,
            result.attestation
        );
        let saved = f.retained()?;
        drop(stage);
        let stage = f.stage(true).await?;
        let restored = stage
            .readback_from_original_dataset(&f.config.dataset, native.context())
            .await?;
        pretty_assertions::assert_eq!(
            (restored.receipt, restored.attestation),
            (result.receipt.clone(), result.attestation)
        );
        pretty_assertions::assert_eq!(f.retained()?, saved);
        pretty_assertions::assert_eq!(native.source_bytes()?, source_before);

        native
            .original
            .withdraw_source(&native.publication.input().scope.run_id)?;
        let after_withdrawal = native.source_bytes()?;
        assert!(
            stage
                .execute_training_from_original_dataset(
                    &f.config.dataset,
                    native.context(),
                    Arc::new(AtomicBool::new(false))
                )
                .await
                .is_err()
        );
        assert!(
            stage
                .readback_from_original_dataset(&f.config.dataset, native.context())
                .await
                .is_err()
        );
        assert!(
            stage
                .receipt_attestation_from_original_dataset(
                    &f.config.dataset,
                    native.context(),
                    &result.receipt
                )
                .await
                .is_err()
        );
        pretty_assertions::assert_eq!(f.retained()?, saved);
        pretty_assertions::assert_eq!(native.source_bytes()?, after_withdrawal);
    }
    Ok(())
}

#[tokio::test]
async fn original_dataset_scope_and_same_dataset_different_batch_reject_before_claim()
-> anyhow::Result<()> {
    let native = Native::new(2_i64 << 32).await?;
    let wrong_batch = crate::CellQ24TrainingBatchV1::new(
        native.material.dataset().snapshot.dataset_digest,
        vec![crate::CellQ24TrainingSampleV1 {
            input: vec![Q, Q / 2],
            target: -Q,
        }],
    )?;
    for (principal, data) in [
        (
            cell::id("foreign-learning-principal"),
            native.material.batch().clone(),
        ),
        (native.material.profile().principal_id.clone(), wrong_batch),
    ] {
        let f = Training::new(&native, principal, data)?;
        let stage = f.stage(false).await?;
        let original = f.retained()?;
        assert!(
            stage
                .execute_training_from_original_dataset(
                    &f.config.dataset,
                    native.context(),
                    Arc::new(AtomicBool::new(false))
                )
                .await
                .is_err()
        );
        pretty_assertions::assert_eq!(f.retained()?, original);
    }
    let actual_run = native.publication.input().scope.run_id.clone();
    let actual_completion = native
        .publication
        .history_digest()
        .as_str()
        .parse::<Digest32>()?;
    for (run, completion) in [
        (cell::id("foreign-original-trigger"), actual_completion),
        (actual_run, cell::d("foreign-completed-task-receipt")),
    ] {
        let f = Training::new(
            &native,
            native.material.profile().principal_id.clone(),
            native.material.batch().clone(),
        )?
        .with_trigger(run, completion)?;
        let stage = f.stage(false).await?;
        let before = f.retained()?;
        assert!(matches!(
            stage
                .execute_training_from_original_dataset(
                    &f.config.dataset,
                    native.context(),
                    Arc::new(AtomicBool::new(false)),
                )
                .await,
            Err(StageError::Source(
                crate::OriginalCellQ24DatasetErrorV1::Binding(_)
            ))
        ));
        pretty_assertions::assert_eq!(f.retained()?, before);
    }
    Ok(())
}

struct WithdrawOnCompletedTraining {
    inner: FileAnchorWitnessStore,
    source: fixtures::NativeSource,
    run: StableId,
}
impl AnchorWitnessStore for WithdrawOnCompletedTraining {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        // Actual native fit has completed and its own original witness ACKs.
        // Withdraw the real source before the stage can claim/sign its receipt.
        if next.sequence == 3 {
            self.source
                .withdraw_source(&self.run)
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        }
        Ok(())
    }
}

#[tokio::test]
async fn original_dataset_withdrawn_during_fit_is_retained_but_never_signed_or_retrained()
-> anyhow::Result<()> {
    let native = Native::new(2_i64 << 32).await?;
    let f = Training::new(
        &native,
        native.material.profile().principal_id.clone(),
        native.material.batch().clone(),
    )?;
    let witness = WithdrawOnCompletedTraining {
        inner: f.witness()?,
        source: native.original.clone(),
        run: native.publication.input().scope.run_id.clone(),
    };
    let stage =
        Stage::from_original_owners(f.training(witness, false)?, f.receipts(false)?).await?;
    let unsigned = f.signature_bytes()?;
    assert!(matches!(
        stage
            .execute_training_from_original_dataset(
                &f.config.dataset,
                native.context(),
                Arc::new(AtomicBool::new(false))
            )
            .await,
        Err(StageError::Source(_))
    ));
    pretty_assertions::assert_eq!(f.signature_bytes()?, unsigned);
    let completed_native_job = f.retained()?;
    assert!(
        stage
            .execute_training_from_original_dataset(
                &f.config.dataset,
                native.context(),
                Arc::new(AtomicBool::new(false))
            )
            .await
            .is_err()
    );
    assert!(
        stage
            .readback_from_original_dataset(&f.config.dataset, native.context())
            .await
            .is_err()
    );
    pretty_assertions::assert_eq!(f.retained()?, completed_native_job);
    drop(stage);
    let mut recovered = f.training(f.witness()?, true)?;
    assert!(matches!(
        recovered.readback()?,
        CellQ24TrainingOutcomeV1::Candidate(_)
    ));
    pretty_assertions::assert_eq!(f.signature_bytes()?, unsigned);
    pretty_assertions::assert_eq!(f.retained()?, completed_native_job);
    Ok(())
}
