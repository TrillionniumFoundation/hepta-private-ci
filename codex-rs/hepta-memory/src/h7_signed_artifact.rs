//! Signed H7 qualification artifacts and offline-policy-evaluation (OPE)
//! envelopes.
//!
//! The signer and verifier are deliberately separate values.  A verifier is
//! constructed from an independently pinned Ed25519 public key, signer id,
//! and signer epoch; values supplied by an envelope never choose the trust
//! anchor.  The signed payload binds all artifact, evaluation, trajectory,
//! OPE, CAS, and validity-window fields.  Every authority/effect bit is
//! explicitly false, so this module cannot be used as a production promotion
//! path.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::framing::frame_part;
use crate::h7_feedback::H7OfflineEvaluation;
use crate::h7_runtime::H7Artifact;

pub const H7_SIGNED_ARTIFACT_SCHEMA_VERSION: u32 = 1;
pub const H7_SIGNED_ARTIFACT_NAMESPACE: &str = "local_qualification_only";
pub const H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN: &str = "hepta:h7:signed-artifact:v1";
pub const H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM: &str = "ed25519";
pub const H7_SIGNED_ARTIFACT_MAX_LIFETIME_SECONDS: u64 = 86_400;

const SIGNING_DOMAIN: &[u8] = b"hepta-memory:h7-signed-artifact-envelope:v1";

/// A transition authorized by a signed qualification artifact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum H7SignedArtifactTransition {
    Reload,
    Rollback,
}

impl H7SignedArtifactTransition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Reload => "reload",
            Self::Rollback => "rollback",
        }
    }
}

/// A detached signature envelope for one exact H7 artifact and optional OPE
/// result.  `envelope_sha256` commits to every field except the detached
/// signature itself; the Ed25519 signature commits to that same payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7SignedArtifactEnvelope {
    pub schema_version: u32,
    pub namespace: String,
    pub signature_domain: String,
    pub signature_algorithm: String,
    pub artifact_id: String,
    pub artifact_sha256: Sha256Digest,
    pub trajectory_sha256: Sha256Digest,
    pub evaluation_sha256: Sha256Digest,
    pub ope_evaluation_sha256: Option<Sha256Digest>,
    pub signer_id: String,
    pub signer_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub transition: H7SignedArtifactTransition,
    pub expected_runtime_generation: u64,
    pub predecessor_artifact_sha256: Option<Sha256Digest>,
    pub qualification_only: bool,
    pub production_authority: bool,
    pub external_effects: bool,
    pub promotion_eligible: bool,
    pub signature_base64: String,
    pub envelope_sha256: Sha256Digest,
}

/// Alias used by OPE gate callers.  OPE is not a separate authority: it is
/// an optional digest-bound input in the same signed envelope.
pub type H7OpeEnvelope = H7SignedArtifactEnvelope;
pub type H7SignedOpeEnvelope = H7SignedArtifactEnvelope;
pub type H7SignedArtifact = H7SignedArtifactEnvelope;

/// Independent Ed25519 signer for a qualification artifact.
#[derive(Clone)]
pub struct H7ArtifactSigner {
    signer_id: String,
    signer_epoch: u64,
    signing_key: SigningKey,
}

