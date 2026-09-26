//! Owner-controlled trust registry for kernel.evidence production ingress.

use std::collections::BTreeSet;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::IssuerLifecycleState;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceIssuerTrustBindingV1;
use codex_hepta_types::Digest32;
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
        let bytes = read_owner_file(path, identity)?;
        let trust: Self = serde_json::from_slice(&bytes)?;
        if trust.schema_version != 1
            || trust.agent_id != identity.agent_id.as_str()
            || trust.issuers.is_empty()
            || trust.issuers.len() > MAX_EVIDENCE_ISSUERS
        {
            return Err(invalid(
                "evidence trust registry owner, schema or issuer bound is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        for issuer in &trust.issuers {
            if !identities.insert(issuer.issuer_id.clone())
                || issuer.roles.is_empty()
                || issuer.roles.len() > MAX_EVIDENCE_ROLES_PER_ISSUER
            {
                return Err(invalid(
                    "evidence trust registry has duplicate issuer identities or invalid role bounds",
                ));
            }
            StableId::new(issuer.issuer_id.clone()).map_err(|error| invalid(&error.to_string()))?;
            Generation::new(issuer.key_epoch).map_err(|error| invalid(&error.to_string()))?;
            VerifyingKey::from_bytes(&hex_bytes(&issuer.public_key_hex)?)
                .map_err(|_| invalid("invalid registered Ed25519 public key"))?;
            let mut roles = BTreeSet::new();
            for role in &issuer.roles {
                let parsed = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                if !roles.insert(parsed) {
                    return Err(invalid("evidence trust registry contains duplicate roles"));
                }
            }
        }
        Ok(trust)
    }

    pub(crate) async fn reconcile_all(
        &self,
        authority: &AuthBusAuthorityHost,
    ) -> Result<(), AgentdError> {
        for configured in &self.issuers {
            self.reconcile_configured(configured, authority).await?;
        }
        Ok(())
    }

    pub(crate) async fn verification_bindings(
        &self,
        authority: &AuthBusAuthorityHost,
    ) -> Result<Vec<EvidenceIssuerTrustBindingV1>, AgentdError> {
        let mut bindings = Vec::new();
        for configured in &self.issuers {
            if configured.revoked {
                continue;
            }
            let issuer = self.reconcile_configured(configured, authority).await?;
            for role in &configured.roles {
                let role = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                bindings.push(EvidenceIssuerTrustBindingV1::from_registration(
                    &issuer, role,
                ));
            }
        }
        Ok(bindings)
    }

    pub(crate) async fn issuer_for(
        &self,
        authority: &AuthBusAuthorityHost,
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
        self.reconcile_configured(configured, authority).await
    }

    async fn reconcile_configured(
        &self,
        configured: &EvidenceIssuerTrust,
        authority: &AuthBusAuthorityHost,
    ) -> Result<IssuerRegistration, AgentdError> {
        let issuer_id = StableId::new(&configured.issuer_id)
            .map_err(|error| invalid(&error.to_string()))?;
        let key_epoch = Generation::new(configured.key_epoch)
            .map_err(|error| invalid(&error.to_string()))?;
        let verifying_key = VerifyingKey::from_bytes(&hex_bytes(&configured.public_key_hex)?)
            .map_err(|_| invalid("invalid registered Ed25519 public key"))?;
        let expected_key_digest = Digest32::of_bytes(verifying_key.as_bytes());
        let mut record = match authority
            .issuer_record(IssuerPurpose::Message, &issuer_id, key_epoch)
            .await
        {
            Ok(record) => record,
            Err(AuthBusAuthorityError::IssuerMissing) => authority
                .enroll_issuer(
                    IssuerPurpose::Message,
                    IssuerSpec {
                        issuer_id: issuer_id.clone(),
                        key_epoch,
                        verifying_key,
                    },
                )
                .await
                .map_err(|error| {
                    invalid(&format!(
                        "durable evidence issuer enrollment failed; explicit rotation may be required: {error}"
                    ))
                })?,
            Err(error) => {
                return Err(invalid(&format!(
                    "durable evidence issuer lookup failed: {error}"
                )));
            }
        };
        if record.purpose() != IssuerPurpose::Message
            || record.issuer_id() != &issuer_id
            || record.key_epoch() != key_epoch
            || record.verifying_key_digest() != expected_key_digest
        {
            return Err(invalid(
                "evidence trust entry differs from the durable issuer registry",
            ));
        }
        if configured.revoked && record.state() == IssuerLifecycleState::Active {
            record = authority
                .revoke_issuer(
                    IssuerPurpose::Message,
                    &issuer_id,
                    key_epoch,
                    record.revision(),
                )
                .await
                .map_err(|error| {
                    invalid(&format!("durable evidence issuer revocation failed: {error}"))
                })?;
        }
        if !configured.revoked && record.state() != IssuerLifecycleState::Active {
            return Err(invalid(
                "evidence trust file attempts to reactivate a revoked or retired issuer",
            ));
        }
        authority
            .verify_message_issuer(&issuer_id, key_epoch)
            .await
            .map_err(|error| invalid(&format!("evidence issuer handle failed: {error}")))
    }
}

#[cfg(unix)]
fn read_owner_file(path: &Path, identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "evidence trust file must be a direct child of the canonical Agent home",
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
        || before.len() > MAX_EVIDENCE_TRUST_FILE_BYTES
    {
        return Err(invalid(
            "evidence trust file must be a private owner-controlled regular file",
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
        return Err(invalid("evidence trust file changed while opening"));
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
        return Err(invalid("evidence trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_owner_file(_path: &Path, _identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the kernel evidence trust-file profile currently requires Unix ownership checks",
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
