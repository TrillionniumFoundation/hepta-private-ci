//! The original publication store has an immutable authentication namespace.
use super::*;

const MARKER: &str = "authentication.pq-v2";
const CONTENT: &[u8] = b"HEPTA-ARTIFACT-AUTH-MLDSA65-V2\n";

pub(super) fn verify_namespace(
    root: &Path,
    profile: LearningAuthenticationProfile,
) -> Result<(), ArtifactOwnerHostError> {
    let marker = root.join(MARKER);
    match (profile, fs::symlink_metadata(&marker)) {
        (LearningAuthenticationProfile::ClassicalV1, Err(error))
            if error.kind() == std::io::ErrorKind::NotFound =>
        {
            Ok(())
        }
        (LearningAuthenticationProfile::MlDsa65V2, Ok(metadata))
            if metadata.is_file() && metadata.len() == CONTENT.len() as u64 =>
        {
            let mut bytes = Vec::new();
            owner_observation::open_regular_existing(&marker, CONTENT.len())?
                .read_to_end(&mut bytes)?;
            if bytes == CONTENT {
                Ok(())
            } else {
                Err(ArtifactOwnerHostError::InvalidTrust)
            }
        }
        _ => Err(ArtifactOwnerHostError::InvalidTrust),
    }
}

pub(super) fn bind_namespace(
    root: &Path,
    profile: LearningAuthenticationProfile,
) -> Result<(), ArtifactOwnerHostError> {
    if profile == LearningAuthenticationProfile::ClassicalV1
        || root.join(MARKER).symlink_metadata().is_ok()
    {
        return verify_namespace(root, profile);
    }
    // A classic or partially initialized directory is never relabelled PQ.
    if fs::read_dir(root)?.next().is_some() {
        return Err(ArtifactOwnerHostError::InvalidTrust);
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut marker = options.open(root.join(MARKER))?;
    marker.write_all(CONTENT)?;
    marker.sync_all()?;
    File::open(root)?.sync_all()?;
    Ok(())
}

impl LearningArtifactOwnerHost {
    /// Reauthenticate every presented signature before a retry can reuse an
    /// old terminal result. Historical expiry does not turn an invalid proof
    /// into an exact retry, and a randomized PQ signature is not an operation ID.
    pub(crate) fn verify_presented_head(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        if signed.signature.profile() != self.verifier.profile {
            return Err(ArtifactOwnerHostError::InvalidSignature);
        }
        let signer = self
            .verifier
            .head_signers
            .get(&signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            signed.witness.signing_key_digest,
            signed.witness.authority_epoch,
            signed.witness.issued_at,
            signed.witness.issued_at,
            /*require_current*/ false,
        )?;
        verify_signature(
            &signer.verifying_key,
            &signed.signing_bytes(),
            &signed.signature,
        )
    }
}

/// Call only after both signatures have independently passed the pinned owner.
/// PQ proofs may be randomized; a proof is never the durable operation identity.
pub(super) fn same_authenticated_head(
    left: &SignedCurrentArtifactHeadV1,
    right: &SignedCurrentArtifactHeadV1,
) -> bool {
    match (left.signature.profile(), right.signature.profile()) {
        (
            LearningAuthenticationProfile::ClassicalV1,
            LearningAuthenticationProfile::ClassicalV1,
        ) => left == right,
        (LearningAuthenticationProfile::MlDsa65V2, LearningAuthenticationProfile::MlDsa65V2) => {
            left.signing_bytes() == right.signing_bytes()
        }
        (LearningAuthenticationProfile::ClassicalV1, LearningAuthenticationProfile::MlDsa65V2)
        | (LearningAuthenticationProfile::MlDsa65V2, LearningAuthenticationProfile::ClassicalV1) => {
            false
        }
    }
}
