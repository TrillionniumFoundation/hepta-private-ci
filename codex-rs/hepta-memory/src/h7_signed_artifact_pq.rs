//! Explicit ML-DSA artifact authentication. Pinned signature origin is not a
//! current role check, a production grant, or independent custody qualification.

use super::ArtifactVerifier;
use super::H7_SIGNED_ARTIFACT_SCHEMA_VERSION;
use super::H7ArtifactVerifier;
use super::H7SignedArtifactEnvelope;
use super::H7SignedArtifactError;
use super::H7SignedArtifactTransition;
use super::unsigned;
use super::validate_identifier;
use crate::h7_feedback::H7OfflineEvaluation;
use crate::h7_runtime::H7Artifact;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SPKI_BYTES;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use std::sync::Arc;

pub const H7_PQ_SIGNED_ARTIFACT_SCHEMA_VERSION: u32 = 2;
pub const H7_PQ_SIGNED_ARTIFACT_SIGNATURE_DOMAIN: &str = "hepta:h7:signed-artifact:ml-dsa65-v2";
pub const H7_PQ_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM: &str = "ml_dsa65_v2";
const SIGNING_DOMAIN: &[u8] = b"hepta-memory:h7-signed-artifact-envelope:ml-dsa65-v2\0";

/// A separately supplied artifact-role secret, with no implicit generation,
/// secret export, Clone, signer-role inheritance or production promotion.
pub struct H7PqArtifactSigner {
    signer_id: String,
    signer_epoch: u64,
    signing_key: PqNativeSigningKey,
    verifier: Arc<PqNativeVerifier>,
}

impl H7PqArtifactSigner {
    pub fn new(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        signing_key: PqNativeSigningKey,
    ) -> Result<Self, H7SignedArtifactError> {
        let verifier = H7ArtifactVerifier::from_pinned_spki(
            signer_id,
            signer_epoch,
            signing_key.public_spki(),
            signing_key.public_key_id(),
        )?;
        let ArtifactVerifier::MlDsa65V2(key) = verifier.verifying_key else {
            return Err(H7SignedArtifactError::SignatureInvalid);
        };
        Ok(Self {
            signer_id: verifier.signer_id,
            signer_epoch,
            signing_key,
            verifier: key,
        })
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }
    pub fn signer_epoch(&self) -> u64 {
        self.signer_epoch
    }
    pub fn public_key_id(&self) -> [u8; 32] {
        self.verifier.public_key_id()
    }
    pub fn public_spki(&self) -> &[u8; ML_DSA_65_SPKI_BYTES] {
        self.verifier.public_spki()
    }

