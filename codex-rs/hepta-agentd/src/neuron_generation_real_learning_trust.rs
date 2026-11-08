//! Distinct scoped research role keys, verified by the original trust owner.
//! One operator controls these test issuers; this is not independent custody.

use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::process::now;

pub(super) struct ResearchTrust {
    keys: Vec<SigningKey>,
    principals: Vec<AuthenticatedPrincipalV1>,
    pub(super) verifier: LearningEvidenceVerifierV1,
    objective: Digest32,
    expires: u64,
}

impl ResearchTrust {
    pub(super) fn new(operation: &str, objective: Digest32, expires: u64) -> anyhow::Result<Self> {
        let created = now()?;
        let scope = Digest32::of_parts(&[
            b"hepta.research.real-model.roles.v1\0",
            operation.as_bytes(),
        ]);
        let mut keys = Vec::new();
        let mut principals = Vec::new();
        for label in ["trainer", "evaluator", "selector", "observer"] {
            let key = SigningKey::from_bytes(
                Digest32::of_parts(&[
                    b"explicit-research-key\0",
                    operation.as_bytes(),
                    label.as_bytes(),
                ])
                .as_array(),
            );
            principals.push(AuthenticatedPrincipalV1 {
                principal_id: StableId::new(format!("{operation}-{label}"))?,
                credential_chain_digest: Digest32::of_parts(&[
                    b"research-role-credential\0",
                    scope.as_array(),
                    label.as_bytes(),
                ]),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 1,
                authenticated_at: created,
                expires_at: expires,
            });
            keys.push(key);
        }
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 1,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| {
                    Ok(TrustedLearningSignerV1 {
                        principal: principal.clone(),
                        controller_id: StableId::new(format!(
                            "{operation}-research-controller-{index}"
                        ))?,
                        verifying_key: key.verifying_key().to_bytes(),
                        roles: vec![match index {
                            0 => LearningEvidenceRoleV1::Generator,
                            1 => LearningEvidenceRoleV1::Evaluator,
                            2 => LearningEvidenceRoleV1::Selector,
                            _ => LearningEvidenceRoleV1::Observer,
                        }],
                        revoked_at: None,
                    })
                })
                .collect::<anyhow::Result<Vec<_>>>()?,
        })?;
        Ok(Self {
            keys,
            principals,
            verifier,
            objective,
            expires,
        })
    }

    pub(super) fn owners(&self) -> anyhow::Result<LearningIterationOwnersV1> {
        Ok(LearningIterationOwnersV1 {
            evidence_trust_digest: self.verifier.trust_digest(),
            experience: self.principals[3].principal_id.clone(),
            dataset: self.principals[3].principal_id.clone(),
            trainer: self.principals[0].principal_id.clone(),
            evaluator: self.principals[1].principal_id.clone(),
            proposal: StableId::new("unused-research-no-update-proposal")?,
            selector: self.principals[2].principal_id.clone(),
            next_use_observer: self.principals[3].principal_id.clone(),
        })
    }

    pub(super) fn sign(
        &self,
        receipt: &LearningIterationReceiptV1,
    ) -> anyhow::Result<SignedLearningEvidenceV1> {
        let (index, role) = match receipt.observation.stage() {
            LearningIterationStageV1::Training => (0, LearningEvidenceRoleV1::Generator),
            LearningIterationStageV1::Evaluation => (1, LearningEvidenceRoleV1::Evaluator),
            LearningIterationStageV1::Selection => (2, LearningEvidenceRoleV1::Selector),
            LearningIterationStageV1::Experience
            | LearningIterationStageV1::Dataset
            | LearningIterationStageV1::NextUse => (3, LearningEvidenceRoleV1::Observer),
            LearningIterationStageV1::Proposal => anyhow::bail!("no research proposal authority"),
        };
        let principal = &self.principals[index];
        anyhow::ensure!(
            receipt.actor_id == principal.principal_id,
            "wrong actual receipt signer"
        );
        let mut result = SignedLearningEvidenceV1 {
            evidence_id: StableId::new(format!(
                "research-attestation-{}",
                receipt.evidence_digest
            ))?,
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: self.objective,
            authority_epoch: 1,
            issued_at: now()?,
            expires_at: self.expires,
            payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(
                receipt,
            )?),
            signature: [0; 64],
        };
        result.signature = self.keys[index].sign(&result.signing_bytes()).to_bytes();
        Ok(result)
    }
}
