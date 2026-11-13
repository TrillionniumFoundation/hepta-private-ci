//! Existing Root-pinned learning trust for the fixed Source disclosure.
//! Activation verifies the original signed distribution; it neither rotates
//! the ledger nor creates a root, signer, grant or replacement trust history.

use std::io;
use std::path::Path;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::{ActivatedLearningTrustV1, LearningEvidenceRoleV1,
    LearningEvidenceTrustV1, LearningTrustDistributionV1, LearningTrustRootV1,
    SignedLearningTrustDistributionV1, TrustedLearningSignerV1, activate_learning_trust};
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::{OriginalHostTrust, digest};
use crate::authority_host_config::read_root_json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct OriginalDistributionPin {
    root_id: String,
    root_digest: String,
    distribution_id: String,
    distribution_digest: String,
    generation: u64,
    evidence_trust_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RootFile {
    schema_version: u32,
    purpose: String,
    root_id: String,
    scope_digest: String,
    verifying_key: [u8; 32],
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DistributionFile {
    schema_version: u32,
    purpose: String,
    distribution_id: String,
    generation: u64,
    effective_at: u64,
    root_id: String,
    issued_at: u64,
    expires_at: u64,
    signature: String,
}

pub(in super::super) struct OriginalSourceTrust {
    pub(in super::super) evidence: OriginalHostTrust,
    root: LearningTrustRootV1,
    signed: SignedLearningTrustDistributionV1,
    activated: ActivatedLearningTrustV1,
}

impl OriginalSourceTrust {
    pub(in super::super) fn read_original_signed_distribution(
        evidence_path: &Path, root_path: &Path, distribution_path: &Path,
        pin: &OriginalDistributionPin, at: u64,
    ) -> io::Result<Self> {
        let evidence = OriginalHostTrust::read(evidence_path)?;
        let root: RootFile = read_root_json(root_path)?;
        let signed: DistributionFile = read_root_json(distribution_path)?;
        if root.schema_version != 1 || root.purpose != "hepta.root.learning-trust-root.v1"
            || signed.schema_version != 1
            || signed.purpose != "hepta.root.original-learning-trust-distribution.v1"
        { return Err(io::Error::other("original learning trust purpose differs")); }
        let root = LearningTrustRootV1 {
            root_id: StableId::new(root.root_id).map_err(io::Error::other)?,
            scope_digest: digest(&root.scope_digest)?, verifying_key: root.verifying_key,
            valid_from: root.valid_from, expires_at: root.expires_at, revoked_at: root.revoked_at,
        };
        let signature = STANDARD_NO_PAD.decode(&signed.signature).map_err(io::Error::other)?;
        if signature.len() != 64 || STANDARD_NO_PAD.encode(&signature) != signed.signature {
            return Err(io::Error::other("original distribution signature encoding differs"));
        }
        let signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new(signed.distribution_id).map_err(io::Error::other)?,
                generation: signed.generation, effective_at: signed.effective_at,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: evidence.verifier.scope_digest(),
                    objective_digest: evidence.verifier.objective_digest(),
                    authority_epoch: evidence.verifier.authority_epoch(),
                    signers: evidence.signers.clone(),
                },
            },
            root_id: StableId::new(signed.root_id).map_err(io::Error::other)?,
            issued_at: signed.issued_at, expires_at: signed.expires_at,
            signature: signature.try_into().map_err(|_| io::Error::other("original signature width differs"))?,
        };
        // None here validates one already selected immutable distribution. It
        // is not a request to advance an existing ledger's trust generation.
        let activated = activate_learning_trust(&root, signed.clone(), None, at)
            .map_err(io::Error::other)?;
        if activated.root_id().as_str() != pin.root_id
            || activated.root_digest() != digest(&pin.root_digest)?
            || activated.distribution_id().as_str() != pin.distribution_id
            || activated.distribution_digest() != digest(&pin.distribution_digest)?
            || activated.generation() != pin.generation
            || activated.verifier().trust_digest() != digest(&pin.evidence_trust_digest)?
            || activated.verifier().trust_digest() != evidence.verifier.trust_digest()
        { return Err(io::Error::other("original protected trust pins differ")); }
        Ok(Self { evidence, root, signed, activated })
    }

    pub(in super::super) fn require_original_distribution_window(&self, at: u64) -> io::Result<()> {
        let actual = activate_learning_trust(&self.root, self.signed.clone(), None, at)
            .map_err(io::Error::other)?;
        if actual.root_id() != self.activated.root_id()
            || actual.root_digest() != self.activated.root_digest()
            || actual.distribution_id() != self.activated.distribution_id()
            || actual.distribution_digest() != self.activated.distribution_digest()
            || actual.generation() != self.activated.generation()
            || actual.verifier().trust_digest() != self.evidence.verifier.trust_digest()
        { return Err(io::Error::other("original immutable trust changed")); }
        Ok(())
    }

    pub(in super::super) fn original_activation(&self) -> ActivatedLearningTrustV1 {
        self.activated.clone()
    }

    pub(in super::super) fn original_signer(
        &self, actor: &StableId, role: LearningEvidenceRoleV1, at: u64,
    ) -> io::Result<TrustedLearningSignerV1> {
        self.require_original_distribution_window(at)?;
        let signer = self.evidence.signers.iter()
            .find(|value| &value.principal.principal_id == actor)
            .ok_or_else(|| io::Error::other("original disclosed actor is not enrolled"))?;
        self.evidence.verifier.require_signer_binding(role, signer, at).map_err(io::Error::other)?;
        Ok(signer.clone())
    }
}
