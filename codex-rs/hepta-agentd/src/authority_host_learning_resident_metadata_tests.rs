//! Explicit signed metadata for resident protocol/storage mechanism tests.
//! These observations do not claim Training, selection, Task C or adoption.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(super) struct ResidentMetadata {
    _directory: tempfile::TempDir,
    pub(super) initial: LearningIterationSnapshotV1,
    pub(super) scope: FrozenLearningScopeV2,
    pub(super) verifier: LearningEvidenceVerifierV1,
    trust: LearningEvidenceTrustV1,
    at: u64,
}

pub(super) fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

impl ResidentMetadata {
    pub(super) fn new() -> anyhow::Result<Self> {
        let (directory, _, initial) =
            crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
        let mut request = initial.snapshot().request.clone();
        let mut owners = initial.snapshot().owners.clone();
        let at = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        request.envelope.expiry_unix_seconds = at + 120;
        let evidence_scope = digest("resident-protocol-fixture-evidence-scope");
        let mut signers = Vec::new();
        for (index, (principal_id, role)) in [
            (owners.experience.clone(), LearningEvidenceRoleV1::Observer),
            (owners.dataset.clone(), LearningEvidenceRoleV1::Observer),
            (owners.trainer.clone(), LearningEvidenceRoleV1::Generator),
            (owners.selector.clone(), LearningEvidenceRoleV1::Selector),
            (owners.next_use_observer.clone(), LearningEvidenceRoleV1::Observer),
        ].into_iter().enumerate() {
            let key = SigningKey::from_bytes(&[121 + index as u8; 32]);
            signers.push(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id,
                    credential_chain_digest: digest(&format!("resident-fixture-chain-{index}")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: evidence_scope,
                    authority_epoch: 1,
                    authenticated_at: at - 60,
                    expires_at: at + 600,
                },
                controller_id: StableId::new(format!("resident-fixture-controller-{index}"))?,
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            });
        }
        let trust = LearningEvidenceTrustV1 {
            scope_digest: evidence_scope,
            objective_digest: request.envelope.objective_digest,
            authority_epoch: 1,
            signers,
        };
        let verifier = LearningEvidenceVerifierV1::new(trust.clone())?;
        owners.evidence_trust_digest = verifier.trust_digest();
        let initial = LearningIterationCoordinatorV1::new(request, owners)?.snapshot().clone();
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request, &initial.owners, LearningUpdateScopeV2::Cell,
            digest("resident-fixture-frozen-rule"),
        )?;
        Ok(Self { _directory: directory, initial, scope, verifier, trust, at })
    }

    pub(super) fn other_evidence_scope(&self) -> anyhow::Result<LearningEvidenceVerifierV1> {
        let mut trust = self.trust.clone();
        trust.scope_digest = digest("different-resident-evidence-scope");
        for signer in &mut trust.signers {
            signer.principal.scope_digest = trust.scope_digest;
        }
        Ok(LearningEvidenceVerifierV1::new(trust)?)
    }

    pub(super) fn completed_metadata(
        &self,
    ) -> anyhow::Result<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)> {
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(self.initial.clone())?;
        let bundle = self.initial.request.selected_bundle.digest()?;
        let observations = [
            LearningIterationObservationV1::Experience {
                episode_digest: digest("resident-fixture-episode"),
                completed_task_receipt: self.initial.request.completed_task_receipt,
            },
            LearningIterationObservationV1::Dataset {
                snapshot_digest: digest("resident-fixture-dataset"),
                episode_digest: digest("resident-fixture-episode"),
                withdrawal_frontier: digest("resident-fixture-withdrawal"),
                rows: 1,
                bytes: 64,
            },
            LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
                retained_bundle: bundle,
                dataset: digest("resident-fixture-dataset"),
                update_rule: digest("resident-fixture-frozen-rule"),
                steps: 1,
                milliseconds: 1,
                reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
            }),
            LearningIterationObservationV1::Selection {
                candidate_bundle: bundle,
                selection_digest: digest("resident-fixture-selection"),
            },
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: bundle,
                state_partition: CellStatePartitionV1 {
                    principal_id: self.initial.request.principal_id.clone(),
                    agent_id: self.initial.request.agent_id.clone(),
                    cell_id: self.initial.request.cell_id.clone(),
                    run_id: StableId::new("resident-fixture-distinct-C")?,
                },
                checkpoint_digest: digest("resident-fixture-checkpoint"),
                selection_digest: digest("resident-fixture-selection"),
                committed_step_receipt: digest("resident-fixture-step"),
                task_owner_publication: digest("resident-fixture-publication"),
            },
        ];
        let mut signatures = Vec::new();
        for (index, observation) in observations.into_iter().enumerate() {
            let receipt = LearningIterationReceiptV1 {
                operation_id: self.initial.request.operation_id.clone(),
                predecessor: coordinator.snapshot().head_digest,
                actor_id: self.initial.owners.owner(observation.stage()).clone(),
                evidence_digest: digest(&format!("resident-fixture-result-{index}")),
                observed_unix_seconds: self.at,
                observation,
            };
            let role = self.trust.signers[index].roles[0];
            let key = SigningKey::from_bytes(&[121 + index as u8; 32]);
            let mut signature = SignedLearningEvidenceV1 {
                evidence_id: StableId::new(format!("resident-fixture-evidence-{index}"))?,
                principal_id: receipt.actor_id.clone(),
                role,
                trust_digest: self.verifier.trust_digest(),
                scope_digest: self.verifier.scope_digest(),
                objective_digest: self.verifier.objective_digest(),
                authority_epoch: 1,
                issued_at: self.at,
                expires_at: self.at + 600,
                payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(&receipt)?),
                signature: [0; 64],
            };
            signature.signature = key.sign(&signature.signing_bytes()).to_bytes();
            coordinator.record(receipt, self.at)?;
            signatures.push(signature);
        }
        Ok((coordinator.snapshot().clone(), signatures))
    }
}
