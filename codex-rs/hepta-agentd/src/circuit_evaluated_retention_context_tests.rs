//! Use the actual B/retention host's complete negative comparison. The original
//! host fixture has synthetic credentials and times; this is no deployment or
//! ordinary-loop qualification. No publication capability is manufactured.

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::HostFixture;
use super::finish;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitRetainedPublicationContextV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;
use crate::learning_iteration_evidence_client::selection_command_test_support::training_fixture_result;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_preserves_actual_ineligible_candidate_and_four_stage_cut()
-> anyhow::Result<()> {
    let fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    let evaluation = client.execute_evaluation().await?;
    assert!(matches!(
        evaluation.receipt().observation,
        LearningIterationObservationV1::Evaluation {
            disposition: LearningEvaluationDispositionV1::NoUpdate,
            ..
        }
    ));
    let (dataset, training) = training_fixture_result(
        fixture.config.training.clone(),
        fixture.config.scope.clone(),
        fixture.config.signing.verifier.clone(),
        evaluation.training_attestation().clone(),
    )
    .await?;
    let original_bytes = fixture.original_files()?;
    let upstream_bytes = fixture.upstream_files()?;
    let context = OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
        fixture.config.scope.clone(),
        fixture.config.signing.verifier.clone(),
        &training,
        &evaluation,
    )?;
    assert_eq!(context.snapshot(), evaluation.snapshot());
    assert!(context.snapshot().training_no_update_v2().is_none());
    assert!(matches!(
        OriginalCircuitRetainedPublicationContextV1::from_original_training(
            dataset,
            fixture.config.scope.clone(),
            fixture.config.signing.verifier.clone(),
            &training,
        ),
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "strict original TrainingNoUpdate publication profile"
        ))
    ));
    let cold = OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
        fixture.config.scope.clone(),
        fixture.config.signing.verifier.clone(),
        &training,
        &evaluation,
    )?;
    crate::circuit_feature_current::check_evaluated_profiles(
        context,
        cold,
        evaluation.attestation().expires_at,
    )?;
    // The fixture's actual changed-model C cannot satisfy retained baseline CURRENT.
    let fresh = OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
        fixture.config.scope.clone(),
        fixture.config.signing.verifier.clone(),
        &training,
        &evaluation,
    )?;
    assert!(matches!(
        crate::OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
            fixture.original.session.cell.clone(),
            fixture.original.session.source.as_ref().clone(),
            fixture.original.session.runtime.identity.clone(),
            crate::OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(fresh)?,
        ),
        Err(crate::OriginalCircuitLearningReadErrorV1::Owner(crate::AgentdError::Invalid(detail)))
            if detail == "learning decision differs from the original published task owner"
    ));
    assert_eq!(fixture.original_files()?, original_bytes);
    assert_eq!(fixture.upstream_files()?, upstream_bytes);
    assert_eq!(finish(client, peer)?, 1);
    fixture.finish().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retention_refuses_validly_renewed_training_signature() -> anyhow::Result<()> {
    let fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    let evaluation = client.execute_evaluation().await?;
    let mut renewed = evaluation.training_attestation().clone();
    renewed.expires_at -= 1;
    renewed.signature = SigningKey::from_bytes(&[41; 32])
        .sign(&renewed.signing_bytes())
        .to_bytes();
    let (_, training) = training_fixture_result(
        fixture.config.training.clone(),
        fixture.config.scope.clone(),
        fixture.config.signing.verifier.clone(),
        renewed,
    )
    .await?;
    let before = fixture.original_files()?;
    assert!(matches!(
        OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
            fixture.config.scope.clone(),
            fixture.config.signing.verifier.clone(),
            &training,
            &evaluation,
        ),
        Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "original evaluated NoUpdate retention profile"
        ))
    ));
    assert_eq!(fixture.original_files()?, before);
    assert_eq!(finish(client, peer)?, 1);
    fixture.finish().await?;
    Ok(())
}