impl H7ArtifactSigner {
    pub fn new(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        signing_key: SigningKey,
    ) -> Result<Self, H7SignedArtifactError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "signer id")?;
        if signer_epoch == 0 {
            return Err(H7SignedArtifactError::Invalid(
                "signer epoch must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            signer_id,
            signer_epoch,
            signing_key,
        })
    }

    /// Constructs an independent signer from a raw 32-byte Ed25519 seed.
    /// This is convenient for a qualification harness that keeps key material
    /// outside the envelope; the seed itself is never serialized.
    pub fn from_seed(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        seed: [u8; 32],
    ) -> Result<Self, H7SignedArtifactError> {
        Self::new(signer_id, signer_epoch, SigningKey::from_bytes(&seed))
    }

    /// Alias retained for callers that use the Ed25519 `from_bytes` naming.
    pub fn from_bytes(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        seed: [u8; 32],
    ) -> Result<Self, H7SignedArtifactError> {
        Self::from_seed(signer_id, signer_epoch, seed)
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }

    pub const fn signer_epoch(&self) -> u64 {
        self.signer_epoch
    }

    pub fn verifying_key(&self) -> VerifyingKey {
        self.signing_key.verifying_key()
    }

    pub fn verifier(&self) -> H7ArtifactVerifier {
        H7ArtifactVerifier {
            signer_id: self.signer_id.clone(),
            signer_epoch: self.signer_epoch,
            verifying_key: self.verifying_key(),
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
        artifact
            .validate()
            .map_err(|error| H7SignedArtifactError::Runtime(error.to_string()))?;
        if let Some(ope) = ope {
            ope.validate()
                .map_err(|error| H7SignedArtifactError::Feedback(error.to_string()))?;
        }
        validate_window(issued_at_unix_seconds, expires_at_unix_seconds)?;
        if expected_runtime_generation > u64::MAX - 1 {
            return Err(H7SignedArtifactError::Invalid(
                "runtime generation is outside the bounded range".to_string(),
            ));
        }
        if matches!(transition, H7SignedArtifactTransition::Rollback)
            && predecessor_artifact_sha256.is_none()
        {
            return Err(H7SignedArtifactError::PredecessorRequired);
        }
        let mut envelope = H7SignedArtifactEnvelope {
            schema_version: H7_SIGNED_ARTIFACT_SCHEMA_VERSION,
            namespace: H7_SIGNED_ARTIFACT_NAMESPACE.to_string(),
            signature_domain: H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN.to_string(),
            signature_algorithm: H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM.to_string(),
            artifact_id: artifact.artifact_id.clone(),
            artifact_sha256: artifact.body_sha256.clone(),
            trajectory_sha256: artifact.trajectory_sha256.clone(),
            evaluation_sha256: artifact.evaluation_sha256.clone(),
            ope_evaluation_sha256: ope.map(|evaluation| evaluation.evaluation_digest.clone()),
            signer_id: self.signer_id.clone(),
            signer_epoch: self.signer_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            transition,
            expected_runtime_generation,
            predecessor_artifact_sha256,
            qualification_only: true,
            production_authority: false,
            external_effects: false,
            promotion_eligible: false,
            signature_base64: String::new(),
            envelope_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        envelope.envelope_sha256 = envelope.payload_digest();
        envelope.signature_base64 =
            STANDARD.encode(self.signing_key.sign(&envelope.signing_bytes()).to_bytes());
        envelope.validate_shape()?;
        Ok(envelope)
    }
}

/// Independent verifier.  The trust anchor is supplied by the caller and is
/// not taken from the envelope.
#[derive(Clone)]
pub struct H7ArtifactVerifier {
    signer_id: String,
    signer_epoch: u64,
    verifying_key: VerifyingKey,
}

impl H7ArtifactVerifier {
    pub fn new(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        verifying_key: VerifyingKey,
    ) -> Result<Self, H7SignedArtifactError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "verifier signer id")?;
        if signer_epoch == 0 || verifying_key.is_weak() {
            return Err(H7SignedArtifactError::Invalid(
                "verifier epoch or Ed25519 key is invalid".to_string(),
            ));
        }
        Ok(Self {
            signer_id,
            signer_epoch,
            verifying_key,
        })
    }

    /// Pins a verifier to a raw 32-byte Ed25519 public key.  The key is
    /// supplied independently of any envelope data.
    pub fn from_bytes(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        public_key: [u8; 32],
    ) -> Result<Self, H7SignedArtifactError> {
        let verifying_key = VerifyingKey::from_bytes(&public_key).map_err(|_| {
            H7SignedArtifactError::Invalid("verifier public key is malformed".to_string())
        })?;
        Self::new(signer_id, signer_epoch, verifying_key)
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }

    pub const fn signer_epoch(&self) -> u64 {
        self.signer_epoch
    }

    /// Verifies the detached Ed25519 signature and validity window without
    /// requiring the artifact/OPE bodies to be present.  Production control
    /// planes use this when an artifact registry is owned by a separate
    /// process; digest and policy binding still remain in the envelope and
    /// are checked by the caller.
    pub fn verify_envelope_signature(
        &self,
        envelope: &H7SignedArtifactEnvelope,
        now_unix_seconds: u64,
    ) -> Result<(), H7SignedArtifactError> {
        envelope.validate_shape()?;
        if envelope.signer_id != self.signer_id {
            return Err(H7SignedArtifactError::SignerMismatch);
        }
        if envelope.signer_epoch != self.signer_epoch {
            return Err(H7SignedArtifactError::EpochMismatch);
        }
        if now_unix_seconds < envelope.issued_at_unix_seconds {
            return Err(H7SignedArtifactError::NotYetValid);
        }
        if now_unix_seconds >= envelope.expires_at_unix_seconds {
            return Err(H7SignedArtifactError::Expired);
        }
        let signature_bytes = STANDARD
            .decode(&envelope.signature_base64)
            .map_err(|_| H7SignedArtifactError::SignatureMalformed)?;
        if STANDARD.encode(&signature_bytes) != envelope.signature_base64
            || signature_bytes.len() != 64
        {
            return Err(H7SignedArtifactError::SignatureMalformed);
        }
        let signature = Signature::from_slice(&signature_bytes)
            .map_err(|_| H7SignedArtifactError::SignatureMalformed)?;
        self.verifying_key
            .verify(&envelope.signing_bytes(), &signature)
            .map_err(|_| H7SignedArtifactError::SignatureInvalid)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify(
        &self,
        envelope: &H7SignedArtifactEnvelope,
        artifact: &H7Artifact,
        ope: Option<&H7OfflineEvaluation>,
        now_unix_seconds: u64,
        expected_runtime_generation: u64,
        expected_predecessor_artifact_sha256: Option<&Sha256Digest>,
    ) -> Result<(), H7SignedArtifactError> {
        envelope.validate_shape()?;
        artifact
            .validate()
            .map_err(|error| H7SignedArtifactError::Runtime(error.to_string()))?;
        if envelope.artifact_id != artifact.artifact_id
            || envelope.artifact_sha256 != artifact.body_sha256
            || envelope.trajectory_sha256 != artifact.trajectory_sha256
            || envelope.evaluation_sha256 != artifact.evaluation_sha256
        {
            return Err(H7SignedArtifactError::ArtifactBinding);
        }
        match (envelope.ope_evaluation_sha256.as_ref(), ope) {
            (None, None) => {}
            (Some(expected), Some(actual)) => {
                actual
                    .validate()
                    .map_err(|error| H7SignedArtifactError::Feedback(error.to_string()))?;
                if expected != &actual.evaluation_digest {
                    return Err(H7SignedArtifactError::OpeBinding);
                }
            }
            _ => return Err(H7SignedArtifactError::OpeBinding),
        }
        if envelope.expected_runtime_generation != expected_runtime_generation {
            return Err(H7SignedArtifactError::GenerationFence {
                expected: expected_runtime_generation,
                actual: envelope.expected_runtime_generation,
            });
        }
        if envelope.predecessor_artifact_sha256.as_ref() != expected_predecessor_artifact_sha256 {
            return Err(H7SignedArtifactError::PredecessorMismatch);
        }
        self.verify_envelope_signature(envelope, now_unix_seconds)
    }

    /// Convenience spelling for OPE gate callers.
    #[allow(clippy::too_many_arguments)]
    pub fn verify_ope(
        &self,
        envelope: &H7OpeEnvelope,
        artifact: &H7Artifact,
        ope: &H7OfflineEvaluation,
        now_unix_seconds: u64,
        expected_runtime_generation: u64,
        expected_predecessor_artifact_sha256: Option<&Sha256Digest>,
    ) -> Result<(), H7SignedArtifactError> {
        self.verify(
            envelope,
            artifact,
            Some(ope),
            now_unix_seconds,
            expected_runtime_generation,
            expected_predecessor_artifact_sha256,
        )
    }
}

