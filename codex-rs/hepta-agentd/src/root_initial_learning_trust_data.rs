//! Complete public signed distribution data. Conversion alone grants nothing;
//! production activation is admitted only by the original Root Initial lane.

use std::io;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustRootDataV1 {
    pub(crate) schema: u8,
    pub(crate) root_id: String,
    pub(crate) scope_digest: [u8; 32],
    pub(crate) verifying_key: [u8; 32],
    pub(crate) valid_from_seconds: u64,
    pub(crate) expires_at_seconds: u64,
    pub(crate) revoked_at_seconds: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustDistributionDataV1 {
    pub(crate) schema: u8,
    pub(crate) root_id: String,
    pub(crate) distribution_id: String,
    pub(crate) generation: u64,
    pub(crate) effective_at_seconds: u64,
    pub(crate) scope_digest: [u8; 32],
    pub(crate) objective_digest: [u8; 32],
    pub(crate) authority_epoch: u64,
    pub(crate) signers: Vec<LearningTrustSignerDataV1>,
    pub(crate) issued_at_seconds: u64,
    pub(crate) expires_at_seconds: u64,
    pub(crate) signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustSignerDataV1 {
    pub(crate) principal_id: String,
    pub(crate) credential_chain_digest: [u8; 32],
    pub(crate) signing_key_digest: [u8; 32],
    pub(crate) scope_digest: [u8; 32],
    pub(crate) authority_epoch: u64,
    pub(crate) authenticated_at_seconds: u64,
    pub(crate) expires_at_seconds: u64,
    pub(crate) controller_id: String,
    pub(crate) verifying_key: [u8; 32],
    pub(crate) roles: Vec<LearningTrustRoleV1>,
    pub(crate) revoked_at_seconds: Option<u64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum LearningTrustRoleV1 {
    Generator,
    Observer,
    Evaluator,
    CreditAllocator,
    UnlearningAuthority,
    Selector,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustRoleSelectionV1 {
    pub(crate) principal_id: String,
    pub(crate) controller_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustPayloadV1 {
    pub(crate) root: LearningTrustRootDataV1,
    pub(crate) distribution: LearningTrustDistributionDataV1,
    pub(crate) generator: LearningTrustRoleSelectionV1,
    pub(crate) observer: LearningTrustRoleSelectionV1,
}

/// The named Ledger scope remains distinct from the actual task's scope. This
/// pin binds both domains through the original Root deployment/source mapping.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustPinV1 {
    pub(crate) mapping: String,
    pub(crate) target: String,
    pub(crate) task: String,
    pub(crate) source_metadata: String,
    pub(crate) root: String,
    pub(crate) distribution: String,
    pub(crate) trust: String,
    pub(crate) learning_scope: String,
    pub(crate) objective: String,
    pub(crate) roles: String,
}

impl LearningTrustPinV1 {
    pub(crate) fn require_target(
        &self,
        target: &codex_hepta_neuron::CellGenerationOwnerBindingV1,
    ) -> io::Result<()> {
        for value in [
            &self.mapping,
            &self.target,
            &self.task,
            &self.source_metadata,
            &self.root,
            &self.distribution,
            &self.trust,
            &self.learning_scope,
            &self.objective,
            &self.roles,
        ] {
            let digest: Digest32 = value.parse().map_err(io::Error::other)?;
            if digest.is_zero() || digest.to_string() != *value {
                return Err(io::Error::other("original trust pin is not canonical"));
            }
        }
        if self.target
            != Digest32::from_array(target.digest().map_err(io::Error::other)?).to_string()
            || self.task != Digest32::from_array(target.task_digest()).to_string()
        {
            return Err(io::Error::other("original trust pin names another task"));
        }
        Ok(())
    }
}

impl LearningTrustPayloadV1 {
    pub(crate) fn role_digest(&self) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.initial.learning-role-selection.v1\0",
            &serde_json::to_vec(&(&self.generator, &self.observer)).map_err(io::Error::other)?,
        ]))
    }

    pub(crate) fn require_activation_pin(
        &self,
        activated: &ActivatedLearningTrustV1,
        pin: &LearningTrustPinV1,
    ) -> io::Result<()> {
        if activated.root_digest().to_string() != pin.root
            || activated.distribution_digest().to_string() != pin.distribution
            || activated.verifier().trust_digest().to_string() != pin.trust
            || activated.verifier().scope_digest().to_string() != pin.learning_scope
            || activated.verifier().objective_digest().to_string() != pin.objective
            || self.role_digest()?.to_string() != pin.roles
        {
            return Err(io::Error::other("original activated trust pin differs"));
        }
        Ok(())
    }

    /// Only genesis is supported. None never stands in for a missing retained
    /// prior distribution during rotation or recovery of a different pin.
    pub(crate) fn activate_pinned_genesis(
        &self,
        now_seconds: u64,
    ) -> io::Result<(
        ActivatedLearningTrustV1,
        TrustedLearningSignerV1,
        TrustedLearningSignerV1,
    )> {
        if self.root.schema != 1
            || self.distribution.schema != 1
            || self.distribution.generation != 1
            || self.distribution.signature.len() != 64
            || self.distribution.signers.is_empty()
            || self.distribution.signers.len() > 64
        {
            return Err(io::Error::other("original genesis distribution required"));
        }
        let root = LearningTrustRootV1 {
            root_id: StableId::new(&self.root.root_id).map_err(io::Error::other)?,
            scope_digest: Digest32::from_array(self.root.scope_digest),
            verifying_key: self.root.verifying_key,
            valid_from: self.root.valid_from_seconds,
            expires_at: self.root.expires_at_seconds,
            revoked_at: self.root.revoked_at_seconds,
        };
        let signers = self
            .distribution
            .signers
            .iter()
            .map(LearningTrustSignerDataV1::original_signer)
            .collect::<io::Result<Vec<_>>>()?;
        let generator = select(&signers, &self.generator)?;
        let observer = select(&signers, &self.observer)?;
        let signed = SignedLearningTrustDistributionV1 {
            root_id: StableId::new(&self.distribution.root_id).map_err(io::Error::other)?,
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new(&self.distribution.distribution_id)
                    .map_err(io::Error::other)?,
                generation: self.distribution.generation,
                effective_at: self.distribution.effective_at_seconds,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: Digest32::from_array(self.distribution.scope_digest),
                    objective_digest: Digest32::from_array(self.distribution.objective_digest),
                    authority_epoch: self.distribution.authority_epoch,
                    signers,
                },
            },
            issued_at: self.distribution.issued_at_seconds,
            expires_at: self.distribution.expires_at_seconds,
            signature: self
                .distribution
                .signature
                .as_slice()
                .try_into()
                .map_err(io::Error::other)?,
        };
        let activated = activate_learning_trust(&root, signed, /*previous*/ None, now_seconds)
            .map_err(io::Error::other)?;
        for (role, signer) in [
            (LearningEvidenceRoleV1::Generator, &generator),
            (LearningEvidenceRoleV1::Observer, &observer),
        ] {
            activated
                .verifier()
                .require_signer_binding(role, signer, now_seconds)
                .map_err(io::Error::other)?;
        }
        verify_independent_roles(&generator.principal, &observer.principal, now_seconds)
            .map_err(io::Error::other)?;
        if generator.controller_id == observer.controller_id {
            return Err(io::Error::other("independent Observer controller required"));
        }
        Ok((activated, generator, observer))
    }
}

