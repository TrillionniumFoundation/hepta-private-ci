use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactOwnerTrustV1;

const MAX_HOST_PRINCIPALS: usize = 64;
const MAX_ACTIONS_PER_PRINCIPAL: usize = 16;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum LearningArtifactHostActionV1 {
    Publish,
    CurrentRegistryView,
    InstallWithdrawalFrontier,
    RotateAccessPolicy,
    PrepareBackup,
    BeginShutdown,
    FinishShutdown,
    MigrateControlSchema,
}

impl LearningArtifactHostActionV1 {
    #[must_use]
    pub const fn tag(self) -> u8 {
        match self {
            Self::Publish => 1,
            Self::CurrentRegistryView => 2,
            Self::InstallWithdrawalFrontier => 3,
            Self::RotateAccessPolicy => 4,
            Self::PrepareBackup => 5,
            Self::BeginShutdown => 6,
            Self::FinishShutdown => 7,
            Self::MigrateControlSchema => 8,
        }
    }

    pub(crate) const fn from_tag(value: u8) -> Option<Self> {
        match value {
            1 => Some(Self::Publish),
            2 => Some(Self::CurrentRegistryView),
            3 => Some(Self::InstallWithdrawalFrontier),
            4 => Some(Self::RotateAccessPolicy),
            5 => Some(Self::PrepareBackup),
            6 => Some(Self::BeginShutdown),
            7 => Some(Self::FinishShutdown),
            8 => Some(Self::MigrateControlSchema),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedLearningArtifactHostPrincipalV1 {
    pub principal_id: StableId,
    pub verifying_key: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub maximum_authority_epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
    pub allowed_actions: Vec<LearningArtifactHostActionV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactHostAccessPolicyV1 {
    pub policy_id: StableId,
    pub generation: u64,
    pub minimum_authority_epoch: u64,
    pub principals: Vec<TrustedLearningArtifactHostPrincipalV1>,
}

impl LearningArtifactHostAccessPolicyV1 {
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        let mut principals = self.principals.clone();
        principals.sort_by(|left, right| left.principal_id.cmp(&right.principal_id));
        let mut bytes = b"hepta.learning-artifacts.host-access-policy.v1".to_vec();
        push_id(&mut bytes, &self.policy_id);
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        bytes.extend_from_slice(&self.minimum_authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&(principals.len() as u64).to_be_bytes());
        for principal in principals {
            push_id(&mut bytes, &principal.principal_id);
            bytes.extend_from_slice(&principal.verifying_key);
            bytes.extend_from_slice(&principal.minimum_authority_epoch.to_be_bytes());
            bytes.extend_from_slice(&principal.maximum_authority_epoch.to_be_bytes());
            bytes.extend_from_slice(&principal.valid_from.to_be_bytes());
            bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
            match principal.revoked_at {
                Some(at) => {
                    bytes.push(1);
                    bytes.extend_from_slice(&at.to_be_bytes());
                }
                None => bytes.push(0),
            }
            let mut actions = principal.allowed_actions;
            actions.sort_unstable();
            bytes.extend_from_slice(&(actions.len() as u64).to_be_bytes());
            for action in actions {
                bytes.push(action.tag());
            }
        }
        bytes
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.canonical_bytes())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedLearningArtifactHostCommandV1 {
    pub command_id: StableId,
    pub policy_id: StableId,
    pub policy_generation: u64,
    pub principal_id: StableId,
    pub action: LearningArtifactHostActionV1,
    pub request_digest: Digest32,
    pub signing_key_digest: Digest32,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl SignedLearningArtifactHostCommandV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.host-command.v1".to_vec();
        push_id(&mut bytes, &self.command_id);
        push_id(&mut bytes, &self.policy_id);
        bytes.extend_from_slice(&self.policy_generation.to_be_bytes());
        push_id(&mut bytes, &self.principal_id);
        bytes.push(self.action.tag());
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.signing_key_digest.as_array());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.issued_at.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at.to_be_bytes());
        bytes
    }

    #[must_use]
    pub fn command_digest(&self) -> Digest32 {
        let mut bytes = self.signing_bytes();
        bytes.extend_from_slice(&self.signature);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedLearningArtifactHostCommandV1 {
    pub(super) command_id: StableId,
    pub(super) principal_id: StableId,
    pub(super) action: LearningArtifactHostActionV1,
    pub(super) request_digest: Digest32,
    pub(super) command_digest: Digest32,
    pub(super) policy_digest: Digest32,
    pub(super) authority: AuthorityPosture,
}

impl VerifiedLearningArtifactHostCommandV1 {
    #[must_use]
    pub fn command_id(&self) -> &StableId {
        &self.command_id
    }

    #[must_use]
    pub fn principal_id(&self) -> &StableId {
        &self.principal_id
    }

    #[must_use]
    pub const fn action(&self) -> LearningArtifactHostActionV1 {
        self.action
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn command_digest(&self) -> Digest32 {
        self.command_digest
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug)]
pub(super) struct LearningArtifactHostAccessVerifierV1 {
    policy: LearningArtifactHostAccessPolicyV1,
    policy_digest: Digest32,
    principals: BTreeMap<StableId, TrustedLearningArtifactHostPrincipalV1>,
}

impl LearningArtifactHostAccessVerifierV1 {
    pub(super) fn new(
        mut policy: LearningArtifactHostAccessPolicyV1,
        owner_trust: &ArtifactOwnerTrustV1,
    ) -> Result<Self, LearningArtifactHostAccessError> {
        if policy.generation == 0
            || policy.minimum_authority_epoch == 0
            || policy.principals.is_empty()
            || policy.principals.len() > MAX_HOST_PRINCIPALS
        {
            return Err(LearningArtifactHostAccessError::InvalidPolicy);
        }
        policy
            .principals
            .sort_by(|left, right| left.principal_id.cmp(&right.principal_id));
        let owner_keys: Vec<Digest32> = owner_trust
            .writer_signers
            .iter()
            .chain(owner_trust.head_signers.iter())
            .map(|signer| Digest32::of_bytes(&signer.verifying_key))
            .collect();
        let mut principals = BTreeMap::new();
        for principal in &mut policy.principals {
            principal.allowed_actions.sort_unstable();
            if principal.minimum_authority_epoch == 0
                || principal.maximum_authority_epoch < principal.minimum_authority_epoch
                || principal.valid_from > principal.expires_at
                || principal.allowed_actions.is_empty()
                || principal.allowed_actions.len() > MAX_ACTIONS_PER_PRINCIPAL
                || principal
                    .allowed_actions
                    .windows(2)
                    .any(|pair| pair[0] == pair[1])
            {
                return Err(LearningArtifactHostAccessError::InvalidPolicy);
            }
            let key = VerifyingKey::from_bytes(&principal.verifying_key)
                .map_err(|_| LearningArtifactHostAccessError::InvalidKey)?;
            if key.is_weak() {
                return Err(LearningArtifactHostAccessError::InvalidKey);
            }
            let key_digest = Digest32::of_bytes(&principal.verifying_key);
            if owner_keys.contains(&key_digest) {
                return Err(LearningArtifactHostAccessError::AuthorityKeyCollision);
            }
            if principals
                .insert(principal.principal_id.clone(), principal.clone())
                .is_some()
            {
                return Err(LearningArtifactHostAccessError::InvalidPolicy);
            }
        }
        let policy_digest = policy.digest();
        Ok(Self {
            policy,
            policy_digest,
            principals,
        })
    }

    pub(super) fn verify(
        &self,
        command: &SignedLearningArtifactHostCommandV1,
        expected_action: LearningArtifactHostActionV1,
        expected_request_digest: Digest32,
        now: u64,
    ) -> Result<VerifiedLearningArtifactHostCommandV1, LearningArtifactHostAccessError> {
        if command.policy_id != self.policy.policy_id
            || command.policy_generation != self.policy.generation
            || command.action != expected_action
            || command.request_digest != expected_request_digest
            || command.request_digest.is_zero()
            || command.authority_epoch < self.policy.minimum_authority_epoch
            || command.authority_epoch == 0
            || command.issued_at > now
            || now > command.expires_at
            || command.issued_at > command.expires_at
        {
            return Err(LearningArtifactHostAccessError::CommandContext);
        }
        let principal = self
            .principals
            .get(&command.principal_id)
            .ok_or(LearningArtifactHostAccessError::UnknownPrincipal)?;
        if !principal.allowed_actions.contains(&expected_action) {
            return Err(LearningArtifactHostAccessError::ActionDenied);
        }
        if command.authority_epoch < principal.minimum_authority_epoch
            || command.authority_epoch > principal.maximum_authority_epoch
            || command.issued_at < principal.valid_from
            || command.expires_at > principal.expires_at
            || principal.revoked_at.is_some_and(|at| at <= now)
        {
            return Err(LearningArtifactHostAccessError::PrincipalContext);
        }
        let key_digest = Digest32::of_bytes(&principal.verifying_key);
        if command.signing_key_digest != key_digest {
            return Err(LearningArtifactHostAccessError::KeyDigestMismatch);
        }
        VerifyingKey::from_bytes(&principal.verifying_key)
            .map_err(|_| LearningArtifactHostAccessError::InvalidKey)?
            .verify_strict(
                &command.signing_bytes(),
                &Signature::from_bytes(&command.signature),
            )
            .map_err(|_| LearningArtifactHostAccessError::InvalidSignature)?;
        Ok(VerifiedLearningArtifactHostCommandV1 {
            command_id: command.command_id.clone(),
            principal_id: command.principal_id.clone(),
            action: command.action,
            request_digest: command.request_digest,
            command_digest: command.command_digest(),
            policy_digest: self.policy_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub(super) fn policy(&self) -> &LearningArtifactHostAccessPolicyV1 {
        &self.policy
    }

    pub(super) const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningArtifactHostAccessError {
    InvalidPolicy,
    InvalidKey,
    AuthorityKeyCollision,
    UnknownPrincipal,
    ActionDenied,
    CommandContext,
    PrincipalContext,
    KeyDigestMismatch,
    InvalidSignature,
}

impl fmt::Display for LearningArtifactHostAccessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningArtifactHostAccessError {}

pub(super) fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
mod tests {
    use super::*;

    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::TrustedArtifactSignerV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("stable id")
    }

    fn owner_trust() -> ArtifactOwnerTrustV1 {
        let writer = SigningKey::from_bytes(&[7_u8; 32]);
        let head = SigningKey::from_bytes(&[8_u8; 32]);
        let signer = |name: &str, key: &SigningKey| TrustedArtifactSignerV1 {
            signer_id: id(name),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 1_000,
            revoked_at: None,
        };
        ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: Digest32::of_bytes(b"scope"),
            minimum_registry_generation: Generation::new(1).expect("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer("writer", &writer)],
            head_signers: vec![signer("head", &head)],
        }
    }

    fn policy(key: &SigningKey) -> LearningArtifactHostAccessPolicyV1 {
        LearningArtifactHostAccessPolicyV1 {
            policy_id: id("host-policy"),
            generation: 1,
            minimum_authority_epoch: 1,
            principals: vec![TrustedLearningArtifactHostPrincipalV1 {
                principal_id: id("operator"),
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 9,
                valid_from: 1,
                expires_at: 1_000,
                revoked_at: None,
                allowed_actions: vec![LearningArtifactHostActionV1::Publish],
            }],
        }
    }

    #[test]
    fn signed_command_is_action_and_request_bound() {
        let key = SigningKey::from_bytes(&[9_u8; 32]);
        let verifier = LearningArtifactHostAccessVerifierV1::new(policy(&key), &owner_trust())
            .expect("verifier");
        let request_digest = Digest32::of_bytes(b"request");
        let mut command = SignedLearningArtifactHostCommandV1 {
            command_id: id("command"),
            policy_id: id("host-policy"),
            policy_generation: 1,
            principal_id: id("operator"),
            action: LearningArtifactHostActionV1::Publish,
            request_digest,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 10,
            expires_at: 20,
            signature: [0; 64],
        };
        command.signature = key.sign(&command.signing_bytes()).to_bytes();
        let verified = verifier
            .verify(
                &command,
                LearningArtifactHostActionV1::Publish,
                request_digest,
                15,
            )
            .expect("verify");
        assert_eq!(verified.command_id(), &id("command"));
        assert_eq!(verified.authority(), AuthorityPosture::DENY_ALL);
        assert_eq!(
            verifier.verify(
                &command,
                LearningArtifactHostActionV1::Publish,
                Digest32::of_bytes(b"other"),
                15,
            ),
            Err(LearningArtifactHostAccessError::CommandContext)
        );
    }

    #[test]
    fn host_keys_must_be_separate_from_owner_keys() {
        let owner = owner_trust();
        let collision = SigningKey::from_bytes(&[7_u8; 32]);
        assert_eq!(
            LearningArtifactHostAccessVerifierV1::new(policy(&collision), &owner)
                .expect_err("collision"),
            LearningArtifactHostAccessError::AuthorityKeyCollision
        );
    }
}
