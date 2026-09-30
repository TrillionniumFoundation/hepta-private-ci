use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::NduHierarchySnapshotProofV1;
use crate::SubjectClass;

const MAX_HIERARCHY_DEPTH: usize = 4;
const MAX_IDENTIFIER_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduAuthorityKeyStateV2 {
    Active,
    Revoked,
    Retired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduHierarchyAuthorityErrorV2 {
    EmptyDigest(&'static str),
    EmptyIdentifier(&'static str),
    IdentifierTooLong(&'static str),
    InvalidPath,
    InvalidValidityWindow,
    InvalidKey,
    KeyMismatch,
    KeyNotActive,
    KeyOutsideValidity,
    TrustRootRevisionMismatch,
    RevocationFrontierMismatch,
    Signature,
    ProofDigest,
}

impl fmt::Display for NduHierarchyAuthorityErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduHierarchyAuthorityErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduHierarchyAuthorityKeyV2 {
    key_id: StableId,
    key_epoch: Generation,
    verifying_key: [u8; 32],
    state: NduAuthorityKeyStateV2,
    not_before_ms: u64,
    not_after_ms: u64,
    trust_root_revision: u64,
    revocation_frontier_digest: Digest32,
    record_digest: Digest32,
}

impl NduHierarchyAuthorityKeyV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        key_id: StableId,
        key_epoch: Generation,
        verifying_key: [u8; 32],
        state: NduAuthorityKeyStateV2,
        not_before_ms: u64,
        not_after_ms: u64,
        trust_root_revision: u64,
        revocation_frontier_digest: Digest32,
    ) -> Result<Self, NduHierarchyAuthorityErrorV2> {
        if not_before_ms >= not_after_ms || trust_root_revision == 0 {
            return Err(NduHierarchyAuthorityErrorV2::InvalidValidityWindow);
        }
        require_digest(revocation_frontier_digest, "revocation frontier")?;
        VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| NduHierarchyAuthorityErrorV2::InvalidKey)?;
        let record_digest = digest_key_record(
            &key_id,
            key_epoch,
            &verifying_key,
            state,
            not_before_ms,
            not_after_ms,
            trust_root_revision,
            revocation_frontier_digest,
        );
        Ok(Self {
            key_id,
            key_epoch,
            verifying_key,
            state,
            not_before_ms,
            not_after_ms,
            trust_root_revision,
            revocation_frontier_digest,
            record_digest,
        })
    }

    #[must_use]
    pub fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn key_epoch(&self) -> Generation {
        self.key_epoch
    }

    #[must_use]
    pub const fn state(&self) -> NduAuthorityKeyStateV2 {
        self.state
    }

    #[must_use]
    pub const fn trust_root_revision(&self) -> u64 {
        self.trust_root_revision
    }

    #[must_use]
    pub const fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub const fn record_digest(&self) -> Digest32 {
        self.record_digest
    }

    pub fn validate(&self) -> Result<(), NduHierarchyAuthorityErrorV2> {
        let rebuilt = Self::new(
            self.key_id.clone(),
            self.key_epoch,
            self.verifying_key,
            self.state,
            self.not_before_ms,
            self.not_after_ms,
            self.trust_root_revision,
            self.revocation_frontier_digest,
        )?;
        if rebuilt.record_digest != self.record_digest {
            return Err(NduHierarchyAuthorityErrorV2::ProofDigest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSignedHierarchyClaimsV2 {
    pub hierarchy_id: String,
    pub canonical_path: Vec<String>,
    pub snapshot_digest: Digest32,
    pub subject_id: StableId,
    pub parent_subject_id: Option<StableId>,
    pub subject_class: SubjectClass,
    pub generation: Generation,
    pub key_id: StableId,
    pub key_epoch: Generation,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub trust_root_revision: u64,
    pub revocation_frontier_digest: Digest32,
}

impl NduSignedHierarchyClaimsV2 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, NduHierarchyAuthorityErrorV2> {
        self.validate_shape()?;
        let mut bytes = b"hepta.ndu.signed-hierarchy-proof.v2\0".to_vec();
        push_str(&mut bytes, &self.hierarchy_id)?;
        bytes.extend_from_slice(
            &u32::try_from(self.canonical_path.len())
                .map_err(|_| NduHierarchyAuthorityErrorV2::InvalidPath)?
                .to_be_bytes(),
        );
        for node in &self.canonical_path {
            push_str(&mut bytes, node)?;
        }
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        push_id(&mut bytes, &self.subject_id)?;
        match &self.parent_subject_id {
            Some(parent) => {
                bytes.push(1);
                push_id(&mut bytes, parent)?;
            }
            None => bytes.push(0),
        }
        bytes.push(self.subject_class.tag());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        push_id(&mut bytes, &self.key_id)?;
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&self.issued_at_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_ms.to_be_bytes());
        bytes.extend_from_slice(&self.trust_root_revision.to_be_bytes());
        bytes.extend_from_slice(self.revocation_frontier_digest.as_array());
        Ok(bytes)
    }

    fn validate_shape(&self) -> Result<(), NduHierarchyAuthorityErrorV2> {
        validate_identifier(&self.hierarchy_id, "hierarchy id")?;
        require_digest(self.snapshot_digest, "snapshot")?;
        require_digest(self.revocation_frontier_digest, "revocation frontier")?;
        if self.issued_at_ms >= self.expires_at_ms || self.trust_root_revision == 0 {
            return Err(NduHierarchyAuthorityErrorV2::InvalidValidityWindow);
        }
        let expected_depth = match self.subject_class {
            SubjectClass::System => 1,
            SubjectClass::Domain => 2,
            SubjectClass::Agent => 3,
            SubjectClass::Episode => 4,
        };
        if self.canonical_path.len() != expected_depth
            || self.canonical_path.is_empty()
            || self.canonical_path.len() > MAX_HIERARCHY_DEPTH
            || self.canonical_path.last().map(String::as_str) != Some(self.subject_id.as_str())
        {
            return Err(NduHierarchyAuthorityErrorV2::InvalidPath);
        }
        let expected_parent = self
            .canonical_path
            .len()
            .checked_sub(2)
            .and_then(|index| self.canonical_path.get(index))
            .map(String::as_str);
        if expected_parent != self.parent_subject_id.as_ref().map(StableId::as_str) {
            return Err(NduHierarchyAuthorityErrorV2::InvalidPath);
        }
        let mut seen = BTreeSet::new();
        for node in &self.canonical_path {
            validate_identifier(node, "hierarchy path node")?;
            if !seen.insert(node) {
                return Err(NduHierarchyAuthorityErrorV2::InvalidPath);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSignedHierarchyProofV2 {
    claims: NduSignedHierarchyClaimsV2,
    signature: [u8; 64],
    proof_digest: Digest32,
}

impl NduSignedHierarchyProofV2 {
    pub fn from_signed_parts(
        claims: NduSignedHierarchyClaimsV2,
        signature: [u8; 64],
    ) -> Result<Self, NduHierarchyAuthorityErrorV2> {
        let signing_bytes = claims.signing_bytes()?;
        let proof_digest = Digest32::of_parts(&[
            b"hepta.ndu.signed-hierarchy-proof-envelope.v2\0",
            &signing_bytes,
            &signature,
        ]);
        Ok(Self {
            claims,
            signature,
            proof_digest,
        })
    }

    #[must_use]
    pub fn claims(&self) -> &NduSignedHierarchyClaimsV2 {
        &self.claims
    }

    #[must_use]
    pub const fn signature(&self) -> &[u8; 64] {
        &self.signature
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    pub fn verify(
        &self,
        authority: &NduHierarchyAuthorityKeyV2,
        trusted_now_ms: u64,
        current_trust_root_revision: u64,
        current_revocation_frontier_digest: Digest32,
    ) -> Result<NduHierarchySnapshotProofV1, NduHierarchyAuthorityErrorV2> {
        authority.validate()?;
        let signing_bytes = self.claims.signing_bytes()?;
        if authority.state != NduAuthorityKeyStateV2::Active {
            return Err(NduHierarchyAuthorityErrorV2::KeyNotActive);
        }
        if self.claims.key_id != authority.key_id
            || self.claims.key_epoch != authority.key_epoch
        {
            return Err(NduHierarchyAuthorityErrorV2::KeyMismatch);
        }
        if trusted_now_ms < authority.not_before_ms
            || trusted_now_ms >= authority.not_after_ms
            || trusted_now_ms < self.claims.issued_at_ms
            || trusted_now_ms >= self.claims.expires_at_ms
        {
            return Err(NduHierarchyAuthorityErrorV2::KeyOutsideValidity);
        }
        if self.claims.trust_root_revision != current_trust_root_revision
            || authority.trust_root_revision != current_trust_root_revision
        {
            return Err(NduHierarchyAuthorityErrorV2::TrustRootRevisionMismatch);
        }
        if self.claims.revocation_frontier_digest != current_revocation_frontier_digest
            || authority.revocation_frontier_digest != current_revocation_frontier_digest
        {
            return Err(NduHierarchyAuthorityErrorV2::RevocationFrontierMismatch);
        }
        VerifyingKey::from_bytes(&authority.verifying_key)
            .map_err(|_| NduHierarchyAuthorityErrorV2::InvalidKey)?
            .verify_strict(&signing_bytes, &Signature::from_bytes(&self.signature))
            .map_err(|_| NduHierarchyAuthorityErrorV2::Signature)?;
        let expected_digest = Digest32::of_parts(&[
            b"hepta.ndu.signed-hierarchy-proof-envelope.v2\0",
            &signing_bytes,
            &self.signature,
        ]);
        if expected_digest != self.proof_digest {
            return Err(NduHierarchyAuthorityErrorV2::ProofDigest);
        }
        NduHierarchySnapshotProofV1::new(
            self.claims.hierarchy_id.clone(),
            self.claims.canonical_path.clone(),
            self.claims.snapshot_digest,
        )
        .map_err(|_| NduHierarchyAuthorityErrorV2::InvalidPath)
    }
}

fn digest_key_record(
    key_id: &StableId,
    key_epoch: Generation,
    verifying_key: &[u8; 32],
    state: NduAuthorityKeyStateV2,
    not_before_ms: u64,
    not_after_ms: u64,
    trust_root_revision: u64,
    revocation_frontier_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.hierarchy-authority-key.v2\0".to_vec();
    push_id_infallible(&mut bytes, key_id);
    bytes.extend_from_slice(&key_epoch.get().to_be_bytes());
    bytes.extend_from_slice(verifying_key);
    bytes.push(match state {
        NduAuthorityKeyStateV2::Active => 1,
        NduAuthorityKeyStateV2::Revoked => 2,
        NduAuthorityKeyStateV2::Retired => 3,
    });
    bytes.extend_from_slice(&not_before_ms.to_be_bytes());
    bytes.extend_from_slice(&not_after_ms.to_be_bytes());
    bytes.extend_from_slice(&trust_root_revision.to_be_bytes());
    bytes.extend_from_slice(revocation_frontier_digest.as_array());
    Digest32::of_bytes(&bytes)
}


fn push_id_infallible(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduHierarchyAuthorityErrorV2> {
    if value.is_zero() {
        return Err(NduHierarchyAuthorityErrorV2::EmptyDigest(field));
    }
    Ok(())
}

fn validate_identifier(
    value: &str,
    field: &'static str,
) -> Result<(), NduHierarchyAuthorityErrorV2> {
    if value.is_empty() {
        return Err(NduHierarchyAuthorityErrorV2::EmptyIdentifier(field));
    }
    if value.len() > MAX_IDENTIFIER_BYTES || !value.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(NduHierarchyAuthorityErrorV2::IdentifierTooLong(field));
    }
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), NduHierarchyAuthorityErrorV2> {
    push_str(bytes, value.as_str())
}

fn push_str(
    bytes: &mut Vec<u8>,
    value: &str,
) -> Result<(), NduHierarchyAuthorityErrorV2> {
    validate_identifier(value, "canonical string")?;
    let length = u32::try_from(value.len())
        .map_err(|_| NduHierarchyAuthorityErrorV2::IdentifierTooLong("canonical string"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::expect_used)]
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[test]
    fn verifies_signature_time_key_and_revocation_frontier() {
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let key = NduHierarchyAuthorityKeyV2::new(
            id("ndu-hierarchy-key"),
            Generation::new(3).expect("generation"),
            signing.verifying_key().to_bytes(),
            NduAuthorityKeyStateV2::Active,
            100,
            1_000,
            11,
            digest(b"frontier"),
        )
        .expect("key");
        let claims = NduSignedHierarchyClaimsV2 {
            hierarchy_id: "primary".to_string(),
            canonical_path: vec!["system".to_string(), "domain".to_string()],
            snapshot_digest: digest(b"snapshot"),
            subject_id: id("domain"),
            parent_subject_id: Some(id("system")),
            subject_class: SubjectClass::Domain,
            generation: Generation::new(8).expect("generation"),
            key_id: id("ndu-hierarchy-key"),
            key_epoch: Generation::new(3).expect("generation"),
            issued_at_ms: 200,
            expires_at_ms: 800,
            trust_root_revision: 11,
            revocation_frontier_digest: digest(b"frontier"),
        };
        let signature = signing.sign(&claims.signing_bytes().expect("bytes")).to_bytes();
        let proof = NduSignedHierarchyProofV2::from_signed_parts(claims, signature).expect("proof");
        proof
            .verify(&key, 400, 11, digest(b"frontier"))
            .expect("verified proof");
    }

    #[test]
    fn rejects_revoked_key_and_stale_frontier() {
        let signing = SigningKey::from_bytes(&[9_u8; 32]);
        let key = NduHierarchyAuthorityKeyV2::new(
            id("ndu-hierarchy-key"),
            Generation::new(1).expect("generation"),
            signing.verifying_key().to_bytes(),
            NduAuthorityKeyStateV2::Revoked,
            1,
            1_000,
            1,
            digest(b"frontier-a"),
        )
        .expect("key");
        let claims = NduSignedHierarchyClaimsV2 {
            hierarchy_id: "primary".to_string(),
            canonical_path: vec!["system".to_string()],
            snapshot_digest: digest(b"snapshot"),
            subject_id: id("system"),
            parent_subject_id: None,
            subject_class: SubjectClass::System,
            generation: Generation::new(1).expect("generation"),
            key_id: id("ndu-hierarchy-key"),
            key_epoch: Generation::new(1).expect("generation"),
            issued_at_ms: 10,
            expires_at_ms: 900,
            trust_root_revision: 1,
            revocation_frontier_digest: digest(b"frontier-a"),
        };
        let signature = signing.sign(&claims.signing_bytes().expect("bytes")).to_bytes();
        let proof = NduSignedHierarchyProofV2::from_signed_parts(claims, signature).expect("proof");
        assert_eq!(
            proof.verify(&key, 100, 1, digest(b"frontier-b")),
            Err(NduHierarchyAuthorityErrorV2::KeyNotActive)
        );
    }
}
