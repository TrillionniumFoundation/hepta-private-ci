//! Owner-controlled trust registry for kernel.evidence production ingress.

use std::collections::BTreeSet;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceIssuerTrustBindingV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;

const MAX_EVIDENCE_ISSUERS: usize = 32;
const MAX_EVIDENCE_ROLES_PER_ISSUER: usize = 16;
const MAX_EVIDENCE_TRUST_FILE_BYTES: u64 = 32_768;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceIssuerTrust {
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    roles: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct EvidenceTrust {
    schema_version: u32,
    agent_id: String,
    issuers: Vec<EvidenceIssuerTrust>,
}

impl EvidenceTrust {
    pub(crate) fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        Self::load_with_digest(path, identity).map(|(trust, _)| trust)
    }

    pub(crate) fn load_with_digest(
        path: &Path,
        identity: &AgentdIdentity,
    ) -> Result<(Self, Sha256Digest), AgentdError> {
        let bytes = read_owner_file(path, identity)?;
        let digest = Sha256Digest::for_bytes(&bytes);
        let trust: Self = serde_json::from_slice(&bytes)?;
        trust.validate(identity)?;
        Ok((trust, digest))
    }

    fn validate(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.schema_version != 1
            || self.agent_id != identity.agent_id.as_str()
            || self.issuers.is_empty()
            || self.issuers.len() > MAX_EVIDENCE_ISSUERS
        {
            return Err(invalid(
                "evidence trust registry owner, schema or issuer bound is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        for issuer in &self.issuers {
            if !identities.insert((issuer.issuer_id.clone(), issuer.key_epoch))
                || issuer.roles.is_empty()
                || issuer.roles.len() > MAX_EVIDENCE_ROLES_PER_ISSUER
            {
                return Err(invalid(
                    "evidence trust registry has duplicate issuer epochs or invalid role bounds",
                ));
            }
            StableId::new(issuer.issuer_id.clone()).map_err(|error| invalid(&error.to_string()))?;
            Generation::new(issuer.key_epoch).map_err(|error| invalid(&error.to_string()))?;
            let _: [u8; 32] = hex_bytes(&issuer.public_key_hex)?;
            let mut roles = BTreeSet::new();
            for role in &issuer.roles {
                let parsed = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                if !roles.insert(parsed) {
                    return Err(invalid("evidence trust registry contains duplicate roles"));
                }
            }
        }
        Ok(())
    }

    pub(crate) fn verification_bindings(
        &self,
    ) -> Result<Vec<EvidenceIssuerTrustBindingV1>, AgentdError> {
        let mut bindings = Vec::new();
        for configured in &self.issuers {
            if configured.revoked {
                continue;
            }
            for role in &configured.roles {
                let role = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                let issuer = self.issuer_for(&configured.issuer_id, configured.key_epoch, role)?;
                bindings.push(EvidenceIssuerTrustBindingV1::from_registration(
                    &issuer, role,
                ));
            }
        }
        Ok(bindings)
    }

    pub(crate) fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: EvidenceIssuerRoleV1,
    ) -> Result<IssuerRegistration, AgentdError> {
        let configured = self
            .issuers
            .iter()
            .find(|issuer| issuer.issuer_id == issuer_id && issuer.key_epoch == key_epoch)
            .ok_or_else(|| invalid("evidence issuer/key epoch is not registered"))?;
        if !configured
            .roles
            .iter()
            .any(|configured_role| configured_role == role.as_str())
        {
            return Err(invalid(
                "evidence issuer is not registered for the requested role",
            ));
        }
        Ok(IssuerRegistration {
            issuer_id: StableId::new(&configured.issuer_id)
                .map_err(|error| invalid(&error.to_string()))?,
            key_epoch: Generation::new(configured.key_epoch)
                .map_err(|error| invalid(&error.to_string()))?,
            verifying_key: VerifyingKey::from_bytes(&hex_bytes(&configured.public_key_hex)?)
                .map_err(|_| invalid("invalid registered Ed25519 public key"))?,
            revoked: configured.revoked,
        })
    }
}

#[cfg(unix)]
pub(crate) fn read_owner_file(
    path: &Path,
    identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "evidence owner file must be a direct child of the canonical Agent home",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let before = std::fs::symlink_metadata(path)?;
    if !home.is_dir()
        || home.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != home.uid()
        || before.mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > MAX_EVIDENCE_TRUST_FILE_BYTES
    {
        return Err(invalid(
            "evidence owner file must be a non-empty private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity_tuple = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity_tuple(&opened) != identity_tuple(&before) {
        return Err(invalid("evidence owner file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_EVIDENCE_TRUST_FILE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_EVIDENCE_TRUST_FILE_BYTES
        || !after.is_file()
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(invalid("evidence owner file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
pub(crate) fn read_owner_file(
    _path: &Path,
    _identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the kernel evidence owner-file profile currently requires Unix ownership checks",
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
