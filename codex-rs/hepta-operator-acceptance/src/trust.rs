use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;

use crate::AcceptanceError;
use crate::durable::canonical_json;
use crate::durable::secure_canonical_file_path;
use crate::durable::secure_read;
use crate::durable::sha256;
use crate::model::OperatorBinding;
use crate::sshsig::MAX_SIGNATURE_BYTES;
use crate::sshsig::verify_ed25519;

pub(crate) const SSHSIG_NAMESPACE: &str = "hepta-vnext-operator-acceptance-v1";
pub(crate) const SIGNATURE_ALGORITHM: &str = "openssh-sshsig-ed25519";
pub(crate) const TRUST_POLICY_SCOPE: &str =
    "externally_pinned_single_ed25519_external_revocation_responsibility_no_local_krl_v1";
const TRUST_POLICY_SCHEMA: &str = "hepta_operator_acceptance_trust_policy_v1";
const MAX_TRUST_FILE_BYTES: usize = 16 * 1024;

pub(crate) struct TrustAnchor {
    pub binding: OperatorBinding,
    allowed_signers_bytes: Vec<u8>,
}

pub(crate) struct TrustInputs<'a> {
    pub acceptance_store_root: &'a Path,
    pub allowed_signers_path: &'a Path,
    pub externally_pinned_trust_policy_sha256: &'a str,
    pub trust_policy_path: &'a Path,
}

pub(crate) struct VerifiedSignature {
    pub detached_signature_sha256: String,
    pub detached_signature_sshsig_base64: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TrustPolicy {
    acceptance_store_root: String,
    allowed_signers_sha256: String,
    key_fingerprint: String,
    maximum_lifetime_seconds: u64,
    principal: String,
    schema: String,
    schema_version: u32,
    trust_policy_scope: String,
    trust_root_id: String,
    trust_root_revision: u64,
}

impl TrustAnchor {
    pub fn load(inputs: TrustInputs<'_>) -> Result<Self, AcceptanceError> {
        if !digest_shape(inputs.externally_pinned_trust_policy_sha256) {
            return Err(invalid(
                "externally pinned trust-policy digest is malformed",
            ));
        }
        let policy_path = secure_canonical_file_path(inputs.trust_policy_path, "trust policy")?;
        let policy_bytes = secure_read(&policy_path, MAX_TRUST_FILE_BYTES)?;
        if sha256(&policy_bytes) != inputs.externally_pinned_trust_policy_sha256 {
            return Err(invalid(
                "trust policy differs from its independently supplied digest",
            ));
        }
        let policy: TrustPolicy = serde_json::from_slice(&policy_bytes)
            .map_err(|error| invalid(format!("invalid trust policy: {error}")))?;
        if canonical_json(&policy)? != policy_bytes {
            return Err(invalid("trust policy is not canonical JSON"));
        }
        validate_policy(&policy)?;
        let acceptance_store_root = inputs
            .acceptance_store_root
            .to_str()
            .ok_or_else(|| invalid("acceptance store root is not UTF-8"))?;
        if policy.acceptance_store_root != acceptance_store_root {
            return Err(invalid(
                "sidecar differs from the acceptance store pinned by external policy",
            ));
        }

        let allowed_path =
            secure_canonical_file_path(inputs.allowed_signers_path, "allowed_signers")?;
        let allowed_signers_bytes = secure_read(&allowed_path, MAX_TRUST_FILE_BYTES)?;
        let actual_allowed_sha256 = sha256(&allowed_signers_bytes);
        if actual_allowed_sha256 != policy.allowed_signers_sha256 {
            return Err(invalid(
                "allowed_signers differs from the externally pinned trust policy",
            ));
        }
        let fingerprint = parse_allowed_signer(&allowed_signers_bytes, &policy.principal)?;
        if fingerprint != policy.key_fingerprint {
            return Err(invalid(
                "allowed_signers key differs from the externally pinned fingerprint",
            ));
        }

        Ok(Self {
            binding: OperatorBinding {
                acceptance_store_root: policy.acceptance_store_root,
                allowed_signers_sha256: actual_allowed_sha256,
                key_fingerprint: fingerprint,
                maximum_lifetime_seconds: policy.maximum_lifetime_seconds,
                principal: policy.principal,
                trust_policy_scope: policy.trust_policy_scope,
                trust_policy_sha256: inputs.externally_pinned_trust_policy_sha256.to_string(),
                trust_root_id: policy.trust_root_id,
                trust_root_revision: policy.trust_root_revision,
            },
            allowed_signers_bytes,
        })
    }

    pub fn verify(
        &self,
        statement: &[u8],
        signature_path: &Path,
    ) -> Result<VerifiedSignature, AcceptanceError> {
        let signature_path =
            secure_canonical_file_path(signature_path, "detached SSHSIG signature")?;
        let signature_bytes = secure_read(&signature_path, MAX_SIGNATURE_BYTES)?;
        self.verify_bytes(statement, &signature_bytes)
    }

    pub fn verify_base64(
        &self,
        statement: &[u8],
        signature_base64: &str,
    ) -> Result<VerifiedSignature, AcceptanceError> {
        if signature_base64.len() > MAX_SIGNATURE_BYTES.div_ceil(3) * 4 {
            return Err(invalid("stored SSHSIG base64 exceeds its read bound"));
        }
        let signature_bytes = STANDARD
            .decode(signature_base64)
            .map_err(|_| invalid("stored SSHSIG base64 is malformed"))?;
        if STANDARD.encode(&signature_bytes) != signature_base64 {
            return Err(invalid("stored SSHSIG base64 is not canonical"));
        }
        self.verify_bytes(statement, &signature_bytes)
    }