impl LearningTrustSignerDataV1 {
    pub(crate) fn original_signer(&self) -> io::Result<TrustedLearningSignerV1> {
        Ok(TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: StableId::new(&self.principal_id).map_err(io::Error::other)?,
                credential_chain_digest: Digest32::from_array(self.credential_chain_digest),
                signing_key_digest: Digest32::from_array(self.signing_key_digest),
                scope_digest: Digest32::from_array(self.scope_digest),
                authority_epoch: self.authority_epoch,
                authenticated_at: self.authenticated_at_seconds,
                expires_at: self.expires_at_seconds,
            },
            controller_id: StableId::new(&self.controller_id).map_err(io::Error::other)?,
            verifying_key: self.verifying_key,
            roles: self.roles.iter().copied().map(Into::into).collect(),
            revoked_at: self.revoked_at_seconds,
        })
    }
}

impl From<LearningTrustRoleV1> for LearningEvidenceRoleV1 {
    fn from(role: LearningTrustRoleV1) -> Self {
        match role {
            LearningTrustRoleV1::Generator => Self::Generator,
            LearningTrustRoleV1::Observer => Self::Observer,
            LearningTrustRoleV1::Evaluator => Self::Evaluator,
            LearningTrustRoleV1::CreditAllocator => Self::CreditAllocator,
            LearningTrustRoleV1::UnlearningAuthority => Self::UnlearningAuthority,
            LearningTrustRoleV1::Selector => Self::Selector,
        }
    }
}

fn select(
    signers: &[TrustedLearningSignerV1],
    selected: &LearningTrustRoleSelectionV1,
) -> io::Result<TrustedLearningSignerV1> {
    let mut matching = signers.iter().filter(|signer| {
        signer.principal.principal_id.as_str() == selected.principal_id
            && signer.controller_id.as_str() == selected.controller_id
    });
    let signer = matching
        .next()
        .ok_or_else(|| io::Error::other("original configured role absent"))?;
    if matching.next().is_some() {
        return Err(io::Error::other("original role is ambiguous"));
    }
    Ok(signer.clone())
}

#[cfg(test)]
#[path = "root_initial_learning_trust_data_tests.rs"]
mod tests;
