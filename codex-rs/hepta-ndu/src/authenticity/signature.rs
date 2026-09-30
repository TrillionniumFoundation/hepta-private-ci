use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};
use ed25519_dalek::{Signature, VerifyingKey};

use crate::{
    NduDurableProjectionArtifactV2, NduHierarchySnapshotProofV1,
    NduProjectionArtifactKindV2, SubjectClass,
};

use super::{
    push_id, push_string, require_digest, validate_window,
    NduAuthenticityError, NduImmutableLocatorV2,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAuthorityTrustBindingV2 {
    key_id: StableId,
    verifying_key_bytes: [u8; 32],
    valid_from_ms: u64,
    valid_until_ms: u64,
    trust_revision: u64,
    policy_digest: Digest32,
    binding_digest: Digest32,
}

impl NduAuthorityTrustBindingV2 {
    pub fn new(
        key_id: StableId,
        verifying_key_bytes: [u8; 32],
        valid_from_ms: u64,
        valid_until_ms: u64,
        trust_revision: u64,
        policy_digest: Digest32,
    ) -> Result<Self, NduAuthenticityError> {
        validate_window(valid_from_ms, valid_until_ms)?;
        if trust_revision == 0 {
            return Err(NduAuthenticityError::InvalidTrustRevision);
        }
        require_digest(policy_digest, "trust policy")?;
        VerifyingKey::from_bytes(&verifying_key_bytes)
            .map_err(|_| NduAuthenticityError::InvalidKey)?;
        let binding_digest = digest_trust_binding(
            &key_id,
            &verifying_key_bytes,
            valid_from_ms,
            valid_until_ms,
            trust_revision,
            policy_digest,
        );
        Ok(Self {
            key_id,
            verifying_key_bytes,
            valid_from_ms,
            valid_until_ms,
            trust_revision,
            policy_digest,
            binding_digest,
        })
    }

    #[must_use]
    pub fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn verifying_key_bytes(&self) -> &[u8; 32] {
        &self.verifying_key_bytes
    }

    #[must_use]
    pub const fn valid_from_ms(&self) -> u64 {
        self.valid_from_ms
    }

    #[must_use]
    pub const fn valid_until_ms(&self) -> u64 {
        self.valid_until_ms
    }

    #[must_use]
    pub const fn trust_revision(&self) -> u64 {
        self.trust_revision
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduAuthenticityError> {
        let rebuilt = Self::new(
            self.key_id.clone(),
            self.verifying_key_bytes,
            self.valid_from_ms,
            self.valid_until_ms,
            self.trust_revision,
            self.policy_digest,
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduAuthenticityError::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSignedHierarchyProofV2 {
    proof: NduHierarchySnapshotProofV1,
    subject_id: StableId,
    parent_subject_id: Option<StableId>,
    subject_class: SubjectClass,
    generation: Generation,
    issued_at_ms: u64,
    expires_at_ms: u64,
    revocation_epoch: u64,
    revocation_frontier_digest: Digest32,
    policy_digest: Digest32,
    signer_key_id: StableId,
    payload_digest: Digest32,
    signature: [u8; 64],
    receipt_digest: Digest32,
}

impl NduSignedHierarchyProofV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn signing_bytes(
        proof: &NduHierarchySnapshotProofV1,
        subject_id: &StableId,
        parent_subject_id: Option<&StableId>,
        subject_class: SubjectClass,
        generation: Generation,
        issued_at_ms: u64,
        expires_at_ms: u64,
        revocation_epoch: u64,
        revocation_frontier_digest: Digest32,
        policy_digest: Digest32,
        signer_key_id: &StableId,
    ) -> Result<Vec<u8>, NduAuthenticityError> {
        proof
            .validate_subject(subject_id, parent_subject_id, subject_class)
            .map_err(|_| NduAuthenticityError::HierarchyProofInvalid)?;
        validate_window(issued_at_ms, expires_at_ms)?;
        if revocation_epoch == 0 {
            return Err(NduAuthenticityError::RevocationEpochMismatch);
        }
        require_digest(revocation_frontier_digest, "revocation frontier")?;
        require_digest(policy_digest, "hierarchy policy")?;
        let mut bytes = b"hepta.ndu.signed-hierarchy-proof.v2\0".to_vec();
        push_string(&mut bytes, proof.hierarchy_id());
        bytes.extend_from_slice(
            &u32::try_from(proof.canonical_path().len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for node in proof.canonical_path() {
            push_string(&mut bytes, node);
        }
        bytes.extend_from_slice(proof.snapshot_digest().as_array());
        bytes.extend_from_slice(proof.proof_digest().as_array());
        push_id(&mut bytes, subject_id);
        match parent_subject_id {
            Some(parent) => {
                bytes.push(1);
                push_id(&mut bytes, parent);
            }
            None => bytes.push(0),
        }
        bytes.push(subject_class_tag(subject_class));
        bytes.extend_from_slice(&generation.get().to_be_bytes());
        bytes.extend_from_slice(&issued_at_ms.to_be_bytes());
        bytes.extend_from_slice(&expires_at_ms.to_be_bytes());
        bytes.extend_from_slice(&revocation_epoch.to_be_bytes());
        bytes.extend_from_slice(revocation_frontier_digest.as_array());
        bytes.extend_from_slice(policy_digest.as_array());
        push_id(&mut bytes, signer_key_id);
        Ok(bytes)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn from_signature(
        proof: NduHierarchySnapshotProofV1,
        subject_id: StableId,
        parent_subject_id: Option<StableId>,
        subject_class: SubjectClass,
        generation: Generation,
        issued_at_ms: u64,
        expires_at_ms: u64,
        revocation_epoch: u64,
        revocation_frontier_digest: Digest32,
        policy_digest: Digest32,
        signer_key_id: StableId,
        signature: [u8; 64],
    ) -> Result<Self, NduAuthenticityError> {
        let payload = Self::signing_bytes(
            &proof,
            &subject_id,
            parent_subject_id.as_ref(),
            subject_class,
            generation,
            issued_at_ms,
            expires_at_ms,
            revocation_epoch,
            revocation_frontier_digest,
            policy_digest,
            &signer_key_id,
        )?;
        if signature == [0; 64] {
            return Err(NduAuthenticityError::InvalidSignature);
        }
        let payload_digest = Digest32::of_bytes(&payload);
        let receipt_digest = digest_signed_receipt(
            b"hepta.ndu.signed-hierarchy-receipt.v2\0",
            payload_digest,
            &signature,
        );
        Ok(Self {
            proof,
            subject_id,
            parent_subject_id,
            subject_class,
            generation,
            issued_at_ms,
            expires_at_ms,
            revocation_epoch,
            revocation_frontier_digest,
            policy_digest,
            signer_key_id,
            payload_digest,
            signature,
            receipt_digest,
        })
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify(
        &self,
        trust: &NduAuthorityTrustBindingV2,
        trusted_now_ms: u64,
        current_revocation_epoch: u64,
        current_revocation_frontier_digest: Digest32,
    ) -> Result<NduVerifiedHierarchyProofV2, NduAuthenticityError> {
        verify_common(
            trust,
            &self.signer_key_id,
            self.policy_digest,
            self.issued_at_ms,
            self.expires_at_ms,
            self.revocation_epoch,
            self.revocation_frontier_digest,
            trusted_now_ms,
            current_revocation_epoch,
            current_revocation_frontier_digest,
        )?;
        let payload = Self::signing_bytes(
            &self.proof,
            &self.subject_id,
            self.parent_subject_id.as_ref(),
            self.subject_class,
            self.generation,
            self.issued_at_ms,
            self.expires_at_ms,
            self.revocation_epoch,
            self.revocation_frontier_digest,
            self.policy_digest,
            &self.signer_key_id,
        )?;
        verify_payload_and_receipt(
            trust,
            &payload,
            self.payload_digest,
            &self.signature,
            self.receipt_digest,
            b"hepta.ndu.signed-hierarchy-receipt.v2\0",
        )?;
        Ok(NduVerifiedHierarchyProofV2 {
            subject_id: self.subject_id.clone(),
            generation: self.generation,
            signed_receipt_digest: self.receipt_digest,
            trust_binding_digest: trust.binding_digest,
            valid_until_ms: self.expires_at_ms,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduVerifiedHierarchyProofV2 {
    subject_id: StableId,
    generation: Generation,
    signed_receipt_digest: Digest32,
    trust_binding_digest: Digest32,
    valid_until_ms: u64,
    authority: AuthorityPosture,
}

impl NduVerifiedHierarchyProofV2 {
    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn signed_receipt_digest(&self) -> Digest32 {
        self.signed_receipt_digest
    }

    #[must_use]
    pub const fn trust_binding_digest(&self) -> Digest32 {
        self.trust_binding_digest
    }

    #[must_use]
    pub const fn valid_until_ms(&self) -> u64 {
        self.valid_until_ms
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAuthenticatedProjectionArtifactV3 {
    artifact: NduDurableProjectionArtifactV2,
    immutable_locator: NduImmutableLocatorV2,
    issued_at_ms: u64,
    expires_at_ms: u64,
    revocation_epoch: u64,
    revocation_frontier_digest: Digest32,
    policy_digest: Digest32,
    signer_key_id: StableId,
    payload_digest: Digest32,
    signature: [u8; 64],
    receipt_digest: Digest32,
}

impl NduAuthenticatedProjectionArtifactV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn signing_bytes(
        artifact: &NduDurableProjectionArtifactV2,
        immutable_locator: &NduImmutableLocatorV2,
        issued_at_ms: u64,
        expires_at_ms: u64,
        revocation_epoch: u64,
        revocation_frontier_digest: Digest32,
        policy_digest: Digest32,
        signer_key_id: &StableId,
    ) -> Result<Vec<u8>, NduAuthenticityError> {
        artifact
            .validate()
            .map_err(|_| NduAuthenticityError::ArtifactBindingMismatch)?;
        immutable_locator.validate()?;
        if artifact.immutable_locator() != immutable_locator.locator()
            || artifact.projection_digest() != immutable_locator.content_digest()
        {
            return Err(NduAuthenticityError::ArtifactBindingMismatch);
        }
        validate_window(issued_at_ms, expires_at_ms)?;
        if revocation_epoch == 0 {
            return Err(NduAuthenticityError::RevocationEpochMismatch);
        }
        require_digest(revocation_frontier_digest, "revocation frontier")?;
        require_digest(policy_digest, "artifact policy")?;
        let mut bytes = b"hepta.ndu.authenticated-projection-artifact.v3\0".to_vec();
        bytes.push(artifact_kind_tag(artifact.projection_kind()));
        bytes.extend_from_slice(artifact.projection_digest().as_array());
        bytes.extend_from_slice(artifact.binding_digest().as_array());
        bytes.extend_from_slice(immutable_locator.binding_digest().as_array());
        bytes.extend_from_slice(&issued_at_ms.to_be_bytes());
        bytes.extend_from_slice(&expires_at_ms.to_be_bytes());
        bytes.extend_from_slice(&revocation_epoch.to_be_bytes());
        bytes.extend_from_slice(revocation_frontier_digest.as_array());
        bytes.extend_from_slice(policy_digest.as_array());
        push_id(&mut bytes, signer_key_id);
        Ok(bytes)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn from_signature(
        artifact: NduDurableProjectionArtifactV2,
        immutable_locator: NduImmutableLocatorV2,
        issued_at_ms: u64,
        expires_at_ms: u64,
        revocation_epoch: u64,
        revocation_frontier_digest: Digest32,
        policy_digest: Digest32,
        signer_key_id: StableId,
        signature: [u8; 64],
    ) -> Result<Self, NduAuthenticityError> {
        let payload = Self::signing_bytes(
            &artifact,
            &immutable_locator,
            issued_at_ms,
            expires_at_ms,
            revocation_epoch,
            revocation_frontier_digest,
            policy_digest,
            &signer_key_id,
        )?;
        if signature == [0; 64] {
            return Err(NduAuthenticityError::InvalidSignature);
        }
        let payload_digest = Digest32::of_bytes(&payload);
        let receipt_digest = digest_signed_receipt(
            b"hepta.ndu.authenticated-artifact-receipt.v3\0",
            payload_digest,
            &signature,
        );
        Ok(Self {
            artifact,
            immutable_locator,
            issued_at_ms,
            expires_at_ms,
            revocation_epoch,
            revocation_frontier_digest,
            policy_digest,
            signer_key_id,
            payload_digest,
            signature,
            receipt_digest,
        })
    }

    #[must_use]
    pub fn artifact(&self) -> &NduDurableProjectionArtifactV2 {
        &self.artifact
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub fn verify(
        &self,
        trust: &NduAuthorityTrustBindingV2,
        trusted_now_ms: u64,
        current_revocation_epoch: u64,
        current_revocation_frontier_digest: Digest32,
    ) -> Result<NduVerifiedProjectionArtifactV3, NduAuthenticityError> {
        verify_common(
            trust,
            &self.signer_key_id,
            self.policy_digest,
            self.issued_at_ms,
            self.expires_at_ms,
            self.revocation_epoch,
            self.revocation_frontier_digest,
            trusted_now_ms,
            current_revocation_epoch,
            current_revocation_frontier_digest,
        )?;
        let payload = Self::signing_bytes(
            &self.artifact,
            &self.immutable_locator,
            self.issued_at_ms,
            self.expires_at_ms,
            self.revocation_epoch,
            self.revocation_frontier_digest,
            self.policy_digest,
            &self.signer_key_id,
        )?;
        verify_payload_and_receipt(
            trust,
            &payload,
            self.payload_digest,
            &self.signature,
            self.receipt_digest,
            b"hepta.ndu.authenticated-artifact-receipt.v3\0",
        )?;
        Ok(NduVerifiedProjectionArtifactV3 {
            projection_digest: self.artifact.projection_digest(),
            artifact_binding_digest: self.artifact.binding_digest(),
            immutable_locator_binding_digest: self.immutable_locator.binding_digest(),
            signed_receipt_digest: self.receipt_digest,
            trust_binding_digest: trust.binding_digest,
            valid_until_ms: self.expires_at_ms,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduVerifiedProjectionArtifactV3 {
    projection_digest: Digest32,
    artifact_binding_digest: Digest32,
    immutable_locator_binding_digest: Digest32,
    signed_receipt_digest: Digest32,
    trust_binding_digest: Digest32,
    valid_until_ms: u64,
    authority: AuthorityPosture,
}

impl NduVerifiedProjectionArtifactV3 {
    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub const fn artifact_binding_digest(&self) -> Digest32 {
        self.artifact_binding_digest
    }

    #[must_use]
    pub const fn immutable_locator_binding_digest(&self) -> Digest32 {
        self.immutable_locator_binding_digest
    }

    #[must_use]
    pub const fn signed_receipt_digest(&self) -> Digest32 {
        self.signed_receipt_digest
    }

    #[must_use]
    pub const fn trust_binding_digest(&self) -> Digest32 {
        self.trust_binding_digest
    }

    #[must_use]
    pub const fn valid_until_ms(&self) -> u64 {
        self.valid_until_ms
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[allow(clippy::too_many_arguments)]
fn verify_common(
    trust: &NduAuthorityTrustBindingV2,
    signer_key_id: &StableId,
    policy_digest: Digest32,
    issued_at_ms: u64,
    expires_at_ms: u64,
    revocation_epoch: u64,
    revocation_frontier_digest: Digest32,
    trusted_now_ms: u64,
    current_revocation_epoch: u64,
    current_revocation_frontier_digest: Digest32,
) -> Result<(), NduAuthenticityError> {
    trust.validate()?;
    if trust.key_id != *signer_key_id {
        return Err(NduAuthenticityError::SignerMismatch);
    }
    if trust.policy_digest != policy_digest {
        return Err(NduAuthenticityError::PolicyMismatch);
    }
    if trusted_now_ms < issued_at_ms || trusted_now_ms < trust.valid_from_ms {
        return Err(NduAuthenticityError::NotYetValid);
    }
    if trusted_now_ms > expires_at_ms || trusted_now_ms > trust.valid_until_ms {
        return Err(NduAuthenticityError::Expired);
    }
    if revocation_epoch != current_revocation_epoch {
        return Err(NduAuthenticityError::RevocationEpochMismatch);
    }
    if revocation_frontier_digest != current_revocation_frontier_digest {
        return Err(NduAuthenticityError::RevocationFrontierMismatch);
    }
    Ok(())
}

fn verify_payload_and_receipt(
    trust: &NduAuthorityTrustBindingV2,
    payload: &[u8],
    payload_digest: Digest32,
    signature_bytes: &[u8; 64],
    receipt_digest: Digest32,
    receipt_domain: &[u8],
) -> Result<(), NduAuthenticityError> {
    if Digest32::of_bytes(payload) != payload_digest
        || digest_signed_receipt(receipt_domain, payload_digest, signature_bytes)
            != receipt_digest
    {
        return Err(NduAuthenticityError::ReceiptDigestMismatch);
    }
    let verifying_key = VerifyingKey::from_bytes(&trust.verifying_key_bytes)
        .map_err(|_| NduAuthenticityError::InvalidKey)?;
    let signature = Signature::from_bytes(signature_bytes);
    verifying_key
        .verify_strict(payload, &signature)
        .map_err(|_| NduAuthenticityError::InvalidSignature)
}

fn digest_trust_binding(
    key_id: &StableId,
    verifying_key_bytes: &[u8; 32],
    valid_from_ms: u64,
    valid_until_ms: u64,
    trust_revision: u64,
    policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authority-trust-binding.v2\0".to_vec();
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(verifying_key_bytes);
    bytes.extend_from_slice(&valid_from_ms.to_be_bytes());
    bytes.extend_from_slice(&valid_until_ms.to_be_bytes());
    bytes.extend_from_slice(&trust_revision.to_be_bytes());
    bytes.extend_from_slice(policy_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_signed_receipt(
    domain: &[u8],
    payload_digest: Digest32,
    signature: &[u8; 64],
) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(signature);
    Digest32::of_bytes(&bytes)
}

const fn subject_class_tag(subject_class: SubjectClass) -> u8 {
    match subject_class {
        SubjectClass::System => 0,
        SubjectClass::Domain => 1,
        SubjectClass::Agent => 2,
        SubjectClass::Episode => 3,
    }
}

const fn artifact_kind_tag(kind: NduProjectionArtifactKindV2) -> u8 {
    match kind {
        NduProjectionArtifactKindV2::Preference => 0,
        NduProjectionArtifactKindV2::Utility => 1,
        NduProjectionArtifactKindV2::Coefficient => 2,
    }
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::{Signer as _, SigningKey};

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn trust(
        signing: &SigningKey,
        policy: Digest32,
    ) -> NduAuthorityTrustBindingV2 {
        NduAuthorityTrustBindingV2::new(
            id("ndu-authority-key-1"),
            signing.verifying_key().to_bytes(),
            100,
            1_000,
            1,
            policy,
        )
        .expect("trust binding")
    }

    #[test]
    fn signed_hierarchy_requires_current_time_and_revocation_frontier() {
        let signing = SigningKey::from_bytes(&[7; 32]);
        let policy = digest("policy");
        let trust = trust(&signing, policy);
        let frontier = digest("frontier");
        let proof = NduHierarchySnapshotProofV1::new(
            "primary".to_string(),
            vec!["system".to_string(), "domain".to_string()],
            digest("snapshot"),
        )
        .expect("proof");
        let subject = id("domain");
        let parent = id("system");
        let generation = Generation::new(3).expect("generation");
        let bytes = NduSignedHierarchyProofV2::signing_bytes(
            &proof,
            &subject,
            Some(&parent),
            SubjectClass::Domain,
            generation,
            120,
            300,
            9,
            frontier,
            policy,
            trust.key_id(),
        )
        .expect("payload");
        let signed = NduSignedHierarchyProofV2::from_signature(
            proof,
            subject,
            Some(parent),
            SubjectClass::Domain,
            generation,
            120,
            300,
            9,
            frontier,
            policy,
            trust.key_id().clone(),
            signing.sign(&bytes).to_bytes(),
        )
        .expect("signed proof");
        let verified = signed.verify(&trust, 200, 9, frontier).expect("verified");
        assert_eq!(verified.authority(), AuthorityPosture::DENY_ALL);
        assert_eq!(
            signed.verify(&trust, 200, 10, frontier),
            Err(NduAuthenticityError::RevocationEpochMismatch)
        );
    }

    #[test]
    fn authenticated_artifact_binds_content_address_and_signature() {
        let signing = SigningKey::from_bytes(&[11; 32]);
        let policy = digest("artifact-policy");
        let trust = trust(&signing, policy);
        let content = digest("projection-bytes");
        let locator_text = format!(
            "artifact://sha256/{}",
            super::super::digest_hex(content)
        );
        let locator = NduImmutableLocatorV2::new(
            locator_text.clone(),
            content,
            None,
        )
        .expect("locator");
        let artifact = NduDurableProjectionArtifactV2::new(
            NduProjectionArtifactKindV2::Preference,
            content,
            locator_text,
            128,
            2,
            policy,
            digest("provenance"),
            4,
        )
        .expect("artifact");
        let frontier = digest("frontier");
        let bytes = NduAuthenticatedProjectionArtifactV3::signing_bytes(
            &artifact,
            &locator,
            120,
            300,
            9,
            frontier,
            policy,
            trust.key_id(),
        )
        .expect("payload");
        let signed = NduAuthenticatedProjectionArtifactV3::from_signature(
            artifact,
            locator,
            120,
            300,
            9,
            frontier,
            policy,
            trust.key_id().clone(),
            signing.sign(&bytes).to_bytes(),
        )
        .expect("signed artifact");
        let verified = signed.verify(&trust, 200, 9, frontier).expect("verified");
        assert_eq!(verified.projection_digest(), content);
    }
}
