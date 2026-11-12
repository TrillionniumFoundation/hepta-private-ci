//! Real same-source Candidate -> Ineligible B -> baseline publication effects.
//! Same-process role credentials, B clocks and measured Outcomes are explicit
//! fixtures. These tests confer no ordinary-loop or daemon/Root qualification.

use super::*;
use crate::OriginalCircuitRetainedPublicationErrorV1 as PublicationError;
use crate::prepare_original_circuit_evaluated_retention_v1;
use crate::recover_original_circuit_evaluated_retention_v1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

#[path = "circuit_evaluated_retention_publication_support_tests.rs"]
mod publication_fixture;
use publication_fixture::PublicationFixture;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_publishes_baseline_from_same_a_training_and_independent_b()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let context = f.context()?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(context.snapshot().clone())?;
    assert_eq!(context.snapshot(), f.evaluation.snapshot());
    assert_eq!(&context.snapshot().receipts[2], f.training.receipt());
    assert!(context.snapshot().training_no_update_v2().is_none());
    let (trainer, evaluator, peers) = f.clients()?;
    let source_before = f.host.original.predecessor_bytes()?;
    let b_before = f.host.upstream_files()?;
    let evaluation_before = f.host.original_files()?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    let before_current = f.host.original.version.bytes("current.json")?;
    let prepared =
        prepare_original_circuit_evaluated_retention_v1(context, trainer, evaluator, f.inputs()?)
            .await?;
    assert_eq!(
        prepared.final_use_binding().destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let signed = f.host.original.version.sign(prepared.final_use_binding())?;
    let (task, trainer, evaluator) = prepared
        .publish_and_retain_original_evidence(signed)
        .await?;
    assert_eq!(trainer.readback().await?, f.training);
    assert_eq!(evaluator.readback().await?, f.evaluation);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [5, 5]);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    assert_ne!(
        f.host.original.version.bytes("current.json")?,
        before_current
    );
    assert_ne!(f.source_a.scope.run_id, task.source().scope.run_id);
    assert_ne!(f.source_a.observation, task.source().observation);
    assert_eq!(f.host.original.predecessor_bytes()?, source_before);
    assert_eq!(f.host.upstream_files()?, b_before);
    assert_eq!(f.host.original_files()?, evaluation_before);
    let mut c = f.start_c(task).await?;
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    assert!(matches!(
        c.cell.read_learning_selection(&coordinator)?,
        LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if candidate_bundle == f.bundle.digest()?
    ));
    let publication = execute(&c, /*request_id*/ 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    assert_eq!(actual.representation.drive_q24, vec![Q / 4, Q, 0, 0, 0]);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_preserved_owner_connections_reject_withdrawal_after_publication()
-> anyhow::Result<()> {
    for owner in ["trainer", "evaluator"] {
        let mut f = Box::pin(PublicationFixture::ready()).await?;
        let (trainer, evaluator, peers) = f.clients()?;
        let prepared = prepare_original_circuit_evaluated_retention_v1(
            f.context()?,
            trainer,
            evaluator,
            f.inputs()?,
        )
        .await?;
        let signed = f.host.original.version.sign(prepared.final_use_binding())?;
        let (task, trainer, evaluator) = prepared
            .publish_and_retain_original_evidence(signed)
            .await?;
        let published = f.publication_bytes()?;
        let nonces = f.host.original.version.authority.capacity()?.used_nonces;
        match owner {
            "trainer" => {
                f.host.original.withdraw_original_dataset()?;
                assert!(matches!(
                    trainer.readback().await,
                    Err(crate::OriginalCellQ24TrainingCommandErrorV1::CommitUncertain)
                ));
            }
            "evaluator" => {
                f.host.retention_b.withdraw_target()?;
                assert!(matches!(
                    evaluator.readback().await,
                    Err(crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain)
                ));
            }
            _ => unreachable!(),
        }
        drop(trainer);
        drop(evaluator);
        assert_eq!(
            peers.finish()?,
            if owner == "trainer" { [5, 4] } else { [4, 5] }
        );
        assert_eq!(f.publication_bytes()?, published);
        assert_eq!(
            f.host.original.version.authority.capacity()?.used_nonces,
            nonces
        );
        drop(task);
        f.finish().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_wrong_grant_keeps_original_intent_pending_without_redispatch()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (trainer, evaluator, peers) = f.clients()?;
    let prepared = prepare_original_circuit_evaluated_retention_v1(
        f.context()?,
        trainer,
        evaluator,
        f.inputs()?,
    )
    .await?;
    let intent = prepared.intent_digest();
    let mut wrong = prepared.final_use_binding().clone();
    wrong.destination_id = "runtime.learning.resident-admission.v3".into();
    let signed = f.host.original.version.sign(&wrong)?;
    let prepared_bytes = f.publication_bytes()?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    assert!(matches!(
        prepared.publish_original_retained_task(signed).await,
        Err(PublicationError::CommitUncertain(_))
    ));
    assert_eq!(peers.finish()?, [3, 3]);
    assert_eq!(f.publication_bytes()?, prepared_bytes);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    f.host.recover()?;
    let (trainer, evaluator, peers) = f.clients()?;
    assert!(matches!(
        recover_original_circuit_evaluated_retention_v1(
            trainer, evaluator, f.recovery(intent)?,
        ).await,
        Err(PublicationError::Owner(crate::AgentdError::Invalid(message)))
        if message.contains("remains pending; no redispatch")
    ));
    assert_eq!(peers.finish()?, [1, 1]);
    assert_eq!(f.publication_bytes()?, prepared_bytes);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_prepared_owner_withdrawal_is_uncertain_and_never_spends_grant()
-> anyhow::Result<()> {
    for owner in ["trainer", "evaluator"] {
        let mut f = Box::pin(PublicationFixture::ready()).await?;
        let (trainer, evaluator, peers) = f.clients()?;
        let prepared = prepare_original_circuit_evaluated_retention_v1(
            f.context()?,
            trainer,
            evaluator,
            f.inputs()?,
        )
        .await?;
        let intent = prepared.intent_digest();
        let signed = f.host.original.version.sign(prepared.final_use_binding())?;
        let prepared_bytes = f.publication_bytes()?;
        let nonces = f.host.original.version.authority.capacity()?.used_nonces;
        match owner {
            "trainer" => f.host.original.withdraw_original_dataset()?,
            "evaluator" => f.host.retention_b.withdraw_target()?,
            _ => unreachable!(),
        }
        // This is an actual original owner change after durable prepare.
        // The previous 4-cut evidence cannot restore the captured owner.
        assert!(
            matches!(
                prepared.publish_original_retained_task(signed).await,
                Err(PublicationError::CommitUncertain(_))
            ),
            "{owner}"
        );
        let counts = peers.finish()?;
        assert_eq!(counts[0], 3);
        assert_eq!(counts[1], if owner == "trainer" { 2 } else { 3 });
        assert_eq!(f.publication_bytes()?, prepared_bytes);
        assert_eq!(
            f.host.original.version.authority.capacity()?.used_nonces,
            nonces
        );
        // The original durable intent remains; recovery reads it but cannot
        // turn unavailable original evidence into another prepare or grant.
        let (trainer, evaluator, peers) = f.clients()?;
        let recovered = recover_original_circuit_evaluated_retention_v1(
            trainer,
            evaluator,
            f.recovery(intent)?,
        )
        .await;
        match owner {
            "trainer" => assert!(matches!(
                recovered,
                Err(PublicationError::Training(
                    crate::OriginalCellQ24TrainingCommandErrorV1::CommitUncertain
                ))
            )),
            "evaluator" => assert!(matches!(
                recovered,
                Err(PublicationError::Evaluation(
                    crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                ))
            )),
            _ => unreachable!(),
        }
        assert_eq!(
            peers.finish()?,
            if owner == "trainer" { [1, 0] } else { [1, 1] }
        );
        assert_eq!(f.publication_bytes()?, prepared_bytes);
        assert_eq!(
            f.host.original.version.authority.capacity()?.used_nonces,
            nonces
        );
        f.finish().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_readback_context_cannot_prepare_even_with_current_original_owners()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (trainer, evaluator, peers) = f.clients()?;
    let inputs = f.inputs()?;
    let before = f.publication_bytes()?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    assert!(matches!(
        prepare_original_circuit_evaluated_retention_v1(
            f.readback_context()?,
            trainer,
            evaluator,
            inputs,
        )
        .await,
        Err(PublicationError::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    assert_eq!(peers.finish()?, [0, 0]);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_lost_ack_recovers_exact_original_publication_and_baseline_c()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (trainer, evaluator, peers) = f.clients()?;
    let mut inputs = f.inputs()?;
    let (current, lose_ack) = f
        .host
        .original
        .version
        .reopen_current_with_ack_loss_hook()?;
    inputs.current = current;
    let prepared =
        prepare_original_circuit_evaluated_retention_v1(f.context()?, trainer, evaluator, inputs)
            .await?;
    let intent = prepared.intent_digest();
    let signed = f.host.original.version.sign(prepared.final_use_binding())?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    let original_evaluation = f.host.original_files()?;
    let original_training = f.host.original.predecessor_bytes()?;
    lose_ack();
    assert!(matches!(
        prepared.publish_original_retained_task(signed).await,
        Err(PublicationError::CommitUncertain(_))
    ));
    assert_eq!(peers.finish()?, [3, 3]);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    let committed = f.publication_bytes()?;
    f.host.recover()?;
    let (trainer, evaluator, peers) = f.clients()?;
    let task =
        recover_original_circuit_evaluated_retention_v1(trainer, evaluator, f.recovery(intent)?)
            .await?;
    assert_eq!(peers.finish()?, [2, 2]);
    assert_eq!(f.publication_bytes()?, committed);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    assert_eq!(f.host.original_files()?, original_evaluation);
    assert_eq!(f.host.original.predecessor_bytes()?, original_training);
    let mut c = f.start_c(task).await?;
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let publication = execute(&c, /*request_id*/ 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[path = "circuit_evaluated_current_positive_tests.rs"]
mod current_read_positive;
