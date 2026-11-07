//! Production supervisor admission for an externally signed H7 operation.
//!
//! The H7 artifact envelope itself is intentionally qualification-only.  A
//! production mutation therefore needs a second, independently pinned
//! authority grant.  This module defines that grant and its verifier; the
//! supervisor never generates a production grant and never treats a local H7
//! receipt as authority.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7ArtifactVerifier;
use codex_hepta_memory::H7SignedArtifactEnvelope;
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

pub const SIGNED_AUTHORITY_SCHEMA_VERSION: u32 = 1;
pub const SIGNED_AUTHORITY_NAMESPACE: &str = "hepta:production:authority:v1";
pub const SIGNED_AUTHORITY_MAX_LIFETIME_SECONDS: u64 = 86_400;
const SIGNING_DOMAIN: &[u8] = b"hepta-supervisor:production-authority:v1";
pub const PRODUCTION_RECOVERY_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_RECOVERY_NAMESPACE: &str = "hepta:production:recovery:v1";
const RECOVERY_SIGNING_DOMAIN: &[u8] = b"hepta-supervisor:production-recovery:v1";
#[path = "signed_authority_policy.rs"]
mod policy;
#[path = "signed_authority_pq.rs"]
mod pq;
#[cfg(test)]
#[path = "signed_authority_pq_tests.rs"]
pub(crate) mod pq_tests;
#[path = "signed_authority_pq_wire.rs"]
mod pq_wire;
#[path = "unknown_recovery_authority.rs"]
mod unknown_recovery;
#[path = "signed_authority_unsigned.rs"]
mod unsigned;
pub use policy::PqAuthorityBinding;
pub use policy::ProductionAuthorityPolicyV1;
pub use policy::ProductionAuthorityRoleV1;
pub use pq::H7PqProductionGrantSigner;
pub use pq::H7PqProductionRecoverySigner;
pub use unknown_recovery::UnknownRecoveryObservation;
pub use unknown_recovery::UnknownRecoveryPredecessorV1;
#[path = "completion_publication_authority.rs"]
mod completion_publication;
pub use completion_publication::CompletionPublicationObservationV1;
pub use completion_publication::RetainedPublicationObservationV1;
pub use unknown_recovery::absent_release_transaction_digest;

/// Derives the numeric CAS epoch that external grant issuers bind to the
/// daemon's UUID epoch.  A fresh supervisord process gets a fresh UUID, so a
/// grant cannot be replayed across daemon restarts.
pub fn authority_epoch_for_supervisor_epoch(supervisor_epoch: &str) -> u64 {
    let digest = Sha256::digest(supervisor_epoch.as_bytes());
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    let epoch = u64::from_be_bytes(bytes);
    if epoch == 0 { 1 } else { epoch }
}

/// The only two H7 transitions that can reach the lifecycle supervisor.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum H7H89ProductionTransition {
    Upgrade,
    Rollback,
}

impl H7H89ProductionTransition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Upgrade => "upgrade",
            Self::Rollback => "rollback",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductionRecoveryOutcome {
    Committed,
    RolledBack,
    /// Abandon the grant while retaining its unknown effects. No success or
    /// rollback is certified; a separate signature reauthorizes the source.
    AbandonUnknown,
    /// Confirm publication of an already retained Unknown disposition after an
    /// uncertain external CAS. It neither appends history nor permits dispatch.
    ConfirmUnknownPublication,
    /// A fresh operator signature confirms publication of an exact retained
    /// hot-owner completion proposal; it never re-executes that operation.
    ConfirmCommittedPublication,
    ConfirmRolledBackPublication,
    /// Retry the same retained replacement publication under a fresh decision;
    /// no third proposal, new confirmation material, or effect is created.
    RetryRetainedPublication,
}

