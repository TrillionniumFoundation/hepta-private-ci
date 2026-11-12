//! Fixed native HEAD enrollment and pure verification of untrusted source bytes.
//! None of these values grants a writer continuation, lifecycle acceptance,
//! selection or FinalUse. Only the original process-pinned source can establish
//! that a decoded observation came from a current physical writer read.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::ArtifactOwnerHostError as Error;
use super::ArtifactOwnerTrustV1;
use super::ArtifactOwnerVerifierV1;
use super::SignedArtifactWriterLeaseV1;
use super::SignedCurrentArtifactHeadV1;
use super::push_id;
use super::verify_signer_context;
use crate::OriginalArtifactPublicationContextV1;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessV1;
use crate::verify_artifact_admission_v3;

#[path = "owner_head_source_claims.rs"]
mod claims;
pub use claims::UntrustedArtifactRegistryDurableV1;
#[path = "owner_head_source_codec.rs"]
mod codec;
pub use codec::decode_artifact_head_bytes_v1;
pub use codec::encode_artifact_head_bytes_v1;

/// Native original-host configuration, never an enrollment or key request.
/// The complete original writer lease and head enrollment are fixed before a
/// purpose stream is admitted. The signature's expiry cannot be renewed later.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactHeadSigningConfigV1 {
    pub publication: OriginalArtifactPublicationContextV1,
    pub trust: ArtifactOwnerTrustV1,
    pub writer_lease: SignedArtifactWriterLeaseV1,
    pub storage_binding: Digest32,
    pub signer_id: StableId,
    pub authority_epoch: u64,
    pub signature_expires_at: u64,
}