impl H7SignedArtifactEnvelope {
    /// The digest that commits the envelope's detached-signature payload.
    pub fn digest(&self) -> &Sha256Digest {
        &self.envelope_sha256
    }

    /// Alias for callers that use artifact terminology for the bound body
    /// digest.
    pub fn artifact_digest(&self) -> &Sha256Digest {
        &self.artifact_sha256
    }

    pub fn trajectory_digest(&self) -> &Sha256Digest {
        &self.trajectory_sha256
    }

    pub fn evaluation_digest(&self) -> &Sha256Digest {
        &self.evaluation_sha256
    }

    pub fn validate_shape(&self) -> Result<(), H7SignedArtifactError> {
        if self.schema_version != H7_SIGNED_ARTIFACT_SCHEMA_VERSION
            || self.namespace != H7_SIGNED_ARTIFACT_NAMESPACE
            || self.signature_domain != H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN
            || self.signature_algorithm != H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM
            || !self.qualification_only
            || self.production_authority
            || self.external_effects
            || self.promotion_eligible
        {
            return Err(H7SignedArtifactError::ProductionBoundary);
        }
        validate_identifier(&self.artifact_id, "artifact id")?;
        validate_identifier(&self.signer_id, "signer id")?;
        if self.signer_epoch == 0 || self.expected_runtime_generation == u64::MAX {
            return Err(H7SignedArtifactError::Invalid(
                "signer epoch or runtime generation is invalid".to_string(),
            ));
        }
        validate_window(self.issued_at_unix_seconds, self.expires_at_unix_seconds)?;
        if matches!(self.transition, H7SignedArtifactTransition::Rollback)
            && self.predecessor_artifact_sha256.is_none()
        {
            return Err(H7SignedArtifactError::PredecessorRequired);
        }
        for (label, digest) in [
            ("artifact", &self.artifact_sha256),
            ("trajectory", &self.trajectory_sha256),
            ("evaluation", &self.evaluation_sha256),
            ("envelope", &self.envelope_sha256),
        ] {
            parse_digest(digest, label)?;
        }
        if let Some(digest) = &self.ope_evaluation_sha256 {
            parse_digest(digest, "OPE evaluation")?;
        }
        if let Some(digest) = &self.predecessor_artifact_sha256 {
            parse_digest(digest, "predecessor artifact")?;
        }
        if self.envelope_sha256 != self.payload_digest() {
            return Err(H7SignedArtifactError::DigestMismatch("envelope"));
        }
        if self.signature_base64.is_empty() {
            return Err(H7SignedArtifactError::SignatureMalformed);
        }
        Ok(())
    }