    pub fn verifier(&self) -> H7ArtifactVerifier {
        H7ArtifactVerifier {
            signer_id: self.signer_id.clone(),
            signer_epoch: self.signer_epoch,
            verifying_key: ArtifactVerifier::MlDsa65V2(Arc::clone(&self.verifier)),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn sign(
        &self,
        artifact: &H7Artifact,
        ope: Option<&H7OfflineEvaluation>,
        transition: H7SignedArtifactTransition,
        expected_runtime_generation: u64,
        predecessor_artifact_sha256: Option<Sha256Digest>,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<H7SignedArtifactEnvelope, H7SignedArtifactError> {
        let mut envelope = unsigned::artifact_envelope(
            &self.signer_id,
            self.signer_epoch,
            artifact,
            ope,
            transition,
            expected_runtime_generation,
            predecessor_artifact_sha256,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        // Only unsigned bounded data is shared with the legacy constructor.
        // Select the explicit PQ profile before any digest or signature.
        envelope.schema_version = H7_PQ_SIGNED_ARTIFACT_SCHEMA_VERSION;
        envelope.signature_domain = H7_PQ_SIGNED_ARTIFACT_SIGNATURE_DOMAIN.to_string();
        envelope.signature_algorithm = H7_PQ_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM.to_string();
        envelope.signer_public_key_id = Some(self.public_key_id());
        envelope.envelope_sha256 = envelope.payload_digest();
        envelope.signature_base64 = STANDARD.encode(
            self.signing_key
                .sign_exact_message(&envelope.signing_bytes())
                .map_err(|_| H7SignedArtifactError::SignatureInvalid)?,
        );
        envelope.validate_shape()?;
        Ok(envelope)
    }
}

impl H7ArtifactVerifier {
    /// Selects canonical ML-DSA-65 SPKI with its recomputed pinned key ID.
    /// Current role permission remains the authority owner's responsibility.
    pub fn from_pinned_spki(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        spki: &[u8],
        public_key_id: [u8; 32],
    ) -> Result<Self, H7SignedArtifactError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "PQ artifact signer id")?;
        if signer_epoch == 0 || public_key_id == [0; 32] {
            return Err(H7SignedArtifactError::Invalid(
                "PQ artifact epoch or key ID is invalid".to_string(),
            ));
        }
        let verifier =
            PqNativeVerifier::from_pinned_spki(spki, public_key_id).map_err(|error| {
                H7SignedArtifactError::Invalid(format!("PQ artifact key rejected: {error}"))
            })?;
        Ok(Self {
            signer_id,
            signer_epoch,
            verifying_key: ArtifactVerifier::MlDsa65V2(Arc::new(verifier)),
        })
    }

    /// Returns the pinned PQ identity; a classical qualification key has none.
    pub fn pq_public_key_id(&self) -> Option<[u8; 32]> {
        match &self.verifying_key {
            ArtifactVerifier::ClassicalV1(_) => None,
            ArtifactVerifier::MlDsa65V2(key) => Some(key.public_key_id()),
        }
    }

    pub(super) fn verify_signature_for_profile(
        &self,
        envelope: &H7SignedArtifactEnvelope,
    ) -> Result<(), H7SignedArtifactError> {
        let signature_length: usize = match &self.verifying_key {
            ArtifactVerifier::ClassicalV1(_)
                if envelope.schema_version == H7_SIGNED_ARTIFACT_SCHEMA_VERSION =>
            {
                64
            }
            ArtifactVerifier::MlDsa65V2(key)
                if envelope.schema_version == H7_PQ_SIGNED_ARTIFACT_SCHEMA_VERSION
                    && envelope.signer_public_key_id == Some(key.public_key_id()) =>
            {
                ML_DSA_65_SIGNATURE_BYTES
            }
            _ => return Err(H7SignedArtifactError::SignatureInvalid),
        };
        // Bound decoding before allocation and require one canonical encoding.
        if envelope.signature_base64.len() != signature_length.div_ceil(3) * 4 {
            return Err(H7SignedArtifactError::SignatureMalformed);
        }
        let signature = STANDARD
            .decode(&envelope.signature_base64)
            .map_err(|_| H7SignedArtifactError::SignatureMalformed)?;
        if signature.len() != signature_length
            || STANDARD.encode(&signature) != envelope.signature_base64
        {
            return Err(H7SignedArtifactError::SignatureMalformed);
        }
        match &self.verifying_key {
            ArtifactVerifier::ClassicalV1(key) => {
                let signature = Signature::from_slice(&signature)
                    .map_err(|_| H7SignedArtifactError::SignatureMalformed)?;
                key.verify(&envelope.signing_bytes(), &signature)
                    .map_err(|_| H7SignedArtifactError::SignatureInvalid)
            }
            ArtifactVerifier::MlDsa65V2(key) => key
                .verify_exact_message(&envelope.signing_bytes(), &signature)
                .map(|_| ())
                .map_err(|_| H7SignedArtifactError::SignatureInvalid),
        }
    }
}

pub(super) fn signing_bytes(envelope: &H7SignedArtifactEnvelope) -> Vec<u8> {
    let mut message = Vec::new();
    frame(&mut message, SIGNING_DOMAIN);
    frame(&mut message, &envelope.schema_version.to_be_bytes());
    for value in [
        envelope.namespace.as_bytes(),
        envelope.signature_domain.as_bytes(),
        envelope.signature_algorithm.as_bytes(),
        envelope.artifact_id.as_bytes(),
        envelope.artifact_sha256.as_str().as_bytes(),
        envelope.trajectory_sha256.as_str().as_bytes(),
        envelope.evaluation_sha256.as_str().as_bytes(),
        envelope.signer_id.as_bytes(),
    ] {
        frame(&mut message, value);
    }
    optional(
        &mut message,
        envelope
            .signer_public_key_id
            .as_ref()
            .map(<[u8; 32]>::as_slice),
    );
    optional(
        &mut message,
        envelope
            .ope_evaluation_sha256
            .as_ref()
            .map(|digest| digest.as_str().as_bytes()),
    );
    for value in [
        envelope.signer_epoch,
        envelope.issued_at_unix_seconds,
        envelope.expires_at_unix_seconds,
        envelope.expected_runtime_generation,
    ] {
        frame(&mut message, &value.to_be_bytes());
    }
    frame(&mut message, envelope.transition.as_str().as_bytes());
    optional(
        &mut message,
        envelope
            .predecessor_artifact_sha256
            .as_ref()
            .map(|digest| digest.as_str().as_bytes()),
    );
    for flag in [
        envelope.qualification_only,
        envelope.production_authority,
        envelope.external_effects,
        envelope.promotion_eligible,
    ] {
        frame(&mut message, &[u8::from(flag)]);
    }
    message
}

fn frame(message: &mut Vec<u8>, value: &[u8]) {
    message.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    message.extend_from_slice(value);
}

fn optional(message: &mut Vec<u8>, value: Option<&[u8]>) {
    match value {
        Some(value) => {
            frame(message, &[1]);
            frame(message, value);
        }
        None => frame(message, &[0]),
    }
}
