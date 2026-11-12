//! Actual task/Ledger component owners exercise borrow identity and withdrawal.
//! Their explicit test issuers do not prove a deployed Root historical loop.

use pretty_assertions::assert_eq;

use super::*;
use crate::cell_composed_q24::OriginalPreparedReadV1;
use crate::cell_composed_q24::OriginalQ24DatasetReadV1;

#[tokio::test]
async fn q24_training_source_operation_requires_the_same_actual_dataset_capability()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "training-source-borrow",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(2_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = config(&dataset, &publication, baseline, bundle)?;
    let prepared = prepare(config.clone(), &dataset)?;
    let cut = dataset_cut(&prepared)?;
    let material = prepared.training_material(cut.clone(), prepared.scope().clone())?;
    let another = CellQ24PreparedLearningV1::recover(
        config,
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
        prepared.frozen_dataset().clone(),
        prepared.initial(),
        prepared.scope(),
    )?;
    let other_material = another.training_material(cut, another.scope().clone())?;
    assert_eq!(material.batch.encoded(), other_material.batch.encoded());
    prepared.with_original_prepared_operation(|read| -> anyhow::Result<()> {
        OriginalQ24DatasetReadV1::require_current_batch(read, &material.batch.clone())?;
        assert!(matches!(
            OriginalPreparedReadV1::require_training_batch(read, &other_material.batch),
            Err(CellQ24TrainingErrorV1::Binding(
                "operation borrowed another Trainer Dataset capability"
            ))
        ));
        let cancelled = std::sync::atomic::AtomicBool::new(/*val*/ true);
        assert!(matches!(
            material.plan.fit_with_original_source(
                material.batch.clone(),
                material.rule,
                &cancelled,
                read,
            ),
            Err(CellQ24TrainingErrorV1::Cancelled)
        ));
        Ok(())
    })??;
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_training_source_operation_rechecks_withdrawal_before_return() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "training-source-withdrawal",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let prepared = prepare(config(&dataset, &publication, baseline, bundle)?, &dataset)?;
    let material = prepared.training_material(dataset_cut(&prepared)?, prepared.scope().clone())?;
    let result = prepared.with_original_prepared_operation(|read| -> anyhow::Result<()> {
        OriginalPreparedReadV1::require_training_batch(read, &material.batch)?;
        session
            .source
            .withdraw_for_dataset_test(&publication.input().scope.run_id)?;
        assert!(OriginalPreparedReadV1::require_training_batch(read, &material.batch).is_err());
        // Even a caller that observes this failure and returns Ok cannot erase
        // the enclosing operation's independent final source check.
        Ok(())
    });
    assert!(result.is_err());
    session.stop().await?;
    Ok(())
}