    pub fn payload_digest(&self) -> Sha256Digest {
        Sha256Digest::from_sha256_output(Sha256::digest(self.signing_bytes()))
    }

    /// Returns the exact bytes covered by the detached Ed25519 signature.
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, SIGNING_DOMAIN);
        frame_part(&mut hasher, &self.schema_version.to_be_bytes());
        for value in [
            self.namespace.as_bytes(),
            self.signature_domain.as_bytes(),
            self.signature_algorithm.as_bytes(),
            self.artifact_id.as_bytes(),
            self.artifact_sha256.as_str().as_bytes(),
            self.trajectory_sha256.as_str().as_bytes(),
            self.evaluation_sha256.as_str().as_bytes(),
        ] {
            frame_part(&mut hasher, value);
        }
        match &self.ope_evaluation_sha256 {
            Some(digest) => {
                frame_part(&mut hasher, &[1]);
                frame_part(&mut hasher, digest.as_str().as_bytes());
            }
            None => frame_part(&mut hasher, &[0]),
        }
        {
            let value = self.signer_id.as_bytes();
            frame_part(&mut hasher, value);
        }
        frame_part(&mut hasher, &self.signer_epoch.to_be_bytes());
        frame_part(&mut hasher, &self.issued_at_unix_seconds.to_be_bytes());
        frame_part(&mut hasher, &self.expires_at_unix_seconds.to_be_bytes());
        frame_part(&mut hasher, self.transition.as_str().as_bytes());
        frame_part(&mut hasher, &self.expected_runtime_generation.to_be_bytes());
        match &self.predecessor_artifact_sha256 {
            Some(digest) => {
                frame_part(&mut hasher, &[1]);
                frame_part(&mut hasher, digest.as_str().as_bytes());
            }
            None => frame_part(&mut hasher, &[0]),
        }
        for flag in [
            self.qualification_only,
            self.production_authority,
            self.external_effects,
            self.promotion_eligible,
        ] {
            frame_part(&mut hasher, &[u8::from(flag)]);
        }
        hasher.finalize().to_vec()
    }
}

