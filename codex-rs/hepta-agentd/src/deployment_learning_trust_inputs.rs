//! External Root configuration inputs. These values are not current authority.

use std::io;
use std::path::Path;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub(crate) struct OriginalLearningTrustInputs {
    pub(crate) root: LearningTrustRootV1,
    pub(crate) signed: SignedLearningTrustDistributionV1,
    pub(crate) acknowledgement: RootAcknowledgementDeclaration,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootAcknowledgementDeclaration {
    pub(crate) schema_version: u32,
    pub(crate) operation: String,
    pub(crate) owner_id: String,
    pub(crate) workspace_digest: String,
    pub(crate) objective_digest: String,
    pub(crate) ledger_binding: String,
    pub(crate) sequence: u64,
    pub(crate) chain_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RootPin {
    schema_version: u32,
    operation: String,
    root_id: String,
    scope_digest: String,
    verifying_key: [u8; 32],
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Distribution {
    schema_version: u32,
    operation: String,
    root_id: String,
    distribution_id: String,
    generation: u64,
    effective_at: u64,
    issued_at: u64,
    expires_at: u64,
    signature: Vec<u8>,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    signers: Vec<Signer>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Signer {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
    controller_id: String,
    verifying_key: [u8; 32],
    roles: Vec<Role>,
    revoked_at: Option<u64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Role {
    Generator,
    Observer,
    Evaluator,
    CreditAllocator,
    UnlearningAuthority,
    Selector,
}

impl OriginalLearningTrustInputs {
    pub(crate) fn read_original_learning_trust_inputs(
        root_pin: &Path,
        distribution: &Path,
        acknowledgement: &Path,
    ) -> io::Result<Self> {
        if root_pin == distribution
            || root_pin == acknowledgement
            || distribution == acknowledgement
        {
            return Err(io::Error::other(
                "separate original Root input files required",
            ));
        }
        let pin: RootPin = crate::authority_host_config::read_root_json(root_pin)?;
        let distribution: Distribution =
            crate::authority_host_config::read_root_json(distribution)?;
        let acknowledgement = crate::authority_host_config::read_root_json(acknowledgement)?;
        Self::from_parts(pin, distribution, acknowledgement)
    }

    fn from_parts(
        pin: RootPin,
        distribution: Distribution,
        acknowledgement: RootAcknowledgementDeclaration,
    ) -> io::Result<Self> {
        if pin.schema_version != 1
            || pin.operation != "hepta.learning-ledger.root-pin.v1"
            || distribution.schema_version != 1
            || distribution.operation != "hepta.learning-ledger.signed-distribution.v1"
            || acknowledgement.schema_version != 1
            || acknowledgement.operation != "hepta.learning-ledger.root-ack-declaration.v1"
        {
            return Err(io::Error::other("unsupported external Root input profile"));
        }
        let root = LearningTrustRootV1 {
            root_id: StableId::new(pin.root_id).map_err(io::Error::other)?,
            scope_digest: pin.scope_digest.parse().map_err(io::Error::other)?,
            verifying_key: pin.verifying_key,
            valid_from: pin.valid_from,
            expires_at: pin.expires_at,
            revoked_at: pin.revoked_at,
        };
        let signers = distribution
            .signers
            .into_iter()
            .map(|signer| {
                Ok(TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: StableId::new(signer.principal_id)
                            .map_err(io::Error::other)?,
                        credential_chain_digest: signer
                            .credential_chain_digest
                            .parse()
                            .map_err(io::Error::other)?,
                        signing_key_digest: signer
                            .signing_key_digest
                            .parse()
                            .map_err(io::Error::other)?,
                        scope_digest: signer.scope_digest.parse().map_err(io::Error::other)?,
                        authority_epoch: signer.authority_epoch,
                        authenticated_at: signer.authenticated_at,
                        expires_at: signer.expires_at,
                    },
                    controller_id: StableId::new(signer.controller_id).map_err(io::Error::other)?,
                    verifying_key: signer.verifying_key,
                    roles: signer
                        .roles
                        .into_iter()
                        .map(|role| match role {
                            Role::Generator => LearningEvidenceRoleV1::Generator,
                            Role::Observer => LearningEvidenceRoleV1::Observer,
                            Role::Evaluator => LearningEvidenceRoleV1::Evaluator,
                            Role::CreditAllocator => LearningEvidenceRoleV1::CreditAllocator,
                            Role::UnlearningAuthority => {
                                LearningEvidenceRoleV1::UnlearningAuthority
                            }
                            Role::Selector => LearningEvidenceRoleV1::Selector,
                        })
                        .collect(),
                    revoked_at: signer.revoked_at,
                })
            })
            .collect::<io::Result<Vec<_>>>()?;
        let signed = SignedLearningTrustDistributionV1 {
            root_id: StableId::new(distribution.root_id).map_err(io::Error::other)?,
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new(distribution.distribution_id)
                    .map_err(io::Error::other)?,
                generation: distribution.generation,
                effective_at: distribution.effective_at,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: distribution
                        .scope_digest
                        .parse()
                        .map_err(io::Error::other)?,
                    objective_digest: distribution
                        .objective_digest
                        .parse()
                        .map_err(io::Error::other)?,
                    authority_epoch: distribution.authority_epoch,
                    signers,
                },
            },
            issued_at: distribution.issued_at,
            expires_at: distribution.expires_at,
            signature: distribution
                .signature
                .try_into()
                .map_err(|_| io::Error::other("exact external signature length required"))?,
        };
        Ok(Self {
            root,
            signed,
            acknowledgement,
        })
    }
}

#[cfg(test)]
#[path = "deployment_learning_trust_inputs_tests.rs"]
mod tests;
