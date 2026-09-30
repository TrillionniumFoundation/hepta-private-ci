//! Strict wire decoding into the existing learning owner's signed trust API.

use codex_hepta_learning_ledger as ledger;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Trust {
    root_id: String,
    root_public_key_hex: String,
    #[serde(deserialize_with = "digest")]
    scope_digest: Digest32,
    #[serde(deserialize_with = "digest")]
    objective_digest: Digest32,
    authority_epoch: u64,
    root_valid_from_unix_s: u64,
    root_expires_unix_s: u64,
    root_revoked_at_unix_s: Option<u64>,
    distribution_id: String,
    generation: u64,
    effective_at_unix_s: u64,
    issued_at_unix_s: u64,
    pub(super) expires_at_unix_s: u64,
    signature_hex: String,
    signers: Vec<Signer>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Signer {
    principal_id: String,
    controller_id: String,
    #[serde(deserialize_with = "digest")]
    credential_chain_digest: Digest32,
    public_key_hex: String,
    authenticated_at_unix_s: u64,
    expires_at_unix_s: u64,
    revoked_at_unix_s: Option<u64>,
    roles: Vec<Role>,
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

impl Trust {
    pub(super) fn admission_expires_at(&self) -> u64 {
        self.root_revoked_at_unix_s
            .map_or(self.expires_at_unix_s, |revoked| {
                self.expires_at_unix_s.min(revoked.saturating_sub(1))
            })
    }

    pub(super) fn activate(self, now: u64) -> Result<ledger::ActivatedLearningTrustV1, String> {
        if self.signers.is_empty() || self.signers.len() > 32 {
            return Err("retrieval learning requires 1..=32 signed principals".to_string());
        }
        let root = ledger::LearningTrustRootV1 {
            root_id: stable(self.root_id)?,
            scope_digest: self.scope_digest,
            verifying_key: hex(&self.root_public_key_hex)?,
            valid_from: self.root_valid_from_unix_s,
            expires_at: self.root_expires_unix_s,
            revoked_at: self.root_revoked_at_unix_s,
        };
        let signers = self
            .signers
            .into_iter()
            .map(|signer| {
                let key = hex(&signer.public_key_hex)?;
                Ok(ledger::TrustedLearningSignerV1 {
                    principal: ledger::AuthenticatedPrincipalV1 {
                        principal_id: stable(signer.principal_id)?,
                        credential_chain_digest: signer.credential_chain_digest,
                        signing_key_digest: Digest32::of_bytes(&key),
                        scope_digest: self.scope_digest,
                        authority_epoch: self.authority_epoch,
                        authenticated_at: signer.authenticated_at_unix_s,
                        expires_at: signer.expires_at_unix_s,
                    },
                    controller_id: stable(signer.controller_id)?,
                    verifying_key: key,
                    roles: signer
                        .roles
                        .into_iter()
                        .map(|role| match role {
                            Role::Generator => ledger::LearningEvidenceRoleV1::Generator,
                            Role::Observer => ledger::LearningEvidenceRoleV1::Observer,
                            Role::Evaluator => ledger::LearningEvidenceRoleV1::Evaluator,
                            Role::CreditAllocator => {
                                ledger::LearningEvidenceRoleV1::CreditAllocator
                            }
                            Role::UnlearningAuthority => {
                                ledger::LearningEvidenceRoleV1::UnlearningAuthority
                            }
                            Role::Selector => ledger::LearningEvidenceRoleV1::Selector,
                        })
                        .collect(),
                    revoked_at: signer.revoked_at_unix_s,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        let signed = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: stable(self.distribution_id)?,
                generation: self.generation,
                effective_at: self.effective_at_unix_s,
                trust: ledger::LearningEvidenceTrustV1 {
                    scope_digest: self.scope_digest,
                    objective_digest: self.objective_digest,
                    authority_epoch: self.authority_epoch,
                    signers,
                },
            },
            root_id: root.root_id.clone(),
            issued_at: self.issued_at_unix_s,
            expires_at: self.expires_at_unix_s,
            signature: hex(&self.signature_hex)?,
        };
        ledger::activate_learning_trust(&root, signed, None, now).map_err(|error| error.to_string())
    }
}

fn stable(value: String) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| error.to_string())
}

fn hex<const N: usize>(value: &str) -> Result<[u8; N], String> {
    if value.len() != N * 2
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("retrieval learning key/signature requires fixed lowercase hex".to_string());
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[2 * index..2 * index + 2], 16)
            .map_err(|error| error.to_string())?;
    }
    Ok(bytes)
}

pub(super) fn digest<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Digest32, D::Error> {
    String::deserialize(deserializer)?
        .parse()
        .map_err(serde::de::Error::custom)
}