impl ProductionRecoveryOutcome {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Committed => "committed",
            Self::RolledBack => "rolled_back",
            Self::AbandonUnknown => "abandon_unknown",
            Self::ConfirmUnknownPublication => "confirm_unknown_publication",
            Self::ConfirmCommittedPublication => "confirm_committed_publication",
            Self::ConfirmRolledBackPublication => "confirm_rolled_back_publication",
            Self::RetryRetainedPublication => "retry_retained_publication",
        }
    }
}

/// Independently signed operator decision for one quarantined production
/// release transaction. The decision cannot move release state; it only
/// terminalizes an already observed durable source/target outcome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionRecoveryDecision {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: String,
    pub grant_sha256: Sha256Digest,
    pub intent_sha256: Sha256Digest,
    pub release_transaction_sha256: Sha256Digest,
    pub observed_release: String,
    pub observed_manifest_sha256: Sha256Digest,
    pub observed_agentd_sha256: Sha256Digest,
    pub observed_matrixd_sha256: Option<Sha256Digest>,
    pub outcome: ProductionRecoveryOutcome,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unknown_observation: Option<UnknownRecoveryObservation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub completion_observation: Option<CompletionPublicationObservationV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retained_publication_observation: Option<RetainedPublicationObservationV1>,
    pub expected_lifecycle_generation: u64,
    pub authority_epoch: u64,
    pub signer_id: String,
    pub signer_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pq_authority: Option<PqAuthorityBinding>,
    pub signature_base64: String,
    pub decision_sha256: Sha256Digest,
}

impl ProductionRecoveryDecision {
    pub fn digest(&self) -> &Sha256Digest {
        &self.decision_sha256
    }

    pub fn validate_shape(&self) -> Result<(), ProductionAuthorityError> {
        let unknown = matches!(
            self.outcome,
            ProductionRecoveryOutcome::AbandonUnknown
                | ProductionRecoveryOutcome::ConfirmUnknownPublication
        );
        if !pq_wire::recovery_shape(self, unknown)
            || self.expected_lifecycle_generation == 0
            || self.authority_epoch == 0
            || self.signer_epoch == 0
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        AgentId::parse(self.agent_id.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?;
        validate_release(&self.observed_release)?;
        for (digest, label) in [
            (&self.grant_sha256, "recovery grant"),
            (&self.intent_sha256, "recovery intent"),
            (
                &self.release_transaction_sha256,
                "recovery release transaction",
            ),
            (&self.observed_manifest_sha256, "recovery observed manifest"),
            (&self.observed_agentd_sha256, "recovery observed agentd"),
            (&self.decision_sha256, "recovery decision"),
        ] {
            parse_digest(digest, label)?;
        }
        if let Some(digest) = self.observed_matrixd_sha256.as_ref() {
            parse_digest(digest, "recovery observed matrixd")?;
        }
        validate_identifier(&self.signer_id, "recovery signer id")?;
        validate_window(self.issued_at_unix_seconds, self.expires_at_unix_seconds)?;
        if self.decision_sha256 != self.payload_digest()
            || !pq_wire::signature_encoding(&self.signature_base64, self.pq_authority.is_some())
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        Ok(())
    }

    pub fn payload_digest(&self) -> Sha256Digest {
        Sha256Digest::from_sha256_output(Sha256::digest(self.signing_bytes()))
    }

    fn signing_bytes(&self) -> Vec<u8> {
        if self.pq_authority.is_some() {
            return pq_wire::recovery_message(self);
        }
        let mut hasher = Sha256::new();
        for value in [
            if self.outcome == ProductionRecoveryOutcome::AbandonUnknown {
                b"hepta-supervisor:production-recovery:abandon-unknown:v2".as_slice()
            } else {
                RECOVERY_SIGNING_DOMAIN
            },
            self.namespace.as_bytes(),
            self.agent_id.as_bytes(),
            self.grant_sha256.as_str().as_bytes(),
            self.intent_sha256.as_str().as_bytes(),
            self.release_transaction_sha256.as_str().as_bytes(),
            self.observed_release.as_bytes(),
            self.observed_manifest_sha256.as_str().as_bytes(),
            self.observed_agentd_sha256.as_str().as_bytes(),
            self.outcome.as_str().as_bytes(),
            self.signer_id.as_bytes(),
        ] {
            frame(&mut hasher, value);
        }
        match self.observed_matrixd_sha256.as_ref() {
            Some(digest) => {
                frame(&mut hasher, &[1]);
                frame(&mut hasher, digest.as_str().as_bytes());
            }
            None => frame(&mut hasher, &[0]),
        }
        if let Some(observed) = &self.unknown_observation {
            frame(
                &mut hasher,
                &observed.release_state_generation.to_be_bytes(),
            );
            frame(
                &mut hasher,
                observed.admission_frontier_sha256.as_str().as_bytes(),
            );
        }
        for value in [
            self.expected_lifecycle_generation,
            self.authority_epoch,
            self.signer_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
        ] {
            frame(&mut hasher, &value.to_be_bytes());
        }
        hasher.finalize().to_vec()
    }
}

/// A detached, externally issued production authority grant.
///
/// `h7_envelope_sha256` binds this grant to the signed H7/OPE envelope while
/// the source/target release identities and CAS fields bind it to one exact
/// supervisor mutation.  The four positive authority fields are deliberately
/// redundant: a verifier rejects a grant if any one is absent, and also
/// rejects `governance_bypass` even when the signature is valid.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7H89ProductionGrant {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: String,
    pub source_release: String,
    pub target_release: String,
    pub transition: H7H89ProductionTransition,
    pub h7_envelope_sha256: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub expected_control_revision: u64,
    pub expected_lifecycle_generation: u64,
    pub authority_epoch: u64,
    pub signer_id: String,
    pub signer_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub production_authority: bool,
    pub external_effects: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub governance_bypass: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pq_authority: Option<PqAuthorityBinding>,
    pub signature_base64: String,
    pub grant_sha256: Sha256Digest,
}

