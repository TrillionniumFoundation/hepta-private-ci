//! Actual postpublication C channel -> original Decision -> independent
//! Observer Outcome -> real Dataset material. Root publication, role custody
//! and current-generation setup remain explicit component fixtures.

use super::*;
use std::sync::Arc;
use crate::CircuitTaskLearningPendingV1;
use crate::CircuitTaskLearningReadinessV1;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn successor_feedback_requires_original_outcome_before_real_dataset() -> anyhow::Result<()> {
    let mut f = Fixture::new_profile(
        "original-successor-feedback",
        /*lifetime*/ 600,
        fixture::TaskProfile::SuccessorFeedback,
    )
    .await?;
    let task_bytes = f.task_bytes()?;
    assert!(Arc::ptr_eq(
        f.session.ledger.as_ref().expect("original successor producer"),
        &f.producer,
    ));
    let trace = f
        .session
        .runtime
        .state
        .circuit_task_store()?
        .bounded_circuit_committed_trace(&f.session.request.body.run_id)
        .await
        .map_err(|error| anyhow::anyhow!("original successor trace: {error:?}"))?
        .expect("actual committed successor trace");
    let record = f.publication.original_record();
    assert!(matches!(f.producer.readback()?, Status::AwaitingOutcome { .. }));
    assert!(matches!(
        f.session.runtime.state.observe_circuit_learning(record, &trace).await,
        CircuitTaskLearningReadinessV1::Pending(CircuitTaskLearningPendingV1::TerminalOutcome)
    ));
    assert!(matches!(
        f.producer.prepare_dataset(f.preparation()?, Vec::new()),
        Err(Error::PendingOutcome)
    ));
    let before = f.learning_bytes()?;
    let mut wrong = f.outcome();
    wrong.support_digest = cell::d("another-consumer-publication");
    let signed_wrong = f.sign_outcome(&wrong, /*lifetime*/ 300);
    assert!(f.producer.submit_original_terminal_outcome(wrong, &signed_wrong).is_err());
    assert_eq!(f.learning_bytes()?, before);

    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    let completed = f.producer.submit_original_terminal_outcome(outcome.clone(), &signed)?;
    assert!(matches!(completed, Status::Complete { .. }));
    let accepted_bytes = f.learning_bytes()?;
    let readiness = f.session.runtime.state.observe_circuit_learning(record, &trace).await;
    assert!(matches!(&readiness, CircuitTaskLearningReadinessV1::Ready(_)));
    f.session.runtime.state.enqueue_original_circuit_learning(record, &trace, readiness).await?;
    assert_eq!(f.producer.submit_original_terminal_outcome(outcome, &signed)?, completed);
    assert_eq!(f.learning_bytes()?, accepted_bytes);
    // This component has not registered another Root source. Feedback does not
    // infer that enrollment or manufacture a new outbox request.
    f.no_outbox().await?;
    let prepared = f.producer.prepare_learning(f.preparation()?, Vec::new(), f.freeze_inputs()?)?;
    let facts = prepared.read_validated_facts()?;
    assert_eq!(
        facts.experience(),
        &codex_hepta_learning_artifacts::LearningIterationObservationV1::Experience {
            episode_digest: f.publication.publication_digest(),
            completed_task_receipt: f.publication.history_digest().as_str().parse()?,
        }
    );
    assert!(prepared.initial().receipts.is_empty());
    prepared.revalidate_source()?;
    f.require_task_unchanged(&task_bytes)?;
    f.session.source.withdraw_for_dataset_test(&record.snapshot.run_id)?;
    assert!(prepared.revalidate_source().is_err());
    assert!(f.producer.readback().is_err());
    f.session.stop().await
}

#[tokio::test]
async fn successor_feedback_refusal_never_installs_a_nonlearning_fallback() -> anyhow::Result<()> {
    match Fixture::new_profile(
        "original-successor-refused-generator",
        /*lifetime*/ 600,
        fixture::TaskProfile::SuccessorRefusedGenerator,
    )
    .await
    {
        Err(error) => {
            anyhow::ensure!(
                format!("{error:#}").contains("original Generator, outcome or source configuration"),
                "expected the original Generator binding rejection: {error:#}"
            );
        }
        Ok(mut unexpected) => {
            unexpected.session.stop().await?;
            anyhow::bail!("refused original feedback installed a task runtime");
        }
    }
    Ok(())
}
