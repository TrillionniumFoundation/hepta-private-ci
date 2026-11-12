//! Actual original Evaluator host mechanisms with explicit synthetic custody.
//! The underlying real B and nonempty retention both evaluate as Ineligible.
//! These tests neither deploy B measurement nor authorize version adoption.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use crate::OriginalCellEvaluationCommandErrorV1 as CommandError;

#[path = "circuit_original_evaluation_host_support_tests.rs"]
mod fixture;
use fixture::HostFixture;
use fixture::finish;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_host_reads_actual_panel_and_cold_original_signature() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let upstream = fixture.upstream_files()?;
    let missing = fixture.original_files()?;
    let (client, peer) = fixture.commands(/*readback_only*/ false, /*expected*/ None, "original")?;
    assert!(matches!(client.readback().await, Err(CommandError::Missing)));
    assert_eq!(fixture.original_files()?, missing);
    assert!(!fixture.host.as_ref().unwrap().fixture_dispatch_consumed());
    let evaluation = client.execute_evaluation().await?;
    assert_eq!(evaluation.snapshot().receipts.len(), 4);
    assert_eq!(evaluation.training_attestation(), &fixture.original.config.training_evidence);
    assert_eq!(evaluation.authority(), AuthorityPosture::DENY_ALL);
    assert!(matches!(&evaluation.receipt().observation,
        LearningIterationObservationV1::Evaluation { .. }));
    assert_eq!(evaluation.attestation().role, LearningEvidenceRoleV1::Evaluator);
    assert_ne!(fixture.original_files()?, missing);
    let completed = fixture.original_files()?;
    assert_eq!(client.readback().await?, evaluation);
    assert!(matches!(client.execute_evaluation().await, Err(CommandError::ReadbackRequired)));
    assert_eq!(finish(client, peer)?, 3);
    assert_eq!(fixture.upstream_files()?, upstream);
    fixture.host.as_ref().unwrap().fixture_expired_original(&evaluation)?;
    fixture.recover()?;
    assert_eq!(fixture.original_files()?, completed);
    // Even a fixture client asking Execute cannot reset a genuinely recovered
    // original host. Its server brand is independent from client-provided mode.
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, Some(evaluation.clone()), "original",
    )?;
    assert!(matches!(client.execute_evaluation().await, Err(CommandError::ReadbackRequired)));
    assert_eq!(client.readback().await?, evaluation);
    assert_eq!(finish(client, peer)?, 2);
    assert_eq!(fixture.original_files()?, completed);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert_eq!(fixture.finish().await?, [34, 30]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_host_refuses_renewed_or_regressed_completed_evidence() -> anyhow::Result<()> {
    let fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let (client, peer) = fixture.commands(/*readback_only*/ false, /*expected*/ None, "original")?;
    let original = client.execute_evaluation().await?;
    assert_eq!(finish(client, peer)?, 1);
    let completed = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    for fault in ["after-missing", "after-pending", "after-renewal"] {
        let (client, peer) = fixture.commands(/*readback_only*/ true, /*expected*/ None, fault)?;
        assert_eq!(client.readback().await?, original);
        let rejected = client.readback().await;
        if fault == "after-renewal" {
            assert!(matches!(rejected, Err(CommandError::Binding(
                "unchanged full original Evaluation signature"
            ))));
        } else {
            assert!(matches!(rejected, Err(CommandError::CommitUncertain)));
        }
        assert!(matches!(client.readback().await, Err(CommandError::Unavailable)));
        assert_eq!(finish(client, peer)?, 2);
        assert_eq!(fixture.original_files()?, completed);
        assert_eq!(fixture.upstream_files()?, upstream);
    }
    for fault in ["cold-missing", "cold-pending"] {
        let (client, peer) = fixture.commands(
            /*readback_only*/ true, Some(original.clone()), fault,
        )?;
        assert!(matches!(client.readback().await, Err(CommandError::CommitUncertain)));
        assert!(matches!(client.readback().await, Err(CommandError::Unavailable)));
        assert_eq!(finish(client, peer)?, 1);
        assert_eq!(fixture.original_files()?, completed);
    }
    let counts = fixture.finish().await?;
    assert!(counts.into_iter().all(|count| count > 2));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_host_pending_ack_loss_and_cancel_never_repeat_effect() -> anyhow::Result<()> {
    let mut pending = HostFixture::new(/*pending_claim*/ true).await?;
    let claimed = pending.original_files()?;
    let (client, peer) = pending.commands(/*readback_only*/ false, /*expected*/ None, "original")?;
    assert!(matches!(client.execute_evaluation().await, Err(CommandError::ReadbackRequired)));
    assert!(matches!(client.readback().await, Err(CommandError::Pending)));
    assert_eq!(finish(client, peer)?, 2);
    pending.recover()?;
    let (client, peer) = pending.commands(/*readback_only*/ true, /*expected*/ None, "original")?;
    assert!(matches!(client.readback().await, Err(CommandError::Pending)));
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(pending.original_files()?, claimed);
    let counts = pending.finish().await?;
    assert_eq!(counts, [10, 10]);

    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let empty = fixture.original_files()?;
    let (wrong, peer) = fixture.commands(/*readback_only*/ false, /*expected*/ None, "wrong-context")?;
    assert!(matches!(wrong.execute_evaluation().await, Err(CommandError::CommitUncertain)));
    assert!(finish(wrong, peer).is_err());
    assert!(!fixture.host.as_ref().unwrap().fixture_dispatch_consumed());
    fixture.host.as_ref().unwrap().fixture_cancel_queued().await?;
    assert!(!fixture.host.as_ref().unwrap().fixture_dispatch_consumed());
    assert_eq!(fixture.original_files()?, empty);
    let (lost, peer) = fixture.commands(/*readback_only*/ false, /*expected*/ None, "lose-ack")?;
    assert!(matches!(lost.execute_evaluation().await, Err(CommandError::CommitUncertain)));
    assert!(matches!(lost.execute_evaluation().await, Err(CommandError::Unavailable)));
    assert_eq!(finish(lost, peer)?, 1);
    let completed = fixture.original_files()?;
    assert_ne!(completed, empty);
    let (readonly, peer) = fixture.commands(/*readback_only*/ true, /*expected*/ None, "original")?;
    let original = readonly.readback().await?;
    assert_eq!(finish(readonly, peer)?, 1);
    assert_eq!(fixture.original_files()?, completed);
    // Withdrawal of the actual independent B Outcome invalidates this host,
    // including future readback of its already-created real signature.
    fixture.retention_b.withdraw_target()?;
    let (readonly, peer) = fixture.commands(
        /*readback_only*/ true, Some(original), "original",
    )?;
    assert!(matches!(readonly.readback().await, Err(CommandError::PredecessorUnavailable)));
    assert_eq!(finish(readonly, peer)?, 1);
    assert_eq!(fixture.original_files()?, completed);
    let (readonly, peer) = fixture.commands(/*readback_only*/ true, /*expected*/ None, "original")?;
    assert!(matches!(readonly.readback().await, Err(CommandError::CommitUncertain)));
    assert_eq!(finish(readonly, peer)?, 1);
    assert_eq!(fixture.original_files()?, completed);
    let counts = fixture.finish().await?;
    assert!(counts.into_iter().all(|count| count >= 2));
    Ok(())
}

impl crate::OriginalCellEvaluationHostV1 {
    /// Invoked only by the protected Root test entry, not the ordinary suite.
    pub(crate) async fn fixture_resident_evaluation_checkpoint() -> anyhow::Result<()> {
        let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
        let (client, peer) = fixture.commands(
            /*readback_only*/ false, /*expected*/ None, "original",
        )?;
        let evaluation = client.execute_evaluation().await?;
        assert_eq!(finish(client, peer)?, 1);
        let original_files = fixture.original_files()?;
        let upstream = fixture.upstream_files()?;
        let mut signatures = fixture.original.material_evidence.to_vec();
        signatures.push(fixture.original.config.training_evidence.clone());
        signatures.push(evaluation.attestation().clone());
        let credentials = &fixture.original.credentials;
        crate::RootResidentLearningProfileV3::fixture_original_evaluation_checkpoint(
            fixture.original.initial.clone(),
            fixture.config.scope.clone(),
            fixture.config.signing.verifier.clone(),
            &evaluation,
            signatures,
            fixture.host.as_ref().expect("original Evaluator"),
            [
                credentials.experience.clone(), credentials.dataset.clone(),
                credentials.generator.clone(), credentials.evaluator.clone(),
            ],
        ).await?;
        assert_eq!(fixture.original_files()?, original_files);
        assert_eq!(fixture.upstream_files()?, upstream);
        fixture.recover()?;
        let (client, peer) = fixture.commands(
            /*readback_only*/ false, Some(evaluation.clone()), "original",
        )?;
        assert!(matches!(client.execute_evaluation().await, Err(CommandError::ReadbackRequired)));
        assert_eq!(client.readback().await?, evaluation);
        assert_eq!(finish(client, peer)?, 2);
        assert_eq!(fixture.original_files()?, original_files);
        assert_eq!(fixture.upstream_files()?, upstream);
        let counts = fixture.finish().await?;
        assert!(counts.into_iter().all(|count| count > 2));
        Ok(())
    }
}

#[path = "circuit_original_evaluation_model_material_tests.rs"]
mod model_material;