/// A signer is used by an external authority service or an operator ceremony,
/// never by the lifecycle supervisor itself.
#[derive(Clone)]
pub struct H7H89ProductionGrantSigner {
    signer_id: String,
    signer_epoch: u64,
    signing_key: SigningKey,
}

impl H7H89ProductionGrantSigner {
    pub fn new(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        signing_key: SigningKey,
    ) -> Result<Self, ProductionAuthorityError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "signer id")?;
        if signer_epoch == 0 {
            return Err(ProductionAuthorityError::Invalid(
                "signer epoch must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            signer_id,
            signer_epoch,
            signing_key,
        })
    }

    pub fn from_seed(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        seed: [u8; 32],
    ) -> Result<Self, ProductionAuthorityError> {
        Self::new(signer_id, signer_epoch, SigningKey::from_bytes(&seed))
    }

    pub fn verifying_key(&self) -> VerifyingKey {
        self.signing_key.verifying_key()
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }

    pub const fn signer_epoch(&self) -> u64 {
        self.signer_epoch
    }

    #[allow(clippy::too_many_arguments)]
    pub fn sign(
        &self,
        agent_id: &AgentId,
        source_release: impl Into<String>,
        target_release: impl Into<String>,
        transition: H7H89ProductionTransition,
        h7_envelope: &H7SignedArtifactEnvelope,
        expected_control_revision: u64,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<H7H89ProductionGrant, ProductionAuthorityError> {
        let mut grant = unsigned::grant(
            &self.signer_id,
            self.signer_epoch,
            agent_id,
            source_release,
            target_release,
            transition,
            h7_envelope,
            expected_control_revision,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        grant.grant_sha256 = grant.payload_digest();
        grant.signature_base64 =
            STANDARD.encode(self.signing_key.sign(&grant.signing_bytes()).to_bytes());
        grant.validate_shape(h7_envelope)?;
        Ok(grant)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn sign_recovery(
        &self,
        agent_id: &AgentId,
        grant_sha256: Sha256Digest,
        intent_sha256: Sha256Digest,
        release_transaction_sha256: Sha256Digest,
        observed_release: impl Into<String>,
        observed_manifest_sha256: Sha256Digest,
        observed_agentd_sha256: Sha256Digest,
        observed_matrixd_sha256: Option<Sha256Digest>,
        outcome: ProductionRecoveryOutcome,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        let mut decision = unsigned::recovery(
            &self.signer_id,
            self.signer_epoch,
            agent_id,
            grant_sha256,
            intent_sha256,
            release_transaction_sha256,
            observed_release,
            observed_manifest_sha256,
            observed_agentd_sha256,
            observed_matrixd_sha256,
            outcome,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        decision.decision_sha256 = decision.payload_digest();
        decision.signature_base64 =
            STANDARD.encode(self.signing_key.sign(&decision.signing_bytes()).to_bytes());
        decision.validate_shape()?;
        Ok(decision)
    }
}

/// A verifier whose trust anchor is supplied out-of-band and pinned by the
/// caller.  No key material from a grant is ever trusted.
#[derive(Clone)]
pub struct H7H89ProductionGrantVerifier {
    signer_id: String,
    signer_epoch: u64,
    keys: policy::AuthorityVerificationKeys,
    h7_verifier: H7ArtifactVerifier,
}

impl H7H89ProductionGrantVerifier {
    pub fn new(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        verifying_key: VerifyingKey,
    ) -> Result<Self, ProductionAuthorityError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "verifier signer id")?;
        if signer_epoch == 0 || verifying_key.is_weak() {
            return Err(ProductionAuthorityError::Invalid(
                "verifier epoch or Ed25519 key is invalid".to_string(),
            ));
        }
        let h7_verifier =
            H7ArtifactVerifier::new(signer_id.clone(), signer_epoch, verifying_key)
                .map_err(|error| ProductionAuthorityError::H7Binding(error.to_string()))?;
        Self::new_with_h7_verifier(signer_id, signer_epoch, verifying_key, h7_verifier)
    }

    /// Constructs a grant verifier with a separately pinned H7 artifact/OPE
    /// verifier.  Keeping the two trust roots explicit prevents a grant
    /// signer from silently becoming the H7 artifact signer.
    pub fn new_with_h7_verifier(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        verifying_key: VerifyingKey,
        h7_verifier: H7ArtifactVerifier,
    ) -> Result<Self, ProductionAuthorityError> {
        let signer_id = signer_id.into();
        validate_identifier(&signer_id, "verifier signer id")?;
        if signer_epoch == 0 || verifying_key.is_weak() {
            return Err(ProductionAuthorityError::Invalid(
                "verifier epoch or Ed25519 key is invalid".to_string(),
            ));
        }
        Ok(Self {
            signer_id,
            signer_epoch,
            keys: policy::AuthorityVerificationKeys::Classical(verifying_key),
            h7_verifier,
        })
    }

    pub fn from_bytes(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        public_key: [u8; 32],
    ) -> Result<Self, ProductionAuthorityError> {
        let key = VerifyingKey::from_bytes(&public_key).map_err(|_| {
            ProductionAuthorityError::Invalid("verifier public key is malformed".to_string())
        })?;
        Self::new(signer_id, signer_epoch, key)
    }

    /// Pins the grant key and the H7 artifact key independently from raw
    /// public-key material supplied out of band.
    pub fn from_bytes_with_h7_verifier(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        public_key: [u8; 32],
        h7_verifier: H7ArtifactVerifier,
    ) -> Result<Self, ProductionAuthorityError> {
        let key = VerifyingKey::from_bytes(&public_key).map_err(|_| {
            ProductionAuthorityError::Invalid("verifier public key is malformed".to_string())
        })?;
        Self::new_with_h7_verifier(signer_id, signer_epoch, key, h7_verifier)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify(
        &self,
        grant: &H7H89ProductionGrant,
        h7_envelope: &H7SignedArtifactEnvelope,
        agent_id: &AgentId,
        source_release: &str,
        target_release: &str,
        expected_control_revision: u64,
        expected_lifecycle_generation: u64,
        expected_authority_epoch: u64,
        now_unix_seconds: u64,
    ) -> Result<(), ProductionAuthorityError> {
        grant.validate_shape(h7_envelope)?;
        self.h7_verifier
            .verify_envelope_signature(h7_envelope, now_unix_seconds)
            .map_err(|error| ProductionAuthorityError::H7Binding(error.to_string()))?;
        if grant.agent_id != agent_id.to_string()
            || grant.source_release != source_release
            || grant.target_release != target_release
        {
            return Err(ProductionAuthorityError::Binding);
        }
        if grant.expected_control_revision != expected_control_revision {
            return Err(ProductionAuthorityError::ControlRevisionFence {
                expected: expected_control_revision,
                actual: grant.expected_control_revision,
            });
        }
        if grant.expected_lifecycle_generation != expected_lifecycle_generation {
            return Err(ProductionAuthorityError::LifecycleGenerationFence {
                expected: expected_lifecycle_generation,
                actual: grant.expected_lifecycle_generation,
            });
        }
        if grant.authority_epoch != expected_authority_epoch {
            return Err(ProductionAuthorityError::AuthorityEpochFence {
                expected: expected_authority_epoch,
                actual: grant.authority_epoch,
            });
        }
        if grant.signer_id != self.signer_id {
            return Err(ProductionAuthorityError::SignerMismatch);
        }
        if grant.signer_epoch != self.signer_epoch {
            return Err(ProductionAuthorityError::SignerEpochMismatch);
        }
        if now_unix_seconds < grant.issued_at_unix_seconds {
            return Err(ProductionAuthorityError::NotYetValid);
        }
        if now_unix_seconds >= grant.expires_at_unix_seconds {
            return Err(ProductionAuthorityError::Expired);
        }
        self.keys.verify_grant(grant)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify_recovery(
        &self,
        decision: &ProductionRecoveryDecision,
        agent_id: &AgentId,
        expected_grant_sha256: &Sha256Digest,
        expected_intent_sha256: &Sha256Digest,
        expected_transaction_sha256: &Sha256Digest,
        expected_release: &str,
        expected_manifest_sha256: &Sha256Digest,
        expected_agentd_sha256: &Sha256Digest,
        expected_matrixd_sha256: Option<&Sha256Digest>,
        expected_lifecycle_generation: u64,
        expected_authority_epoch: u64,
        now_unix_seconds: u64,
    ) -> Result<(), ProductionAuthorityError> {
        decision.validate_shape()?;
        if decision.agent_id != agent_id.to_string()
            || &decision.grant_sha256 != expected_grant_sha256
            || &decision.intent_sha256 != expected_intent_sha256
            || &decision.release_transaction_sha256 != expected_transaction_sha256
            || decision.observed_release != expected_release
            || &decision.observed_manifest_sha256 != expected_manifest_sha256
            || &decision.observed_agentd_sha256 != expected_agentd_sha256
            || decision.observed_matrixd_sha256.as_ref() != expected_matrixd_sha256
            || decision.expected_lifecycle_generation != expected_lifecycle_generation
            || decision.authority_epoch != expected_authority_epoch
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        let (signer_id, signer_epoch) = self
            .keys
            .recovery_identity(&self.signer_id, self.signer_epoch);
        if decision.signer_id != signer_id {
            return Err(ProductionAuthorityError::SignerMismatch);
        }
        if decision.signer_epoch != signer_epoch {
            return Err(ProductionAuthorityError::SignerEpochMismatch);
        }
        if now_unix_seconds < decision.issued_at_unix_seconds {
            return Err(ProductionAuthorityError::NotYetValid);
        }
        if now_unix_seconds >= decision.expires_at_unix_seconds {
            return Err(ProductionAuthorityError::Expired);
        }
        self.keys.verify_recovery(decision)
    }
}

impl H7H89ProductionGrant {
    pub fn digest(&self) -> &Sha256Digest {
        &self.grant_sha256
    }

    pub fn validate_shape(
        &self,
        h7_envelope: &H7SignedArtifactEnvelope,
    ) -> Result<(), ProductionAuthorityError> {
        h7_envelope
            .validate_shape()
            .map_err(|error| ProductionAuthorityError::H7Binding(error.to_string()))?;
        if !pq_wire::grant_shape(self)
            || !self.production_authority
            || !self.external_effects
            || !self.operator_acceptance
            || !self.promotion
            || self.governance_bypass
            || self.h7_envelope_sha256 != *h7_envelope.digest()
            || self.artifact_sha256 != *h7_envelope.artifact_digest()
        {
            return Err(ProductionAuthorityError::Boundary);
        }
        let parsed_agent = AgentId::parse(self.agent_id.clone())
            .map_err(|_| ProductionAuthorityError::Invalid("agent id is malformed".to_string()))?;
        let _ = parsed_agent;
        validate_release(&self.source_release)?;
        validate_release(&self.target_release)?;
        if self.source_release == self.target_release
            || self.authority_epoch == 0
            || self.signer_epoch == 0
            || self.expected_lifecycle_generation == 0
        {
            return Err(ProductionAuthorityError::Invalid(
                "grant CAS or signer fields are malformed".to_string(),
            ));
        }
        let transition_matches = matches!(
            (self.transition, h7_envelope.transition),
            (
                H7H89ProductionTransition::Upgrade,
                codex_hepta_memory::H7SignedArtifactTransition::Reload
            ) | (
                H7H89ProductionTransition::Rollback,
                codex_hepta_memory::H7SignedArtifactTransition::Rollback
            )
        );
        if !transition_matches {
            return Err(ProductionAuthorityError::TransitionBinding);
        }
        validate_identifier(&self.signer_id, "signer id")?;
        validate_window(self.issued_at_unix_seconds, self.expires_at_unix_seconds)?;
        parse_digest(&self.h7_envelope_sha256, "H7 envelope")?;
        parse_digest(&self.artifact_sha256, "H7 artifact")?;
        parse_digest(&self.grant_sha256, "grant")?;
        if self.grant_sha256 != self.payload_digest() {
            return Err(ProductionAuthorityError::DigestMismatch);
        }
        if !pq_wire::signature_encoding(&self.signature_base64, self.pq_authority.is_some()) {
            return Err(ProductionAuthorityError::SignatureMalformed);
        }
        Ok(())
    }

    pub fn payload_digest(&self) -> Sha256Digest {
        Sha256Digest::from_sha256_output(Sha256::digest(self.signing_bytes()))
    }

    fn signing_bytes(&self) -> Vec<u8> {
        if self.pq_authority.is_some() {
            return pq_wire::grant_message(self);
        }
        let mut hasher = Sha256::new();
        for value in [
            SIGNING_DOMAIN,
            self.namespace.as_bytes(),
            self.agent_id.as_bytes(),
            self.source_release.as_bytes(),
            self.target_release.as_bytes(),
            self.transition.as_str().as_bytes(),
            self.h7_envelope_sha256.as_str().as_bytes(),
            self.artifact_sha256.as_str().as_bytes(),
            self.signer_id.as_bytes(),
        ] {
            frame(&mut hasher, value);
        }
        frame(&mut hasher, &self.schema_version.to_be_bytes());
        frame(&mut hasher, &self.expected_control_revision.to_be_bytes());
        frame(
            &mut hasher,
            &self.expected_lifecycle_generation.to_be_bytes(),
        );
        frame(&mut hasher, &self.authority_epoch.to_be_bytes());
        frame(&mut hasher, &self.signer_epoch.to_be_bytes());
        frame(&mut hasher, &self.issued_at_unix_seconds.to_be_bytes());
        frame(&mut hasher, &self.expires_at_unix_seconds.to_be_bytes());
        for value in [
            self.production_authority,
            self.external_effects,
            self.operator_acceptance,
            self.promotion,
            self.governance_bypass,
        ] {
            frame(&mut hasher, &[u8::from(value)]);
        }
        hasher.finalize().to_vec()
    }
}

/// Receipt returned after a verified operation has been admitted to the
/// real supervisor.  `queued` means the process transition is in progress;
/// it is not a claim that the child has become healthy.
/// Authority flags describe the admission scope, never an observed effect
/// outcome. An `aborted` Unknown disposition has `promotion=false`; its
/// unresolved external effects remain in `ProductionMutationState` history.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionMutationReceipt {
    pub grant_sha256: Sha256Digest,
    pub agent_id: String,
    pub transition: H7H89ProductionTransition,
    pub source_release: String,
    pub target_release: String,
    pub control_revision: u64,
    pub status: ProductionMutationStatus,
    pub production_authority: bool,
    pub external_effects: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionMutationState {
    pub receipt: ProductionMutationReceipt,
    pub intent_sha256: Sha256Digest,
    pub release_transaction_sha256: Option<Sha256Digest>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub unknown_effects: Vec<crate::signed_intent::UnknownEffectDisposition>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductionMutationStatus {
    Queued,
    Committed,
    RolledBack,
    RecoveryRequired,
    Aborted,
}

impl ProductionMutationReceipt {
    pub(crate) fn queued(grant: &H7H89ProductionGrant, control_revision: u64) -> Self {
        Self {
            grant_sha256: grant.grant_sha256.clone(),
            agent_id: grant.agent_id.clone(),
            transition: grant.transition,
            source_release: grant.source_release.clone(),
            target_release: grant.target_release.clone(),
            control_revision,
            status: ProductionMutationStatus::Queued,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
        }
    }
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum ProductionAuthorityError {
    #[error("invalid production authority grant: {0}")]
    Invalid(String),
    #[error("production authority grant crosses its boundary")]
    Boundary,
    #[error("production authority grant does not bind the H7 envelope")]
    H7Binding(String),
    #[error("production authority grant transition does not bind the H7 transition")]
    TransitionBinding,
    #[error("production authority grant binding mismatch")]
    Binding,
    #[error(
        "production authority grant control revision fence mismatch: expected {expected}, actual {actual}"
    )]
    ControlRevisionFence { expected: u64, actual: u64 },
    #[error(
        "production authority grant lifecycle generation fence mismatch: expected {expected}, actual {actual}"
    )]
    LifecycleGenerationFence { expected: u64, actual: u64 },
    #[error(
        "production authority grant authority epoch fence mismatch: expected {expected}, actual {actual}"
    )]
    AuthorityEpochFence { expected: u64, actual: u64 },
    #[error("production authority grant signer identity mismatch")]
    SignerMismatch,
    #[error("production authority grant signer epoch mismatch")]
    SignerEpochMismatch,
    #[error("production authority grant is not yet valid")]
    NotYetValid,
    #[error("production authority grant has expired")]
    Expired,
    #[error("production authority grant signature is malformed")]
    SignatureMalformed,
    #[error("production authority grant signature verification failed")]
    SignatureInvalid,
    #[error("production authority grant digest mismatch")]
    DigestMismatch,
    #[error("production recovery decision does not bind the quarantined transaction")]
    RecoveryBinding,
}