fn validate_window(issued: u64, expires: u64) -> Result<(), H7SignedArtifactError> {
    if issued == 0 || expires <= issued {
        return Err(H7SignedArtifactError::Invalid(
            "signed artifact validity window is malformed".to_string(),
        ));
    }
    if expires - issued > H7_SIGNED_ARTIFACT_MAX_LIFETIME_SECONDS {
        return Err(H7SignedArtifactError::Invalid(
            "signed artifact validity window exceeds the bounded lifetime".to_string(),
        ));
    }
    Ok(())
}

fn validate_identifier(value: &str, label: &str) -> Result<(), H7SignedArtifactError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(H7SignedArtifactError::Invalid(format!(
            "{label} contains an invalid identifier"
        )));
    }
    Ok(())
}

fn parse_digest(digest: &Sha256Digest, label: &'static str) -> Result<(), H7SignedArtifactError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| H7SignedArtifactError::DigestMismatch(label))
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum H7SignedArtifactError {
    #[error("invalid signed H7 artifact: {0}")]
    Invalid(String),
    #[error("signed H7 artifact crosses the qualification authority boundary")]
    ProductionBoundary,
    #[error("signed H7 artifact digest mismatch for {0}")]
    DigestMismatch(&'static str),
    #[error("signed H7 artifact does not bind the artifact/evaluation")]
    ArtifactBinding,
    #[error("signed H7 artifact does not bind the OPE evaluation")]
    OpeBinding,
    #[error("signed H7 artifact signer identity mismatch")]
    SignerMismatch,
    #[error("signed H7 artifact signer epoch mismatch")]
    EpochMismatch,
    #[error("signed H7 artifact validity window has not started")]
    NotYetValid,
    #[error("signed H7 artifact validity window has expired")]
    Expired,
    #[error("signed H7 artifact signature is malformed")]
    SignatureMalformed,
    #[error("signed H7 artifact signature verification failed")]
    SignatureInvalid,
    #[error(
        "signed H7 artifact expected-runtime-generation fence mismatch: expected {expected}, actual {actual}"
    )]
    GenerationFence { expected: u64, actual: u64 },
    #[error("signed H7 artifact rollback predecessor does not match the active CAS head")]
    PredecessorMismatch,
    #[error("signed H7 artifact rollback requires a predecessor CAS digest")]
    PredecessorRequired,
    #[error("H7 artifact validation failed: {0}")]
    Runtime(String),
    #[error("H7 OPE validation failed: {0}")]
    Feedback(String),
}

impl From<crate::h7_runtime::H7RuntimeError> for H7SignedArtifactError {
    fn from(error: crate::h7_runtime::H7RuntimeError) -> Self {
        Self::Runtime(error.to_string())
    }
}

