//! Versioned historical admission evidence owned by the RunStart journal.
//!
//! This is deliberately not `ObjectiveAdmissionProofV1`: decoding persisted
//! bytes never reconstructs the compiler's opaque admission capability and
//! never authenticates a source or grants final-use authority. The compiler
//! owns the frozen canonical encoding; the destination checks that encoding
//! and binds it to the same immutable admission and checkpointed record.

use codex_hepta_types::Digest32;

use super::RunStartStoreError;

const DOMAIN: &[u8] = b"hepta.objective.admission-proof.v1";
pub(super) const CANONICAL_BYTES: usize = DOMAIN.len() + 5 * 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartAdmissionProofV1 {
    bytes: [u8; CANONICAL_BYTES],
    digest: Digest32,
}

impl RunStartAdmissionProofV1 {
    /// Decode integrity evidence, not an authenticated compiler capability.
    /// Unknown versions, zero identities, extra bytes and digest drift fail
    /// closed. There is no legacy-proof synthesis or implicit migration.
    pub fn from_canonical_bytes(
        bytes: &[u8],
        digest: Digest32,
    ) -> Result<Self, RunStartStoreError> {
        let bytes: [u8; CANONICAL_BYTES] = bytes
            .try_into()
            .map_err(|_| RunStartStoreError::InvalidSnapshot("objectiveAdmissionProof"))?;
        if !bytes.starts_with(DOMAIN)
            || digest.is_zero()
            || Digest32::of_bytes(&bytes) != digest
            || bytes[DOMAIN.len()..]
                .chunks_exact(32)
                .any(|identity| identity.iter().all(|byte| *byte == 0))
        {
            return Err(RunStartStoreError::InvalidSnapshot(
                "objectiveAdmissionProof",
            ));
        }
        Ok(Self { bytes, digest })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn source_envelope_digest(&self) -> Digest32 {
        self.identity(0)
    }

    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        self.identity(1)
    }

    #[must_use]
    pub fn authentication_context_digest(&self) -> Digest32 {
        self.identity(2)
    }

    #[must_use]
    pub fn compiler_contract_digest(&self) -> Digest32 {
        self.identity(3)
    }

    #[must_use]
    pub fn admitted_source_digest(&self) -> Digest32 {
        self.identity(4)
    }

    pub(super) fn validate_binding(
        &self,
        profile_digest: Digest32,
        admitted_source_digest: Digest32,
    ) -> Result<(), RunStartStoreError> {
        if self.profile_digest() != profile_digest
            || self.admitted_source_digest() != admitted_source_digest
        {
            return Err(RunStartStoreError::InvalidSnapshot(
                "objectiveAdmissionProofBinding",
            ));
        }
        Ok(())
    }

    fn identity(&self, index: usize) -> Digest32 {
        let start = DOMAIN.len() + index * 32;
        let mut bytes = [0; 32];
        bytes.copy_from_slice(&self.bytes[start..start + 32]);
        Digest32::from_array(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn canonical() -> Vec<u8> {
        let mut bytes = DOMAIN.to_vec();
        for byte in 1..=5 {
            bytes.extend_from_slice(&[byte; 32]);
        }
        bytes
    }

    #[test]
    fn run_start_proof_retains_exact_canonical_identities() {
        let bytes = canonical();
        let digest = Digest32::of_bytes(&bytes);
        let proof = RunStartAdmissionProofV1::from_canonical_bytes(&bytes, digest)
            .unwrap_or_else(|error| panic!("historical integrity evidence: {error:?}"));
        assert_eq!(proof.canonical_bytes(), bytes);
        assert_eq!(proof.digest(), digest);
        assert_eq!(
            proof.source_envelope_digest(),
            Digest32::from_array([1; 32])
        );
        assert_eq!(proof.profile_digest(), Digest32::from_array([2; 32]));
        assert_eq!(
            proof.authentication_context_digest(),
            Digest32::from_array([3; 32])
        );
        assert_eq!(
            proof.compiler_contract_digest(),
            Digest32::from_array([4; 32])
        );
        assert_eq!(
            proof.admitted_source_digest(),
            Digest32::from_array([5; 32])
        );
        assert!(
            proof
                .validate_binding(Digest32::from_array([2; 32]), Digest32::from_array([5; 32]))
                .is_ok()
        );
        assert!(
            proof
                .validate_binding(Digest32::from_array([7; 32]), Digest32::from_array([5; 32]))
                .is_err()
        );
        assert!(
            proof
                .validate_binding(Digest32::from_array([2; 32]), Digest32::from_array([7; 32]))
                .is_err()
        );
    }

    #[test]
    fn run_start_proof_rejects_version_length_zero_and_tamper() {
        let bytes = canonical();
        let digest = Digest32::of_bytes(&bytes);
        for index in 0..bytes.len() {
            let mut changed = bytes.clone();
            changed[index] ^= 1;
            assert!(RunStartAdmissionProofV1::from_canonical_bytes(&changed, digest).is_err());
        }
        for length in 0..bytes.len() {
            let truncated = &bytes[..length];
            assert!(
                RunStartAdmissionProofV1::from_canonical_bytes(
                    truncated,
                    Digest32::of_bytes(truncated),
                )
                .is_err()
            );
        }
        let mut extra = bytes.clone();
        extra.push(0);
        assert!(
            RunStartAdmissionProofV1::from_canonical_bytes(&extra, Digest32::of_bytes(&extra))
                .is_err()
        );
        let mut successor = bytes.clone();
        successor[DOMAIN.len() - 1] = b'2';
        assert!(
            RunStartAdmissionProofV1::from_canonical_bytes(
                &successor,
                Digest32::of_bytes(&successor),
            )
            .is_err()
        );
        for index in 0..5 {
            let mut zero = bytes.clone();
            zero[DOMAIN.len() + index * 32..DOMAIN.len() + (index + 1) * 32].fill(0);
            assert!(
                RunStartAdmissionProofV1::from_canonical_bytes(&zero, Digest32::of_bytes(&zero))
                    .is_err()
            );
        }
    }
}
