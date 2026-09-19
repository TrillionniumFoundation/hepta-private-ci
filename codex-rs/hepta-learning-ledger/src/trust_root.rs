//! Pinned root-of-trust admission for learning signer distribution. The root
//! public key is supplied out-of-band by the product host; a submitted manifest
//! can never choose or replace that root.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::RwLock;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::LearningEvidenceTrustProviderV1;
use crate::LearningEvidenceTrustSnapshotV1;
use crate::LearningEvidenceTrustV1;
use crate::LearningEvidenceVerifierV1;
use crate::SignedEvidenceError;

const MAX_MANIFEST_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningTrustRootV1 {
    pub root_id: StableId,
    pub verifying_key: [u8; 32],
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub minimum_authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedLearningTrustManifestV1 {
    pub manifest_id: StableId,
    pub root_id: StableId,
    pub generation: u64,
    pub predecessor_manifest_digest: Option<Digest32>,
    pub issued_at: u64,
    pub expires_at: u64,
    pub trust: LearningEvidenceTrustV1,
    pub signature: [u8; 64],
}

#[derive(Clone, Debug)]
pub struct VerifiedLearningTrustManifestV1 {
    pub manifest_id: StableId,
    pub generation: u64,
    pub manifest_digest: Digest32,
    pub trust_digest: Digest32,
    pub issued_at: u64,
    pub expires_at: u64,
    pub trust: LearningEvidenceTrustV1,
    pub verifier: LearningEvidenceVerifierV1,
}

#[derive(Clone, Debug)]
struct RootedLearningTrustStateV1 {
    root: LearningTrustRootV1,
    current: VerifiedLearningTrustManifestV1,
}

/// Cloneable live provider backed by one out-of-band pinned public root. Signer
/// distributions may rotate only through root-signed, predecessor-bound
/// manifests. The root private key is never accepted by this type.
#[derive(Clone, Debug)]
pub struct RootedLearningEvidenceTrustProviderV1 {
    state: Arc<RwLock<RootedLearningTrustStateV1>>,
}

impl RootedLearningEvidenceTrustProviderV1 {
    pub fn new(
        root: LearningTrustRootV1,
        initial_manifest: SignedLearningTrustManifestV1,
        now: u64,
    ) -> Result<Self, TrustRootError> {
        let current = verify_learning_trust_manifest(&root, initial_manifest, None, now)?;
        Ok(Self {
            state: Arc::new(RwLock::new(RootedLearningTrustStateV1 { root, current })),
        })
    }

    pub fn rotate(
        &self,
        next_manifest: SignedLearningTrustManifestV1,
        now: u64,
    ) -> Result<Digest32, TrustRootError> {
        let mut state = self.state.write().map_err(|_| TrustRootError::Poisoned)?;
        let next = verify_learning_trust_manifest(
            &state.root,
            next_manifest,
            Some(&state.current),
            now,
        )?;
        let digest = next.manifest_digest;
        state.current = next;
        Ok(digest)
    }

    pub fn current_manifest_digest(&self) -> Result<Digest32, TrustRootError> {
        let state = self.state.read().map_err(|_| TrustRootError::Poisoned)?;
        Ok(state.current.manifest_digest)
    }
}

impl LearningEvidenceTrustProviderV1 for RootedLearningEvidenceTrustProviderV1 {
    fn current_trust(
        &self,
        now: u64,
    ) -> Result<LearningEvidenceTrustSnapshotV1, SignedEvidenceError> {
        let state = self
            .state
            .read()
            .map_err(|_| SignedEvidenceError::InvalidTrust)?;
        let current = &state.current;
        let snapshot = LearningEvidenceTrustSnapshotV1 {
            revision: current.generation,
            valid_from: current.issued_at,
            valid_until: current.expires_at,
            trust: current.trust.clone(),
        };
        snapshot.validate(now)?;
        Ok(snapshot)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TrustRootError {
    InvalidRoot,
    InvalidManifest,
    RootMismatch,
    ScopeMismatch,
    ObjectiveMismatch,
    AuthorityEpochRollback,
    GenerationRollback,
    PredecessorMismatch,
    ValidityWindow,
    ManifestLimit,
    InvalidSignature,
    Poisoned,
    EvidenceTrust(SignedEvidenceError),
}

impl fmt::Display for TrustRootError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TrustRootError {}

impl From<SignedEvidenceError> for TrustRootError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::EvidenceTrust(value)
    }
}

pub fn trust_manifest_signing_bytes(
    manifest: &SignedLearningTrustManifestV1,
) -> Result<Vec<u8>, TrustRootError> {
    let mut signers = manifest.trust.signers.clone();
    signers.sort_by(|left, right| left.principal.principal_id.cmp(&right.principal.principal_id));
    if signers.is_empty() || signers.len() > 64 || manifest.generation == 0 {
        return Err(TrustRootError::InvalidManifest);
    }
    let mut bytes = b"hepta.learning-ledger.trust-manifest.v1".to_vec();
    push_id(&mut bytes, &manifest.manifest_id);
    push_id(&mut bytes, &manifest.root_id);
    bytes.extend_from_slice(&manifest.generation.to_be_bytes());
    push_optional_digest(&mut bytes, manifest.predecessor_manifest_digest);
    bytes.extend_from_slice(&manifest.issued_at.to_be_bytes());
    bytes.extend_from_slice(&manifest.expires_at.to_be_bytes());
    bytes.extend_from_slice(manifest.trust.scope_digest.as_array());
    bytes.extend_from_slice(manifest.trust.objective_digest.as_array());
    bytes.extend_from_slice(&manifest.trust.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&(signers.len() as u32).to_be_bytes());
    for mut signer in signers {
        signer.roles.sort();
        push_id(&mut bytes, &signer.principal.principal_id);
        push_id(&mut bytes, &signer.controller_id);
        bytes.extend_from_slice(signer.principal.credential_chain_digest.as_array());
        bytes.extend_from_slice(signer.principal.signing_key_digest.as_array());
        bytes.extend_from_slice(signer.principal.scope_digest.as_array());
        bytes.extend_from_slice(&signer.principal.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&signer.principal.authenticated_at.to_be_bytes());
        bytes.extend_from_slice(&signer.principal.expires_at.to_be_bytes());
        bytes.extend_from_slice(&signer.verifying_key);
        bytes.extend_from_slice(&(signer.roles.len() as u32).to_be_bytes());
        for role in signer.roles {
            bytes.push(role.tag());
        }
        match signer.revoked_at {
            Some(at) => {
                bytes.push(1);
                bytes.extend_from_slice(&at.to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
    if bytes.len() > MAX_MANIFEST_BYTES {
        return Err(TrustRootError::ManifestLimit);
    }
    Ok(bytes)
}

pub fn verify_learning_trust_manifest(
    root: &LearningTrustRootV1,
    manifest: SignedLearningTrustManifestV1,
    previous: Option<&VerifiedLearningTrustManifestV1>,
    now: u64,
) -> Result<VerifiedLearningTrustManifestV1, TrustRootError> {
    if root.scope_digest.is_zero()
        || root.objective_digest.is_zero()
        || root.minimum_authority_epoch == 0
    {
        return Err(TrustRootError::InvalidRoot);
    }
    let root_key =
        VerifyingKey::from_bytes(&root.verifying_key).map_err(|_| TrustRootError::InvalidRoot)?;
    if root_key.is_weak() {
        return Err(TrustRootError::InvalidRoot);
    }
    if manifest.root_id != root.root_id {
        return Err(TrustRootError::RootMismatch);
    }
    if manifest.trust.scope_digest != root.scope_digest {
        return Err(TrustRootError::ScopeMismatch);
    }
    if manifest.trust.objective_digest != root.objective_digest {
        return Err(TrustRootError::ObjectiveMismatch);
    }
    if manifest.trust.authority_epoch < root.minimum_authority_epoch {
        return Err(TrustRootError::AuthorityEpochRollback);
    }
    if manifest.issued_at > now
        || now > manifest.expires_at
        || manifest.issued_at > manifest.expires_at
    {
        return Err(TrustRootError::ValidityWindow);
    }
    match previous {
        Some(previous) => {
            if manifest.generation != previous.generation + 1 {
                return Err(TrustRootError::GenerationRollback);
            }
            if manifest.predecessor_manifest_digest != Some(previous.manifest_digest) {
                return Err(TrustRootError::PredecessorMismatch);
            }
            if manifest.trust.authority_epoch < previous.verifier.authority_epoch() {
                return Err(TrustRootError::AuthorityEpochRollback);
            }
        }
        None => {
            if manifest.predecessor_manifest_digest.is_some() {
                return Err(TrustRootError::PredecessorMismatch);
            }
        }
    }
    let signing_bytes = trust_manifest_signing_bytes(&manifest)?;
    root_key
        .verify_strict(&signing_bytes, &Signature::from_bytes(&manifest.signature))
        .map_err(|_| TrustRootError::InvalidSignature)?;
    let manifest_digest = digest_signed_manifest(&signing_bytes, &manifest.signature);
    let issued_at = manifest.issued_at;
    let expires_at = manifest.expires_at;
    let trust = manifest.trust.clone();
    let verifier = LearningEvidenceVerifierV1::new(manifest.trust)?;
    let trust_digest = verifier.trust_digest();
    Ok(VerifiedLearningTrustManifestV1 {
        manifest_id: manifest.manifest_id,
        generation: manifest.generation,
        manifest_digest,
        trust_digest,
        issued_at,
        expires_at,
        trust,
        verifier,
    })
}

fn digest_signed_manifest(signing_bytes: &[u8], signature: &[u8; 64]) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.signed-trust-manifest.v1".to_vec();
    bytes.extend_from_slice(signing_bytes);
    bytes.extend_from_slice(signature);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::AuthenticatedPrincipalV1;
    use crate::LearningEvidenceRoleV1;
    use crate::TrustedLearningSignerV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn signed_manifest() -> (LearningTrustRootV1, SignedLearningTrustManifestV1) {
        let root_key = SigningKey::from_bytes(&[9_u8; 32]);
        let signer_key = SigningKey::from_bytes(&[7_u8; 32]);
        let scope = digest("scope");
        let objective = digest("objective");
        let root = LearningTrustRootV1 {
            root_id: id("root"),
            verifying_key: root_key.verifying_key().to_bytes(),
            scope_digest: scope,
            objective_digest: objective,
            minimum_authority_epoch: 3,
        };
        let principal = AuthenticatedPrincipalV1 {
            principal_id: id("observer"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: Digest32::of_bytes(&signer_key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 3,
            authenticated_at: 10,
            expires_at: 100,
        };
        let mut manifest = SignedLearningTrustManifestV1 {
            manifest_id: id("manifest-1"),
            root_id: id("root"),
            generation: 1,
            predecessor_manifest_digest: None,
            issued_at: 10,
            expires_at: 100,
            trust: LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: objective,
                authority_epoch: 3,
                signers: vec![TrustedLearningSignerV1 {
                    principal,
                    controller_id: id("observer-controller"),
                    verifying_key: signer_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Observer],
                    revoked_at: None,
                }],
            },
            signature: [0_u8; 64],
        };
        let payload = trust_manifest_signing_bytes(&manifest).expect("payload");
        manifest.signature = root_key.sign(&payload).to_bytes();
        (root, manifest)
    }

    #[test]
    fn pinned_root_admits_signed_signer_distribution() {
        let (root, manifest) = signed_manifest();
        let verified =
            verify_learning_trust_manifest(&root, manifest, None, 50).expect("signed trust manifest");
        assert_eq!(verified.generation, 1);
        assert!(!verified.manifest_digest.is_zero());
        assert!(!verified.trust_digest.is_zero());
    }

    #[test]
    fn manifest_cannot_replace_pinned_root() {
        let (root, mut manifest) = signed_manifest();
        manifest.root_id = id("attacker-root");
        assert!(matches!(
            verify_learning_trust_manifest(&root, manifest, None, 50),
            Err(TrustRootError::RootMismatch)
        ));
    }
}
