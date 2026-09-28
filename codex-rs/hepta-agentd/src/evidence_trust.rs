//! Owner-controlled trust registry for kernel.evidence production ingress.

use std::collections::BTreeSet;
use std::path::Path;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PrivateIssuerRegistryDocument;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceIssuerTrustBindingV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
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
struct EvidenceTrustDocument {
    schema_version: u32,
    agent_id: String,
    issuers: Vec<EvidenceIssuerTrust>,
}

pub(crate) struct EvidenceTrust {
    issuers: Vec<EvidenceIssuerTrust>,
    registry: PrivateIssuerRegistryDocument,
}

impl EvidenceTrust {
    pub(crate) fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let registry = PrivateIssuerRegistryDocument::load(
            path,
            &identity.home_root,
            MAX_EVIDENCE_TRUST_FILE_BYTES,
        )
        .map_err(|error| invalid(&error.to_string()))?;
        let document: EvidenceTrustDocument = serde_json::from_slice(registry.bytes())?;
        if document.schema_version != 1
            || document.agent_id != identity.agent_id.as_str()
            || document.issuers.is_empty()
            || document.issuers.len() > MAX_EVIDENCE_ISSUERS
        {
            return Err(invalid(
                "evidence trust registry owner, schema or issuer bound is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        for issuer in &document.issuers {
            if !identities.insert((issuer.issuer_id.clone(), issuer.key_epoch))
                || issuer.roles.is_empty()
                || issuer.roles.len() > MAX_EVIDENCE_ROLES_PER_ISSUER
            {
                return Err(invalid(
                    "evidence trust registry has duplicate issuer epochs or invalid role bounds",
                ));
            }
            let issuer_id = StableId::new(issuer.issuer_id.clone())
                .map_err(|error| invalid(&error.to_string()))?;
            let key_epoch =
                Generation::new(issuer.key_epoch).map_err(|error| invalid(&error.to_string()))?;
            let _: [u8; 32] = hex_bytes(&issuer.public_key_hex)?;
            let registration = registry
                .message_issuer(&issuer_id, key_epoch)
                .map_err(|error| invalid(&error.to_string()))?;
            if registration.revoked != issuer.revoked {
                return Err(invalid("evidence issuer revocation state is inconsistent"));
            }
            let mut roles = BTreeSet::new();
            for role in &issuer.roles {
                let parsed = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                if !roles.insert(parsed) {
                    return Err(invalid("evidence trust registry contains duplicate roles"));
                }
            }
        }
        Ok(Self {
            issuers: document.issuers,
            registry,
        })
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
        let issuer_id =
            StableId::new(&configured.issuer_id).map_err(|error| invalid(&error.to_string()))?;
        let key_epoch =
            Generation::new(configured.key_epoch).map_err(|error| invalid(&error.to_string()))?;
        let registration = self
            .registry
            .message_issuer(&issuer_id, key_epoch)
            .map_err(|error| invalid(&error.to_string()))?;
        if registration.revoked != configured.revoked {
            return Err(invalid("evidence issuer revocation state is inconsistent"));
        }
        Ok(registration)
    }
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
