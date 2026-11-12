//! Actual owner/UDS observation component checks. Root deployment, ordinary
//! main and an independently operated business Observer are separate tests.

use codex_hepta_agent_protocol::AGENTD_Q24_ORIGINAL_TASK_OBSERVATION_CAPABILITY;
use codex_hepta_agent_protocol::Q24OriginalTaskObservationV1;
use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn q24_live_task_observation_reads_the_signed_decision_without_creating_outcome()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "observe-real-original-task",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let before = (f.task_bytes()?, f.learning_bytes()?);
    let Status::AwaitingOutcome { decision } = f.producer.readback()? else {
        anyhow::bail!("original fixture must have only its real Decision");
    };
    let observed = control.client.original_q24_task_observation().await?;
    let payload = observed
        .decision_preimage_hex
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
        .collect::<anyhow::Result<Vec<_>>>()?;
    let signed = test_faults::retained_decision(&f.producer)?;
    f.ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("original ledger lock"))?
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Generator,
            &signed,
            &payload,
            signed.issued_at,
        )?;
    let LedgerEvent::AuthenticatedDecisionV2(original) = &decision.event else {
        anyhow::bail!("original authenticated Decision required");
    };
    assert_eq!(
        observed,
        Q24OriginalTaskObservationV1 {
            run_id: original.record_id.to_string(),
            source_publication_digest: f.publication.publication_digest().to_string(),
            source_history_digest: f.publication.history_digest().as_str().to_owned(),
            // Verified above against the actual original Generator signature,
            // not recomputed with a second implementation of the projection.
            decision_preimage_hex: observed.decision_preimage_hex.clone(),
            decision_sequence: decision.sequence.get(),
            decision_chain_digest: decision.chain_digest.to_string(),
            episode_id: f.config.episode_id.to_string(),
            selected_candidate_id: original.selected_candidate_id.to_string(),
            outcome_record_id: f.config.outcome_record_id.to_string(),
            outcome_id: f.config.outcome_id.to_string(),
            unit_profile_digest: f.config.unit_profile_digest.to_string(),
            expected_delay_profile_digest: f.config.expected_delay_profile_digest.to_string(),
            observer_principal_id: f.config.observer.principal.principal_id.to_string(),
            observer_controller_id: f.config.observer.controller_id.to_string(),
        }
    );
    assert_eq!(
        control.client.original_q24_task_observation().await?,
        observed
    );
    assert_eq!((f.task_bytes()?, f.learning_bytes()?), before);
    assert!(matches!(
        f.producer.readback()?,
        Status::AwaitingOutcome { .. }
    ));
    // Independent fixture input remains required. The query supplies only
    // exact support/profile data; it never supplies the business value.
    let outcome = f.outcome();
    let signature = f.sign_outcome(&outcome, /*lifetime*/ 600);
    control
        .client
        .submit_original_q24_terminal_outcome(&outcome, &signature)
        .await?;
    assert_eq!(
        control.client.original_q24_task_observation().await?,
        observed
    );
    control.stop().await?;
    f.session.stop().await
}

#[tokio::test]
async fn q24_live_task_observation_refuses_withdrawn_original_source() -> anyhow::Result<()> {
    let mut f = Fixture::new(
        "observe-withdrawn-original-task",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    control.client.original_q24_task_observation().await?;
    let ledger = f.learning_bytes()?;
    f.session
        .source
        .withdraw_for_dataset_test(&f.publication.original_record().snapshot.run_id)?;
    assert!(
        control
            .client
            .original_q24_task_observation()
            .await
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, ledger);
    control.stop().await?;
    f.session.stop().await
}

#[tokio::test]
async fn q24_live_task_observation_requires_installed_current_original_owner() -> anyhow::Result<()>
{
    for automatic in [false, true] {
        let mut f = Fixture::new("observe-owner-or-fence", /*lifetime*/ 600, automatic).await?;
        let control = Control::open(&mut f).await?;
        assert_eq!(
            control
                .client
                .capabilities()
                .await?
                .capabilities
                .iter()
                .any(|capability| {
                    capability.id == AGENTD_Q24_ORIGINAL_TASK_OBSERVATION_CAPABILITY
                }),
            automatic
        );
        if automatic {
            control.client.original_q24_task_observation().await?;
            f.session.runtime.state.mark_fenced();
        }
        let before = (f.task_bytes()?, f.learning_bytes()?);
        assert!(
            control
                .client
                .original_q24_task_observation()
                .await
                .is_err()
        );
        assert_eq!((f.task_bytes()?, f.learning_bytes()?), before);
        control.stop().await?;
        f.session.stop().await?;
    }
    Ok(())
}
