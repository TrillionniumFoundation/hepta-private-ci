//! Retained-model publication mechanisms with actual ordinary A/C and original
//! version, artifact and FinalUse files. Training signatures remain explicit
//! fixture metadata; this is neither native learning nor a deployed closed loop.

use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCircuitRetainedPublicationContextV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;
use crate::learning_iteration_evidence_client::selection_command_test_support::training_fixture_result;
use crate::prepare_original_circuit_retained_publication_v1;
use crate::recover_original_circuit_retained_publication_v1;

#[path = "circuit_learning_retained_publication_support_tests.rs"]
mod retained_support;
use retained_support::RetainedPublicationFixture;
use retained_support::finish_trainer;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_uses_original_selection_and_real_distinct_task_c()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    let prepared =
        prepare_original_circuit_retained_publication_v1(context, trainer, f.inputs()?).await?;
    assert_eq!(
        prepared.final_use_binding().destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let signed = f.version.sign(prepared.final_use_binding())?;
    let task = prepared.publish_original_retained_task(signed).await?;
    assert_eq!(finish_trainer(peer)?, 4);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces + 1);
    assert_ne!(f.source_a.scope.run_id, task.source().scope.run_id);
    assert_ne!(f.source_a.observation, task.source().observation);
    assert_ne!(f.config_a.task_digest, f.config_c.task_digest);
    let mut c = f.start_c(task).await?;
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let selection = c.cell.read_learning_selection(&f.metadata.decision)?;
    assert!(
        matches!(selection, LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if candidate_bundle == f.bundle.digest()?)
    );
    let publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_eq!(actual.representation.drive_q24, vec![Q / 4, Q, 0, 0, 0]);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    c.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_refuses_changed_full_training_signature_before_prepare()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let mut changed = f.metadata.training_signature.clone();
    changed.expires_at += 1;
    changed.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&changed.signing_bytes())
        .to_bytes();
    let (trainer, peer) = f.trainer(changed)?;
    let inputs = f.inputs()?;
    let before = f.publication_bytes()?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    assert!(matches!(
        prepare_original_circuit_retained_publication_v1(context, trainer, inputs).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "original complete Training receipt and signature changed"
        ))
    ));
    assert_eq!(finish_trainer(peer)?, 1);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_rejects_same_content_even_with_a_new_run_and_task_digest()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let mut inputs = f.inputs()?;
    inputs.source.observation = f.source_a.observation.clone();
    inputs.target.config.task_digest =
        crate::circuit_feature_task_digest_v1(&inputs.definition, &inputs.source)?.into_array();
    assert_ne!(inputs.source.scope.run_id, f.source_a.scope.run_id);
    assert_ne!(inputs.target.config.task_digest, f.config_a.task_digest);
    let before = f.publication_bytes()?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    assert!(matches!(
        prepare_original_circuit_retained_publication_v1(context, trainer, inputs).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "exact drained A and distinct retained-model C"
        ))
    ));
    assert_eq!(finish_trainer(peer)?, 1);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_never_converts_candidate_training_into_no_update()
