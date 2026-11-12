//! Actual original Evaluator evidence at the protected Root checkpoint.
//! Test-only Root grants and role keys are explicit mechanism custody. The
//! real B/retention panel is Ineligible; this never grants Model or adoption.
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use tokio_util::sync::CancellationToken;

use super::super::super::authentication::verify_attestations;
use super::RootResidentLearningProfileV3;
use super::support::ResidentRootFixture;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellEvaluationCommandErrorV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationHostV1;

fn current_time() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

impl RootResidentLearningProfileV3 {
    /// All successful receipts and signatures are original completed bytes.
    pub(crate) async fn fixture_original_evaluation_checkpoint(
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
        signatures: Vec<SignedLearningEvidenceV1>,
        host: &Arc<OriginalCellEvaluationHostV1>,
        original_signers: [TrustedLearningSignerV1; 4],
    ) -> anyhow::Result<()> {
        assert_eq!(evaluation.snapshot().receipts.len(), 4);
        assert_eq!(signatures.len(), 4);
        assert_eq!(&signatures[2], evaluation.training_attestation());
        assert_eq!(&signatures[3], evaluation.attestation());
        let mut prefix = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        let mut cuts = vec![initial.clone()];
        for receipt in &evaluation.snapshot().receipts {
            prefix.record(receipt.clone(), receipt.observed_unix_seconds)?;
            cuts.push(prefix.snapshot().clone());
        }
        assert_eq!(cuts[4], *evaluation.snapshot());
        let training = &cuts[3];
        assert_eq!(
            LearningIterationCoordinatorV1::from_snapshot(training.clone())?.next_stage(),
            Some(LearningIterationStageV1::Evaluation)
        );

        // Real completed remote E exists while Root is still pending at T.
        // A future four-cut cannot replace the active three-cut dispatch.
        let pending = ResidentRootFixture::for_original_evaluation_window(
            initial.clone(),
            scope.clone(),
            &verifier,
        )?;
        verify_attestations(
            &pending.profile,
            &verifier,
            evaluation.snapshot(),
            &signatures,
            current_time()?,
        )?;
        let original = &pending
            .registration
            .as_ref()
            .expect("original Root registration")
            .owner;
        let cancellation = CancellationToken::new();
        let continuation = original
            .admit(&cancellation)
            .await?
            .ok_or_else(|| anyhow::anyhow!("actual vacant Root admission"))?;
        for index in 0..3 {
            continuation
                .gate
                .begin(
                    &cuts[index],
                    cuts[index + 1].receipts[index].observation.stage(),
                )
                .await?;
            continuation
                .gate
                .checkpoint(&cuts[index], cuts[index + 1].clone())
                .await?;
        }
        continuation
            .gate
            .begin(training, LearningIterationStageV1::Evaluation)
            .await?;
        continuation.gate.require_current(training, &scope).await?;
        let before = original.read(&cancellation).await?.0;
        assert_eq!(before.snapshot.as_ref(), Some(training));
        assert!(before.dispatch_pending);
        assert!(
            continuation
                .gate
                .require_current(evaluation.snapshot(), &scope)
                .await
                .is_err()
        );
        assert!(
            continuation
                .gate
                .training_cancellation()
                .load(Ordering::Acquire)
        );
        assert!(
            continuation
                .gate
                .require_current(training, &scope)
                .await
                .is_err()
        );
        assert!(
            continuation
                .gate
                .checkpoint(training, evaluation.snapshot().clone())
                .await
                .is_err()
        );
        let after = original.read(&cancellation).await?.0;
        assert_eq!(after.snapshot, before.snapshot);
        assert!(after.dispatch_pending);
        assert!(original.admit(&cancellation).await?.is_none());

        // A fenced Root effect gate does not turn original E into Missing.
        // Readback still authenticates all original owner CURRENT and windows.
        let (client, peer) = host.fixture_commands(
            /*readback_only*/ false,
            Some(evaluation.clone()),
            "original",
        )?;
        assert_eq!(client.readback().await?, *evaluation);
        assert!(matches!(
            client.execute_evaluation().await,
            Err(OriginalCellEvaluationCommandErrorV1::ReadbackRequired)
        ));
        drop(client);
        assert_eq!(peer.join().expect("original E after Root fence")?, 2);
        drop(continuation);
        drop(pending);

        // A separate explicit Root fixture authenticates the original full E
        // before committing it. Cold Root recovery cannot dispatch any stage.
        let mut accepted = ResidentRootFixture::for_original_evaluation_window(
            initial.clone(),
            scope.clone(),
            &verifier,
        )?;
        {
            let original = &accepted
                .registration
                .as_ref()
                .expect("original Root registration")
                .owner;
            let continuation = original
                .admit(&cancellation)
                .await?
                .ok_or_else(|| anyhow::anyhow!("actual vacant Root admission"))?;
            for index in 0..4 {
                verify_attestations(
                    &accepted.profile,
                    &verifier,
                    &cuts[index + 1],
                    &signatures[..index + 1],
                    current_time()?,
                )?;
                continuation
                    .gate
                    .begin(
                        &cuts[index],
                        cuts[index + 1].receipts[index].observation.stage(),
                    )
                    .await?;
                continuation
                    .gate
                    .require_current(&cuts[index], &scope)
                    .await?;
                continuation
                    .gate
                    .checkpoint(&cuts[index], cuts[index + 1].clone())
                    .await?;
            }
            let saved = original.read(&cancellation).await?.0;
            assert_eq!(saved.snapshot.as_ref(), Some(evaluation.snapshot()));
            assert!(!saved.dispatch_pending);
            drop(continuation);
        }
        accepted.recover()?;
        {
            let cold = &accepted
                .registration
                .as_ref()
                .expect("original readback registration")
                .owner;
            assert!(cold.authority.readonly());
            let saved = cold.read(&cancellation).await?.0;
            assert_eq!(saved.snapshot.as_ref(), Some(evaluation.snapshot()));
            assert!(!saved.dispatch_pending);
            assert!(cold.admit(&cancellation).await.is_err());
            verify_attestations(
                &accepted.profile,
                &verifier,
                evaluation.snapshot(),
                &signatures,
                current_time()?,
            )?;
        }

        // Cryptographically signed wrong-role and Trainer identity attempts
        // cannot replace the original Evaluator payload or principal.
        let mut wrong_role = signatures.clone();
        wrong_role[3].role = LearningEvidenceRoleV1::Observer;
        wrong_role[3].signature = SigningKey::from_bytes(&[42; 32])
            .sign(&wrong_role[3].signing_bytes())
            .to_bytes();
        assert!(matches!(
            verify_attestations(
                &accepted.profile,
                &verifier,
                evaluation.snapshot(),
                &wrong_role,
                current_time()?
            ),
            Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::RoleMismatch
            ))
        ));
        let mut trainer_impersonation = signatures.clone();
        trainer_impersonation[3].principal_id = training.owners.trainer.clone();
        trainer_impersonation[3].signature = SigningKey::from_bytes(&[41; 32])
            .sign(&trainer_impersonation[3].signing_bytes())
            .to_bytes();
        assert!(matches!(
            verify_attestations(
                &accepted.profile,
                &verifier,
                evaluation.snapshot(),
                &trainer_impersonation,
                current_time()?
            ),
            Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::RoleMismatch
            ))
        ));
        reject_shared_controller(
            &initial,
            evaluation.snapshot(),
            &signatures,
            original_signers,
        )
        .await?;
        Ok(())
    }
}