fn frame(hasher: &mut Sha256, value: &[u8]) {
    hasher.update(u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    hasher.update(value);
}

fn validate_identifier(value: &str, label: &str) -> Result<(), ProductionAuthorityError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(ProductionAuthorityError::Invalid(format!(
            "{label} contains an invalid identifier"
        )));
    }
    Ok(())
}

fn validate_release(value: &str) -> Result<(), ProductionAuthorityError> {
    if value.trim().is_empty()
        || value.len() > 128
        || !value.is_ascii()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(ProductionAuthorityError::Invalid(
            "release identity is malformed".to_string(),
        ));
    }
    Ok(())
}

fn validate_window(issued: u64, expires: u64) -> Result<(), ProductionAuthorityError> {
    if issued == 0 || expires <= issued || expires - issued > SIGNED_AUTHORITY_MAX_LIFETIME_SECONDS
    {
        return Err(ProductionAuthorityError::Invalid(
            "authority grant validity window is malformed".to_string(),
        ));
    }
    Ok(())
}

fn parse_digest(
    digest: &Sha256Digest,
    label: &'static str,
) -> Result<(), ProductionAuthorityError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| ProductionAuthorityError::Invalid(format!("{label} digest is malformed")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_memory::H7ArtifactSigner;
    use codex_hepta_memory::H7ArtifactVerifier;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7SignedArtifactTransition;

    fn h7() -> H7SignedArtifactEnvelope {
        let mut runtime = H7QualificationRuntime::new();
        let fence = Sha256Digest::for_bytes(b"fence");
        let event = codex_hepta_memory::H7TrajectoryEvent::new(
            "production-trajectory",
            1,
            "reload",
            100,
            true,
            1,
            1,
            1,
            fence,
        )
        .expect("event");
        runtime.append_trajectory_event(event).expect("append");
        runtime
            .evaluate_trajectory("production-trajectory")
            .expect("evaluate");
        let artifact = runtime
            .propose_artifact("artifact-production", "production-trajectory", 1)
            .expect("artifact");
        let signer = H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32]).expect("h7 signer");
        signer
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Reload,
                0,
                None,
                100,
                200,
            )
            .expect("h7 envelope")
    }

    fn h7_verifier() -> H7ArtifactVerifier {
        H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32])
            .expect("h7 signer")
            .verifier()
    }

    #[test]
    fn external_grant_binds_h7_and_all_cas_fences() {
        let envelope = h7();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let signer =
            H7H89ProductionGrantSigner::from_seed("operator", 4, [9; 32]).expect("grant signer");
        let grant = signer
            .sign(
                &agent,
                "release-v2",
                "release-v3",
                H7H89ProductionTransition::Upgrade,
                &envelope,
                8,
                11,
                3,
                100,
                200,
            )
            .expect("grant");
        let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
            "operator",
            4,
            signer.verifying_key(),
            h7_verifier(),
        )
        .expect("verifier");
        verifier
            .verify(
                &grant,
                &envelope,
                &agent,
                "release-v2",
                "release-v3",
                8,
                11,
                3,
                150,
            )
            .expect("verify");
        assert_eq!(grant.h7_envelope_sha256, *envelope.digest());
        assert!(grant.production_authority);
        assert!(grant.external_effects);
        assert!(grant.operator_acceptance);
        assert!(grant.promotion);
        assert!(!grant.governance_bypass);
    }

    #[test]
    fn tampering_or_stale_fence_is_rejected_before_signature_use() {
        let envelope = h7();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let signer =
            H7H89ProductionGrantSigner::from_seed("operator", 4, [9; 32]).expect("grant signer");
        let grant = signer
            .sign(
                &agent,
                "release-v2",
                "release-v3",
                H7H89ProductionTransition::Upgrade,
                &envelope,
                8,
                11,
                3,
                100,
                200,
            )
            .expect("grant");
        let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
            "operator",
            4,
            signer.verifying_key(),
            h7_verifier(),
        )
        .expect("verifier");
        assert_eq!(
            verifier.verify(
                &grant,
                &envelope,
                &agent,
                "release-v2",
                "release-v3",
                9,
                11,
                3,
                150
            ),
            Err(ProductionAuthorityError::ControlRevisionFence {
                expected: 9,
                actual: 8,
            })
        );
        let mut tampered = grant;
        tampered.target_release = "release-v4".to_string();
        assert_eq!(
            verifier.verify(
                &tampered,
                &envelope,
                &agent,
                "release-v2",
                "release-v4",
                8,
                11,
                3,
                150
            ),
            Err(ProductionAuthorityError::DigestMismatch)
        );
    }
}