-> anyhow::Result<()> {
    let f = RetainedPublicationFixture::ready().await?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(f.dataset())?;
    let source_bundle = f.bundle.digest()?;
    let mut candidate = f.bundle.clone();
    candidate.artifact_id = StableId::new("explicit-retained-negative-candidate")?;
    candidate.generation = candidate.generation.next()?;
    candidate.components.cell_adapter = Some(d("explicit-retained-negative-adapter"));
    let LearningIterationObservationV1::TrainingNoUpdateV2(original) =
        &f.metadata.training.observation
    else {
        anyhow::bail!("strict fixture NoUpdate");
    };
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle,
        dataset: original.dataset,
        update_rule: original.update_rule,
        evaluation_profile: coordinator.snapshot().request.evaluation_profile,
    });
    candidate.rollback_predecessor = Some(source_bundle);
    let training = receipt(
        &coordinator,
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 64,
        },
        now()?,
        "explicit-candidate-negative-evidence",
    );
    let evidence = signed(
        &training,
        &f.metadata.verifier,
        LearningEvidenceRoleV1::Generator,
        &SigningKey::from_bytes(&[101; 32]),
        "explicit-candidate-negative-generator",
    )?;
    coordinator.record(training.clone(), training.observed_unix_seconds)?;
    let before = f.version.bytes("current.json")?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    let (dataset, opaque) = training_fixture_result(
        coordinator.snapshot().clone(),
        f.metadata.scope.clone(),
        f.metadata.verifier.clone(),
        evidence,
    )
    .await?;
    assert!(matches!(
        OriginalCircuitRetainedPublicationContextV1::from_original_training(
            dataset,
            f.metadata.scope.clone(),
            f.metadata.verifier.clone(),
            &opaque,
        ),
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "strict original TrainingNoUpdate publication profile"
        ))
    ));
    assert_eq!(f.version.bytes("current.json")?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_refuses_another_final_use_purpose_and_only_reads_pending()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let prepared =
        prepare_original_circuit_retained_publication_v1(context, trainer, f.inputs()?).await?;
    let intent = prepared.intent_digest();
    let mut other = prepared.final_use_binding().clone();
    other.destination_id = "runtime.learning.resident-admission.v3".into();
    let wrong = f.version.sign(&other)?;
    let before = f.publication_bytes()?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    assert!(matches!(
        prepared.publish_original_retained_task(wrong).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::CommitUncertain(
            _
        ))
    ));
    assert_eq!(finish_trainer(peer)?, 3);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    assert!(
        matches!(recover_original_circuit_retained_publication_v1(trainer, f.recovery(intent)?).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::Owner(crate::AgentdError::Invalid(message)))
        if message.contains("remains pending; no redispatch"))
    );
    assert_eq!(finish_trainer(peer)?, 1);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_refuses_actual_artifact_withdrawal_before_final_use()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let prepared =
        prepare_original_circuit_retained_publication_v1(context, trainer, f.inputs()?).await?;
    let signed = f.version.sign(prepared.final_use_binding())?;
    let before = f.publication_bytes()?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    f.version.withdraw()?;
    assert!(matches!(
        prepared.publish_original_retained_task(signed).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::CommitUncertain(
            _
        ))
    ));
    assert_eq!(finish_trainer(peer)?, 3);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_publication_lost_ack_recovers_original_files_without_another_grant()
-> anyhow::Result<()> {
    let mut f = RetainedPublicationFixture::ready().await?;
    let context = f.context().await?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let mut inputs = f.inputs()?;
    let (current, lose_ack) = f.version.reopen_current_with_ack_loss_hook()?;
    inputs.current = current;
    let prepared =
        prepare_original_circuit_retained_publication_v1(context, trainer, inputs).await?;
    let intent = prepared.intent_digest();
    let signed = f.version.sign(prepared.final_use_binding())?;
    let nonces = f.version.authority.capacity()?.used_nonces;
    lose_ack();
    assert!(matches!(
        prepared.publish_original_retained_task(signed).await,
        Err(OriginalCircuitRetainedPublicationErrorV1::CommitUncertain(
            _
        ))
    ));
    assert_eq!(finish_trainer(peer)?, 3);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces + 1);
    let committed = f.publication_bytes()?;
    let (trainer, peer) = f.trainer(f.metadata.training_signature.clone())?;
    let task =
        recover_original_circuit_retained_publication_v1(trainer, f.recovery(intent)?).await?;
    assert_eq!(finish_trainer(peer)?, 2);
    assert_eq!(f.publication_bytes()?, committed);
    assert_eq!(f.version.authority.capacity()?.used_nonces, nonces + 1);
    let mut c = f.start_c(task).await?;
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let publication = execute(&c, 1).await?;
    assert_eq!(
        read_receipt(&c, &f.definition, &publication)?.bundle_digest,
        f.bundle.digest()?
    );
    c.stop().await?;
    Ok(())
}