/// Negative metadata only. Reauthenticated observations under deliberately
/// co-controlled registered roles never enter the original host, its journals
/// or a successful checkpoint. A distinct role name cannot prove independence.
async fn reject_shared_controller(
    initial: &LearningIterationSnapshotV1,
    original: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    mut signers: [TrustedLearningSignerV1; 4],
) -> anyhow::Result<()> {
    assert_ne!(signers[2].controller_id, signers[3].controller_id);
    signers[3].controller_id = signers[2].controller_id.clone();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: signatures[0].scope_digest,
        objective_digest: signatures[0].objective_digest,
        authority_epoch: signatures[0].authority_epoch,
        signers: signers.to_vec(),
    })?;
    let mut owners = initial.owners.clone();
    owners.evidence_trust_digest = verifier.trust_digest();
    let mut rebuilt = LearningIterationCoordinatorV1::new(initial.request.clone(), owners)?;
    let altered_initial = rebuilt.snapshot().clone();
    let mut changed = Vec::new();
    let seeds = [44_u8, 45, 41, 42];
    for (index, receipt) in original.receipts.iter().enumerate() {
        let mut receipt = receipt.clone();
        receipt.predecessor = rebuilt.snapshot().head_digest;
        let mut evidence = signatures[index].clone();
        evidence.trust_digest = verifier.trust_digest();
        evidence.payload_digest =
            Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(&receipt)?);
        evidence.signature = SigningKey::from_bytes(&[seeds[index]; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        verifier.verify(
            evidence.role,
            &evidence,
            &learning_iteration_receipt_signing_bytes_v1(&receipt)?,
            current_time()?,
        )?;
        rebuilt.record(receipt.clone(), receipt.observed_unix_seconds)?;
        changed.push(evidence);
    }
    let update_rule = rebuilt
        .candidate()
        .and_then(|candidate| candidate.training_lineage.as_ref())
        .ok_or_else(|| anyhow::anyhow!("actual Candidate lineage"))?
        .update_rule;
    let scope = FrozenLearningScopeV2::freeze(
        &altered_initial.request,
        &altered_initial.owners,
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    let fixture =
        ResidentRootFixture::for_original_evaluation_window(altered_initial, scope, &verifier)?;
    assert!(matches!(
        verify_attestations(
            &fixture.profile,
            &verifier,
            rebuilt.snapshot(),
            &changed,
            current_time()?
        ),
        Err(LearningIterationRuntimeErrorV1::Evidence(
            SignedEvidenceError::ControllerCollision
        ))
    ));
    assert!(
        fixture
            .registration
            .as_ref()
            .expect("negative registration")
            .owner
            .read(&CancellationToken::new())
            .await?
            .0
            .snapshot
            .is_none()
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_original_evaluation_requires_actual_checkpoint_and_independent_signature()
-> anyhow::Result<()> {
    OriginalCellEvaluationHostV1::fixture_resident_evaluation_checkpoint().await
}