    fn verify_bytes(
        &self,
        statement: &[u8],
        signature_bytes: &[u8],
    ) -> Result<VerifiedSignature, AcceptanceError> {
        // Binding is receipt metadata, not a replaceable verification authority.
        let fingerprint =
            parse_allowed_signer(&self.allowed_signers_bytes, &self.binding.principal)?;
        if fingerprint != self.binding.key_fingerprint {
            return Err(invalid(
                "signature binding differs from the private trust anchor",
            ));
        }
        verify_ed25519(statement, signature_bytes, &fingerprint, SSHSIG_NAMESPACE)?;
        Ok(VerifiedSignature {
            detached_signature_sha256: sha256(signature_bytes),
            detached_signature_sshsig_base64: STANDARD.encode(signature_bytes),
        })
    }
}

fn validate_policy(policy: &TrustPolicy) -> Result<(), AcceptanceError> {
    validate_identifier(&policy.principal, "operator principal")?;
    validate_identifier(&policy.trust_root_id, "trust root id")?;
    if policy.schema != TRUST_POLICY_SCHEMA
        || policy.schema_version != 1
        || policy.trust_policy_scope != TRUST_POLICY_SCOPE
    {
        return Err(invalid("trust policy schema or scope is not V1"));
    }
    if policy.trust_root_revision == 0 {
        return Err(invalid("trust root revision must be nonzero"));
    }
    if policy.maximum_lifetime_seconds == 0 || policy.maximum_lifetime_seconds > 3_600 {
        return Err(invalid(
            "maximum acceptance lifetime must be within 1..=3600 seconds",
        ));
    }
    if !digest_shape(&policy.allowed_signers_sha256) {
        return Err(invalid("trust policy allowed_signers digest is malformed"));
    }
    if !policy.key_fingerprint.starts_with("SHA256:")
        || policy.key_fingerprint.len() < 16
        || policy.key_fingerprint.len() > 64
        || !policy
            .key_fingerprint
            .bytes()
            .skip(7)
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'/'))
    {
        return Err(invalid("trust policy Ed25519 fingerprint is malformed"));
    }
    Ok(())
}

fn parse_allowed_signer(bytes: &[u8], principal: &str) -> Result<String, AcceptanceError> {
    let text = std::str::from_utf8(bytes).map_err(|_| invalid("allowed_signers is not UTF-8"))?;
    if !text.ends_with('\n') || text.contains('\r') {
        return Err(invalid(
            "allowed_signers must be LF-terminated UTF-8 without carriage returns",
        ));
    }
    let lines = text.lines().collect::<Vec<_>>();
    if lines.len() != 1 {
        return Err(invalid(
            "V1 trust anchor must contain exactly one allowed signer",
        ));
    }
    let fields = lines[0].split_ascii_whitespace().collect::<Vec<_>>();
    if fields.len() != 3 || fields[0] != principal || fields[1] != "ssh-ed25519" {
        return Err(invalid(
            "allowed_signers must map the pinned principal to one raw Ed25519 key",
        ));
    }
    let blob = STANDARD
        .decode(fields[2])
        .map_err(|_| invalid("allowed_signers Ed25519 key is not valid base64"))?;
    validate_ed25519_blob(&blob)?;
    Ok(format!(
        "SHA256:{}",
        STANDARD_NO_PAD.encode(sha2::Sha256::digest(&blob))
    ))
}

fn validate_ed25519_blob(blob: &[u8]) -> Result<(), AcceptanceError> {
    let (algorithm, rest) = take_ssh_string(blob)?;
    let (key, rest) = take_ssh_string(rest)?;
    let key: [u8; 32] = key
        .try_into()
        .map_err(|_| invalid("allowed_signers Ed25519 key must be 32 bytes"))?;
    let verifying_key = VerifyingKey::from_bytes(&key)
        .map_err(|_| invalid("allowed_signers contains an invalid Ed25519 point"))?;
    if algorithm != b"ssh-ed25519" || !rest.is_empty() || verifying_key.is_weak() {
        return Err(invalid(
            "allowed_signers contains a malformed or weak Ed25519 key blob",
        ));
    }
    Ok(())
}

fn take_ssh_string(bytes: &[u8]) -> Result<(&[u8], &[u8]), AcceptanceError> {
    let prefix: [u8; 4] = bytes
        .get(..4)
        .ok_or_else(|| invalid("truncated SSH public key blob"))?
        .try_into()
        .map_err(|_| invalid("truncated SSH public key length"))?;
    let length = usize::try_from(u32::from_be_bytes(prefix))
        .map_err(|_| invalid("SSH public key length overflow"))?;
    let end = 4_usize
        .checked_add(length)
        .ok_or_else(|| invalid("SSH public key length overflow"))?;
    let value = bytes
        .get(4..end)
        .ok_or_else(|| invalid("truncated SSH public key value"))?;
    let rest = bytes
        .get(end..)
        .ok_or_else(|| invalid("truncated SSH public key remainder"))?;
    Ok((value, rest))
}

fn validate_identifier(value: &str, label: &str) -> Result<(), AcceptanceError> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(invalid(format!("{label} has an invalid identifier")));
    }
    Ok(())
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "trust_tests.rs"]
mod tests;