impl From<crate::h7_feedback::H7FeedbackError> for H7SignedArtifactError {
    fn from(error: crate::h7_feedback::H7FeedbackError) -> Self {
        Self::Feedback(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::h7_runtime::H7QualificationRuntime;

    fn digest(seed: u8) -> Sha256Digest {
        Sha256Digest::for_bytes(&[seed; 8])
    }

    fn artifact() -> H7Artifact {
        let mut runtime = H7QualificationRuntime::new();
        let event = crate::h7_runtime::H7TrajectoryEvent::new(
            "signed-trajectory",
            1,
            "abstain",
            1_000,
            true,
            1,
            1,
            1,
            digest(1),
        )
        .expect("event");
        runtime.append_trajectory_event(event).expect("append");
        runtime
            .evaluate_trajectory("signed-trajectory")
            .expect("evaluate");
        runtime
            .propose_artifact("signed-artifact", "signed-trajectory", 1)
            .expect("artifact")
    }

    #[test]
    fn independent_signer_verifier_binds_cas_and_expiry() {
        let artifact = artifact();
        let signer =
            H7ArtifactSigner::new("qualification-signer", 7, SigningKey::from_bytes(&[9; 32]))
                .expect("signer");
        let envelope = signer
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Reload,
                0,
                None,
                100,
                200,
            )
            .expect("sign");
        let verifier = H7ArtifactVerifier::new("qualification-signer", 7, signer.verifying_key())
            .expect("verifier");
        verifier
            .verify(&envelope, &artifact, None, 150, 0, None)
            .expect("verify");
        assert_eq!(
            verifier.verify(&envelope, &artifact, None, 200, 0, None),
            Err(H7SignedArtifactError::Expired)
        );
        assert_eq!(
            verifier.verify(&envelope, &artifact, None, 150, 1, None),
            Err(H7SignedArtifactError::GenerationFence {
                expected: 1,
                actual: 0,
            })
        );
        let mut tampered = envelope;
        tampered.signature_domain = "wrong-domain".to_string();
        assert!(matches!(
            verifier.verify(&tampered, &artifact, None, 150, 0, None),
            Err(H7SignedArtifactError::ProductionBoundary)
                | Err(H7SignedArtifactError::DigestMismatch(_))
        ));
    }

    #[test]
    fn detached_signature_verification_is_body_independent_and_fail_closed() {
        let artifact = artifact();
        let signer = H7ArtifactSigner::new("detached-signer", 9, SigningKey::from_bytes(&[6; 32]))
            .expect("signer");
        let envelope = signer
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Reload,
                4,
                None,
                100,
                200,
            )
            .expect("sign");
        let verifier = signer.verifier();

        // The detached path only needs the envelope and pinned public key;
        // artifact/OPE bodies are deliberately absent here.
        verifier
            .verify_envelope_signature(&envelope, 150)
            .expect("detached signature");

        let mut tampered_signature = envelope.clone();
        let mut signature_bytes = STANDARD
            .decode(&tampered_signature.signature_base64)
            .expect("signature encoding");
        signature_bytes[0] ^= 0x01;
        tampered_signature.signature_base64 = STANDARD.encode(signature_bytes);
        assert_eq!(
            verifier.verify_envelope_signature(&tampered_signature, 150),
            Err(H7SignedArtifactError::SignatureInvalid)
        );

        let mut malformed_signature = envelope.clone();
        malformed_signature.signature_base64 = "not-base64".to_string();
        assert_eq!(
            verifier.verify_envelope_signature(&malformed_signature, 150),
            Err(H7SignedArtifactError::SignatureMalformed)
        );
        assert_eq!(
            verifier.verify_envelope_signature(&envelope, 200),
            Err(H7SignedArtifactError::Expired)
        );
        let wrong_epoch = H7ArtifactVerifier::new("detached-signer", 10, signer.verifying_key())
            .expect("wrong-epoch verifier");
        assert_eq!(
            wrong_epoch.verify_envelope_signature(&envelope, 150),
            Err(H7SignedArtifactError::EpochMismatch)
        );
    }

