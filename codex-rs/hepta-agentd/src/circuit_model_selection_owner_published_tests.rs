//! Positive original-owner behavior over real SourceBound optimization,
//! independent native evaluation and version/FinalUse publication. Synthetic
//! credentials and cohorts are explicit fixtures, not ordinary adoption proof.
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::LearningOriginalOwnerErrorV1;

#[path = "circuit_model_selection_owner_support_tests.rs"]
mod original;
use original::PositiveFixture;
use original::SelectionError;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_attests_and_recovers_exact_adoption() -> anyhow::Result<()>
{
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let predecessors = f.predecessor_bytes()?;
    let mut owner = f.create_owner()?;
    let peers = f.peers(f.config.training_evidence.clone())?;
    let original = f.attest(&mut owner, &decision, &peers)?;
    assert_eq!(original.1.role, LearningEvidenceRoleV1::Selector);
    assert!(matches!(&original.0.observation,
        LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if *candidate_bundle == f.candidate.digest()?));
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(decision)?;
    coordinator.record(original.0.clone(), original.0.observed_unix_seconds)?;
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::NextUse)
    );
    let signed_bytes = f.selector_bytes()?;

    // C is a fresh ordinary session with a different input. Its actual native
    // Prediction row consumes the changed trained bytes; Drive remains baseline.
    assert_eq!(
        f.session
            .cell
            .snapshot(&f.session.retirement.source().scope)?
            .revision,
        0
    );
    let publication = execute(&f.session, 1).await?;
    let receipt = read_receipt(&f.session, &f.definition, &publication)?;
    assert_eq!(receipt.representation.drive_q24, vec![Q / 4, Q, 0, 0, 0]);
    assert_eq!(
        receipt.representation.prediction_q24,
        vec![79 * Q / 128, Q, 0, 0, 0]
    );
    assert_eq!(receipt.bundle_digest, f.candidate.digest()?);
    assert_ne!(receipt.scope.run_id, f.previous.input().scope.run_id);
    assert_ne!(
        publication.input().observation,
        f.previous.input().observation
    );
    let next_use = f.session.cell.read_learning_next_use(
        &coordinator,
        f.session.source.as_ref(),
        &f.session.runtime.identity,
    )?;
    assert!(matches!(next_use, LearningIterationObservationV1::NextUse {
        candidate_bundle, checkpoint_digest, state_cutover_receipt, ..
    } if candidate_bundle == receipt.bundle_digest
        && checkpoint_digest == receipt.checkpoint_after
        && !state_cutover_receipt.is_zero()));

    let complete_selection = coordinator.snapshot().clone();
    assert_eq!(
        f.readback(&mut owner, &complete_selection, &peers)?,
        original
    );
    drop(owner);
    let mut recovered = f.recover_config(f.config.clone())?;
    assert_eq!(
        f.readback(&mut recovered, &complete_selection, &peers)?,
        original
    );
    assert_eq!(f.selector_bytes()?, signed_bytes);
    assert_eq!(f.predecessor_bytes()?, predecessors);
    drop(recovered);
    assert_eq!(peers.finish()?, [4, 4]);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_refuses_withdrawn_training_source() -> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let mut owner = f.create_owner()?;
    let before = f.selector_bytes()?;
    let peers = f.peers(f.config.training_evidence.clone())?;
    // A real signed Unlearning append withdraws the original frozen Decision
    // and advances the still-held original Ledger and independent witness.
    f.withdraw_original_dataset()?;
    assert!(matches!(
        f.attest(&mut owner, &decision, &peers),
        Err(SelectionError::Model(
            crate::OriginalCellQ24TrainingStageErrorV1::Training(
                crate::CellQ24TrainingOwnerErrorV1::Source(_)
            )
        ))
    ));
    assert!(matches!(
        f.readback(&mut owner, &decision, &peers),
        Err(SelectionError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(f.selector_bytes()?, before);
    drop(owner);
    assert_eq!(peers.finish()?, [0, 0]);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_refuses_withdrawn_version_publication()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let mut owner = f.create_owner()?;
    let before = f.selector_bytes()?;
    let peers = f.peers(f.config.training_evidence.clone())?;
    f.version.withdraw()?;
    assert!(matches!(
        f.attest(&mut owner, &decision, &peers),
        Err(SelectionError::Observation(_))
    ));
    assert!(matches!(
        f.readback(&mut owner, &decision, &peers),
        Err(SelectionError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(f.selector_bytes()?, before);
    drop(owner);
    assert_eq!(peers.finish()?, [0, 0]);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_refuses_valid_predecessor_resigning() -> anyhow::Result<()>
{
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let mut owner = f.create_owner()?;
    let empty = f.selector_bytes()?;
    let mut renewed = f.config.training_evidence.clone();
    // Same actor, payload and issued_at; this test custodian legitimately
    // extends expiry and signs again. It is still not the original signature.
    renewed.expires_at += 1;
    renewed.signature = SigningKey::from_bytes(&[41; 32])
        .sign(&renewed.signing_bytes())
        .to_bytes();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs();
    f.config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &renewed,
        &learning_iteration_receipt_signing_bytes_v1(&decision.receipts[2])?,
        now,
    )?;
    let changed = f.peers(renewed.clone())?;
    assert!(matches!(
        f.attest(&mut owner, &decision, &changed),
        Err(SelectionError::Owner(
            LearningOriginalOwnerErrorV1::Binding("changed original Model predecessor signatures")
        ))
    ));
    assert_eq!(f.selector_bytes()?, empty);
    assert_eq!(changed.finish()?, [1, 1]);

    let original_peers = f.peers(f.config.training_evidence.clone())?;
    let completed = f.attest(&mut owner, &decision, &original_peers)?;
    let original_bytes = f.selector_bytes()?;
    drop(owner);
    let mut changed_config = f.config.clone();
    changed_config.training_evidence = renewed;
    assert!(f.recover_config(changed_config).is_err());
    assert_eq!(f.selector_bytes()?, original_bytes);
    let mut recovered = f.recover_config(f.config.clone())?;
    assert_eq!(
        f.readback(&mut recovered, &decision, &original_peers)?,
        completed
    );
    assert_eq!(f.selector_bytes()?, original_bytes);
    drop(recovered);
    assert_eq!(original_peers.finish()?, [3, 3]);
    f.finish().await
}

struct LostClaimAck(FileAnchorWitnessStore);
impl AnchorWitnessStore for LostClaimAck {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.0.compare_and_swap(expected, next)?;
        if next.sequence == 2 {
            return Err(WitnessStoreError::Indeterminate);
        }
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_pending_claim_survives_recovery() -> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let mut owner = f.create_with_witness(LostClaimAck(f.selector_witness(true)?))?;
    let empty = f.selector_bytes()?;
    let predecessors = f.predecessor_bytes()?;
    let peers = f.peers(f.config.training_evidence.clone())?;
    assert!(matches!(
        f.attest(&mut owner, &decision, &peers),
        Err(SelectionError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    let pending = f.selector_bytes()?;
    assert_ne!(pending[0], empty[0]);
    assert_ne!(pending[1], empty[1]);
    drop(owner);
    let mut recovered = f.recover_config(f.config.clone())?;
    assert!(matches!(
        f.readback(&mut recovered, &decision, &peers),
        Err(SelectionError::Owner(LearningOriginalOwnerErrorV1::Pending))
    ));
    assert!(matches!(
        f.attest(&mut recovered, &decision, &peers),
        Err(SelectionError::Owner(LearningOriginalOwnerErrorV1::Pending))
    ));
    assert_eq!(f.selector_bytes()?, pending);
    assert_eq!(f.predecessor_bytes()?, predecessors);
    drop(recovered);
    assert_eq!(peers.finish()?, [1, 1]);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn q24_source_bound_model_selector_fences_changed_execution_bytes() -> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let decision = f.config.decision.clone();
    let mut owner = f.create_owner()?;
    let empty = f.selector_bytes()?;
    let original_files = f.evaluation.durable_bytes()?;
    let peers = f.peers(f.config.training_evidence.clone())?;
    let original = f.evaluation.replace_execution_byte()?;
    assert!(matches!(
        f.attest(&mut owner, &decision, &peers),
        Err(SelectionError::Cell(_))
    ));
    f.evaluation.restore_execution_bytes(&original)?;
    assert_eq!(f.evaluation.durable_bytes()?, original_files);
    assert!(matches!(
        f.readback(&mut owner, &decision, &peers),
        Err(SelectionError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(f.selector_bytes()?, empty);
    drop(owner);
    assert_eq!(peers.finish()?, [0, 0]);
    f.finish().await
}
