//! Role-specific local issuer using already activated host trust. It neither
//! creates identities nor declares controller independence; installers must
//! provision distinct role owners and the verifier rechecks them on each use.

use std::fs::File;
use std::io::Read;
use std::path::Path;

use codex_hepta_agent_components::types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

pub struct AgentdSelfIterationLocalSignerV1 {
    trust: Arc<ActivatedLearningTrustV1>,
    principal_id: StableId,
    role: LearningEvidenceRoleV1,
    key: SigningKey,
}
impl AgentdSelfIterationLocalSignerV1 {
    pub fn from_existing_private_key(
        trust: Arc<ActivatedLearningTrustV1>,
        principal_id: StableId,
        role: LearningEvidenceRoleV1,
        path: &Path,
    ) -> Result<Self, AgentdError> {
        if !matches!(
            role,
            LearningEvidenceRoleV1::Generator
                | LearningEvidenceRoleV1::Evaluator
                | LearningEvidenceRoleV1::Selector
                | LearningEvidenceRoleV1::Observer
        ) || !path.is_absolute()
        {
            return Err(invalid("local iteration signer role or path"));
        }
        let metadata = std::fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() != 32 {
            return Err(invalid(
                "local signer key must be a regular 32-byte private file",
            ));
        }
        let parent =
            std::fs::symlink_metadata(path.parent().ok_or_else(|| invalid("key parent"))?)?;
        if !parent.is_dir() || parent.file_type().is_symlink() {
            return Err(invalid("local signer key parent"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.mode() & 0o077 != 0 || metadata.nlink() != 1 || parent.mode() & 0o077 != 0 {
                return Err(invalid("local signer key must be private and unlinked"));
            }
        }
        let file = File::open(path)?;
        let opened = file.metadata()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if opened.dev() != metadata.dev() || opened.ino() != metadata.ino() {
                return Err(invalid("local signer key identity changed"));
            }
        }
        let mut bytes = Vec::new();
        file.take(33).read_to_end(&mut bytes)?;
        let mut seed: [u8; 32] = bytes
            .as_slice()
            .try_into()
            .map_err(|_| invalid("local signer key size changed"))?;
        bytes.fill(0);
        let key = SigningKey::from_bytes(&seed);
        seed.fill(0);
        Ok(Self {
            trust,
            principal_id,
            role,
            key,
        })
    }

    pub fn principal_id(&self) -> &StableId {
        &self.principal_id
    }

    /// Signs factual payloads for this installed role only. Model text must be
    /// measured/compiled by the owning adapter before it reaches this method.
    pub fn sign_payload(
        &self,
        payload: &[u8],
        issued_at_ms: u64,
        expires_at_ms: u64,
    ) -> Result<SignedLearningEvidenceV1, AgentdError> {
        if payload.is_empty()
            || payload.len() > 64 * 1024
            || expires_at_ms <= issued_at_ms
            || expires_at_ms > issued_at_ms.saturating_add(3_600_000)
        {
            return Err(invalid("local evidence payload or lifetime"));
        }
        let verifier = self.trust.verifier();
        let digest = Digest32::of_bytes(payload);
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: StableId::new(format!("local.{digest}"))
                .map_err(|error| invalid(error.to_string()))?,
            principal_id: self.principal_id.clone(),
            role: self.role,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: verifier.authority_epoch(),
            issued_at: issued_at_ms,
            expires_at: expires_at_ms,
            payload_digest: digest,
            signature: [0; 64],
        };
        evidence.signature = self.key.sign(&evidence.signing_bytes()).to_bytes();
        verifier
            .verify(self.role, &evidence, payload, issued_at_ms)
            .map_err(|error| invalid(format!("installed local role cannot sign: {error}")))?;
        Ok(evidence)
    }
}

#[cfg(test)]
#[path = "self_iteration_signer_tests.rs"]
mod tests;