impl ArtifactHeadSigningConfigV1 {
    /// Pure fixed-context digest; this does not validate current authority.
    pub fn binding(&self) -> Result<Digest32, Error> {
        let verifier = ArtifactOwnerVerifierV1::new(self.trust.clone())?;
        let mut bytes = b"hepta.original-artifact-head-native.v1".to_vec();
        bytes.extend_from_slice(verifier.trust_digest().as_array());
        bytes.extend_from_slice(self.storage_binding.as_array());
        bytes.extend_from_slice(self.writer_lease_digest().as_array());
        bytes.extend_from_slice(crate::publication::digest_intent(
            &self.publication.operation_id,
            &self.publication.admission,
            self.publication.expected_registry_predecessor_head,
        ).as_array());
        push_id(&mut bytes, &self.signer_id);
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.signature_expires_at.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn writer_lease_digest(&self) -> Digest32 {
        let mut bytes = self.writer_lease.signing_bytes();
        bytes.extend_from_slice(&self.writer_lease.signature);
        Digest32::of_bytes(&bytes)
    }

    /// Verify the complete original registration, lease and fixed window.
    /// This pure method cannot make an untrusted DTO into original custody.
    pub fn authenticate_current(&self, now: u64) -> Result<(), Error> {
        let verifier = ArtifactOwnerVerifierV1::new(self.trust.clone())?;
        let writer = verifier.verify_writer_lease(&self.writer_lease, now)?;
        let manifest = &self.publication.admission.validated_manifest.manifest;
        if self.storage_binding.is_zero()
            || manifest.producer_id != writer.producer_id
            || self.publication.admission.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || self.signer_id == writer.producer_id
            || self.signature_expires_at < now
            || self.signature_expires_at > self.writer_lease.expires_at
            || self.signature_expires_at > manifest.expires_at
            || self.authority_epoch < self.trust.minimum_authority_epoch
        {
            return Err(Error::WriterLeaseContext);
        }
        verify_artifact_admission_v3(
            &self.publication.admission,
            self.publication.admission.withdrawal_head_digest,
            now,
        ).map_err(|_| Error::CheckpointMismatch)?;
        let signer = verifier.head_signers.get(&self.signer_id).ok_or(Error::UnknownSigner)?;
        if self.signature_expires_at > signer.expires_at
            || signer.revoked_at.is_some_and(|at| self.signature_expires_at >= at)
            || self.trust.writer_signers.iter().any(|writer| {
                writer.signer_id == signer.signer_id || writer.verifying_key == signer.verifying_key
            })
        {
            return Err(Error::SignerContext);
        }
        verify_signer_context(
            signer, Digest32::of_bytes(&signer.verifying_key), self.authority_epoch,
            now, now, /*require_current*/ true,
        )
    }

    /// Compare a native already-held key with the original registered key.
    /// No key bytes are generated, enrolled, returned or transported here.
    pub fn require_registered_key(&self, verifying_key: &[u8; 32], now: u64) -> Result<(), Error> {
        self.authenticate_current(now)?;
        let signer = self.trust.head_signers.iter().find(|entry| entry.signer_id == self.signer_id)
            .ok_or(Error::UnknownSigner)?;
        if &signer.verifying_key != verifying_key { return Err(Error::InvalidKey); }
        Ok(())
    }

    /// Derive only the exact unsigned HEAD of a validated source observation.
    /// A caller-created observation still provides no native signing custody.
    pub fn unsigned_head(
        &self, source: &UntrustedArtifactRegistryDurableV1, issued_at: u64,
    ) -> Result<SignedCurrentArtifactHeadV1, Error> {
        source.authenticate_current(self, issued_at)?;
        let generation = self.expected_generation(source)?;
        let signer = self.trust.head_signers.iter().find(|entry| entry.signer_id == self.signer_id)
            .ok_or(Error::UnknownSigner)?;
        Ok(SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.trust.withdrawal_scope_digest,
            binding: self.storage_binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: self.trust.registry_id.clone(),
                generation,
                head_digest: source.registry_receipt().head_digest,
                predecessor_head_digest: self.publication.expected_registry_predecessor_head,
                authority_epoch: self.authority_epoch,
                signer_id: self.signer_id.clone(),
                signing_key_digest: Digest32::of_bytes(&signer.verifying_key),
                issued_at,
                expires_at: self.signature_expires_at,
            },
            signature: [0; 64],
        })
    }

    pub fn verify_original_head(
        &self, source: &UntrustedArtifactRegistryDurableV1,
        signed: &SignedCurrentArtifactHeadV1, now: u64,
    ) -> Result<(), Error> {
        source.authenticate_current(self, now)?;
        if signed.witness.issued_at > now {
            return Err(Error::CurrentHeadContext);
        }
        // Reconstruct immutable fields without treating the old issued_at as
        // a fresh physical read or changing the original signed window.
        let signer = self.trust.head_signers.iter().find(|entry| entry.signer_id == self.signer_id)
            .ok_or(Error::UnknownSigner)?;
        if signed.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || signed.binding != self.storage_binding
            || signed.witness.registry_id != self.trust.registry_id
            || signed.witness.generation != self.expected_generation(source)?
            || signed.witness.head_digest != source.registry_receipt().head_digest
            || signed.witness.predecessor_head_digest != self.publication.expected_registry_predecessor_head
            || signed.witness.authority_epoch != self.authority_epoch
            || signed.witness.signer_id != self.signer_id
            || signed.witness.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
            || signed.witness.expires_at != self.signature_expires_at
        {
            return Err(Error::CurrentHeadContext);
        }
        if let Some(current) = source.current_head()
            && current.witness.head_digest == source.registry_receipt().head_digest
            && current != signed
        {
            return Err(Error::CurrentHeadConflict);
        }
        let verifier = ArtifactOwnerVerifierV1::new(self.trust.clone())?;
        verifier.verify_signed_head(signed, &RegistryHeadRequirementV1 {
            registry_id: self.trust.registry_id.clone(),
            minimum_generation: signed.witness.generation,
            expected_predecessor_head_digest: self.publication.expected_registry_predecessor_head,
            minimum_authority_epoch: self.trust.minimum_authority_epoch,
            now,
        }, /*require_current_signer*/ true)?;
        Ok(())
    }

    fn expected_generation(&self, source: &UntrustedArtifactRegistryDurableV1) -> Result<Generation, Error> {
        match source.current_head() {
            Some(current) if current.witness.head_digest == source.registry_receipt().head_digest => {
                Ok(current.witness.generation)
            }
            Some(current) if current.witness.head_digest == self.publication.expected_registry_predecessor_head => {
                if self.authority_epoch < current.witness.authority_epoch { return Err(Error::SignerContext); }
                current.witness.generation.next().map_err(|_| Error::CurrentHeadContext)
            }
            None if self.publication.expected_registry_predecessor_head == self.trust.genesis_predecessor_head_digest => {
                Ok(self.trust.minimum_registry_generation)
            }
            Some(_) | None => Err(Error::CurrentHeadConflict),
        }
    }
}