    #[test]
    fn production_flags_and_wrong_anchor_are_rejected() {
        let artifact = artifact();
        let signer =
            H7ArtifactSigner::new("qualification-signer", 1, SigningKey::from_bytes(&[4; 32]))
                .expect("signer");
        let envelope = signer
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Reload,
                0,
                None,
                10,
                20,
            )
            .expect("sign");
        let wrong = H7ArtifactVerifier::new(
            "other-signer",
            1,
            SigningKey::from_bytes(&[5; 32]).verifying_key(),
        )
        .expect("verifier");
        assert_eq!(
            wrong.verify(&envelope, &artifact, None, 11, 0, None),
            Err(H7SignedArtifactError::SignerMismatch)
        );
        let mut forged = envelope;
        forged.production_authority = true;
        assert_eq!(
            wrong.verify(&forged, &artifact, None, 11, 0, None),
            Err(H7SignedArtifactError::ProductionBoundary)
        );
    }

    #[test]
    fn signed_runtime_reload_rollback_and_replay_are_cas_bound() {
        let mut runtime = H7QualificationRuntime::new();
        let event = crate::h7_runtime::H7TrajectoryEvent::new(
            "signed-runtime-trajectory",
            1,
            "abstain",
            1_000,
            true,
            1,
            1,
            1,
            digest(21),
        )
        .expect("event");
        runtime.append_trajectory_event(event).expect("append");
        runtime
            .evaluate_trajectory("signed-runtime-trajectory")
            .expect("evaluate");
        let artifact_v1 = runtime
            .propose_artifact("signed-runtime-v1", "signed-runtime-trajectory", 1)
            .expect("v1");
        let artifact_v2 = runtime
            .propose_artifact("signed-runtime-v2", "signed-runtime-trajectory", 2)
            .expect("v2");
        let signer = H7ArtifactSigner::from_seed("runtime-signer", 3, [8; 32]).expect("signer");
        let verifier =
            H7ArtifactVerifier::from_bytes("runtime-signer", 3, signer.verifying_key().to_bytes())
                .expect("verifier");

        let reload_v1 = signer
            .sign(
                &artifact_v1,
                None,
                H7SignedArtifactTransition::Reload,
                0,
                None,
                100,
                500,
            )
            .expect("signed v1");
        let state_v1 = runtime
            .apply_signed(&reload_v1, &verifier, None, 200)
            .expect("apply v1");
        assert_eq!(state_v1.runtime_generation, 1);

        let reload_v2 = signer
            .sign(
                &artifact_v2,
                None,
                H7SignedArtifactTransition::Reload,
                1,
                Some(artifact_v1.body_sha256.clone()),
                100,
                500,
            )
            .expect("signed v2");
        let state_v2 = runtime
            .apply_signed(&reload_v2, &verifier, None, 200)
            .expect("apply v2");
        assert_eq!(state_v2.runtime_generation, 2);

        let rollback_v1 = signer
            .sign(
                &artifact_v1,
                None,
                H7SignedArtifactTransition::Rollback,
                2,
                Some(artifact_v2.body_sha256),
                100,
                500,
            )
            .expect("signed rollback");
        let rolled_back = runtime
            .apply_signed(&rollback_v1, &verifier, None, 200)
            .expect("apply rollback");
        assert_eq!(rolled_back.runtime_generation, 3);
        assert_eq!(
            rolled_back.active_artifact_id.as_deref(),
            Some("signed-runtime-v1")
        );
        assert_eq!(rolled_back.rollback_from_generation, Some(2));
        assert!(matches!(
            runtime.apply_signed(&rollback_v1, &verifier, None, 200),
            Err(crate::h7_runtime::H7RuntimeError::SignedArtifact(_))
        ));
    }
}
