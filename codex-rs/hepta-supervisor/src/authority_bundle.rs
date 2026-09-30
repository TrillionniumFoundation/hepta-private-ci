//! Digest-pinned public verifier bundle consumed by `hepta-supervisord`.
//!
//! The external release-policy owner distributes this file. It contains no
//! signing key and grants no authority by itself; the host must pin the exact
//! bundle SHA-256 before constructing the two independent verifiers.

use std::io::Read;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7ArtifactVerifier;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::H7H89ProductionGrantVerifier;

pub const PRODUCTION_AUTHORITY_BUNDLE_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_AUTHORITY_BUNDLE_NAMESPACE: &str =
    "hepta:runtime-supervisor:authority-bundle:v1";
const BUNDLE_DOMAIN: &[u8] = b"hepta-supervisor:authority-bundle:v1";
const MAX_BUNDLE_BYTES: u64 = 8_192;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionAuthorityBundle {
    pub schema_version: u32,
    pub namespace: String,
    pub grant_signer_id: String,
    pub grant_signer_epoch: u64,
    pub grant_public_key_hex: String,
    pub h7_signer_id: String,
    pub h7_signer_epoch: u64,
    pub h7_public_key_hex: String,
    pub bundle_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum ProductionAuthorityBundleError {
    #[error("production authority bundle is invalid: {0}")]
    Invalid(String),
    #[error("production authority bundle digest mismatch")]
    DigestMismatch,
    #[error("production authority bundle verifier is invalid: {0}")]
    Verifier(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl ProductionAuthorityBundle {
    pub fn new(
        grant_signer_id: impl Into<String>,
        grant_signer_epoch: u64,
        grant_key: VerifyingKey,
        h7_signer_id: impl Into<String>,
        h7_signer_epoch: u64,
        h7_key: VerifyingKey,
    ) -> Result<Self, ProductionAuthorityBundleError> {
        let mut bundle = Self {
            schema_version: PRODUCTION_AUTHORITY_BUNDLE_SCHEMA_VERSION,
            namespace: PRODUCTION_AUTHORITY_BUNDLE_NAMESPACE.to_string(),
            grant_signer_id: grant_signer_id.into(),
            grant_signer_epoch,
            grant_public_key_hex: hex_lower(&grant_key.to_bytes()),
            h7_signer_id: h7_signer_id.into(),
            h7_signer_epoch,
            h7_public_key_hex: hex_lower(&h7_key.to_bytes()),
            bundle_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        bundle.bundle_sha256 = bundle.compute_digest()?;
        bundle.validate()?;
        Ok(bundle)
    }

    pub fn validate(&self) -> Result<(), ProductionAuthorityBundleError> {
        if self.schema_version != PRODUCTION_AUTHORITY_BUNDLE_SCHEMA_VERSION
            || self.namespace != PRODUCTION_AUTHORITY_BUNDLE_NAMESPACE
            || self.grant_signer_epoch == 0
            || self.h7_signer_epoch == 0
        {
            return Err(ProductionAuthorityBundleError::Invalid(
                "schema, namespace, or signer epoch is invalid".to_string(),
            ));
        }
        validate_identifier(&self.grant_signer_id, "grant signer id")?;
        validate_identifier(&self.h7_signer_id, "H7 signer id")?;
        parse_public_key(&self.grant_public_key_hex)?;
        parse_public_key(&self.h7_public_key_hex)?;
        if self.bundle_sha256 != self.compute_digest()? {
            return Err(ProductionAuthorityBundleError::DigestMismatch);
        }
        Ok(())
    }

    pub fn verifier(
        &self,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityBundleError> {
        self.validate()?;
        let h7_verifier = H7ArtifactVerifier::from_bytes(
            self.h7_signer_id.clone(),
            self.h7_signer_epoch,
            parse_public_key(&self.h7_public_key_hex)?,
        )
        .map_err(|error| ProductionAuthorityBundleError::Verifier(error.to_string()))?;
        H7H89ProductionGrantVerifier::from_bytes_with_h7_verifier(
            self.grant_signer_id.clone(),
            self.grant_signer_epoch,
            parse_public_key(&self.grant_public_key_hex)?,
            h7_verifier,
        )
        .map_err(|error| ProductionAuthorityBundleError::Verifier(error.to_string()))
    }

    pub fn load_pinned(
        path: &Path,
        expected_sha256: &Sha256Digest,
    ) -> Result<(Self, H7H89ProductionGrantVerifier), ProductionAuthorityBundleError> {
        if !path.is_absolute() {
            return Err(ProductionAuthorityBundleError::Invalid(
                "bundle path must be absolute".to_string(),
            ));
        }
        let bytes = read_secure_file(path)?;
        let bundle: Self = serde_json::from_slice(&bytes)?;
        bundle.validate()?;
        if &bundle.bundle_sha256 != expected_sha256 {
            return Err(ProductionAuthorityBundleError::DigestMismatch);
        }
        let verifier = bundle.verifier()?;
        Ok((bundle, verifier))
    }

    pub fn to_json_bytes(&self) -> Result<Vec<u8>, ProductionAuthorityBundleError> {
        self.validate()?;
        Ok(serde_json::to_vec_pretty(self)?)
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ProductionAuthorityBundleError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.namespace,
            &self.grant_signer_id,
            self.grant_signer_epoch,
            &self.grant_public_key_hex,
            &self.h7_signer_id,
            self.h7_signer_epoch,
            &self.h7_public_key_hex,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [BUNDLE_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

fn read_secure_file(path: &Path) -> Result<Vec<u8>, ProductionAuthorityBundleError> {
    let before = std::fs::symlink_metadata(path)?;
    if !before.file_type().is_file()
        || before.file_type().is_symlink()
        || before.len() > MAX_BUNDLE_BYTES
    {
        return Err(ProductionAuthorityBundleError::Invalid(
            "bundle must be a bounded regular non-symlink file".to_string(),
        ));
    }
    #[cfg(unix)]
    validate_unix_metadata(&before)?;

    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    let opened = file.metadata()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != opened.dev() || before.ino() != opened.ino() {
            return Err(ProductionAuthorityBundleError::Invalid(
                "bundle identity changed while opening".to_string(),
            ));
        }
        validate_unix_metadata(&opened)?;
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_BUNDLE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BUNDLE_BYTES {
        return Err(ProductionAuthorityBundleError::Invalid(
            "bundle exceeds its size bound".to_string(),
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn validate_unix_metadata(
    metadata: &std::fs::Metadata,
) -> Result<(), ProductionAuthorityBundleError> {
    use std::os::unix::fs::MetadataExt;

    // SAFETY: geteuid has no pointer arguments or side effects beyond reading
    // the process credential.
    let euid = unsafe { libc::geteuid() };
    if metadata.uid() != euid || metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
        return Err(ProductionAuthorityBundleError::Invalid(
            "bundle owner, link count, or permissions are unsafe".to_string(),
        ));
    }
    Ok(())
}

fn validate_identifier(
    value: &str,
    label: &str,
) -> Result<(), ProductionAuthorityBundleError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(ProductionAuthorityBundleError::Invalid(format!(
            "{label} is malformed"
        )));
    }
    Ok(())
}

fn parse_public_key(value: &str) -> Result<[u8; 32], ProductionAuthorityBundleError> {
    if value.len() != 64 || !value.is_ascii() {
        return Err(ProductionAuthorityBundleError::Invalid(
            "public key must be 64 lowercase hex characters".to_string(),
        ));
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        output[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Ok(output)
}

fn hex_value(value: u8) -> Result<u8, ProductionAuthorityBundleError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(ProductionAuthorityBundleError::Invalid(
            "public key contains non-lowercase-hex data".to_string(),
        )),
    }
}

fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::SigningKey;

    use super::*;

    #[test]
    fn exact_digest_pins_rotated_public_keys() {
        let grant = SigningKey::from_bytes(&[3; 32]);
        let h7 = SigningKey::from_bytes(&[7; 32]);
        let bundle = ProductionAuthorityBundle::new(
            "release-policy",
            4,
            grant.verifying_key(),
            "h7-policy",
            9,
            h7.verifying_key(),
        )
        .expect("bundle");
        let dir = tempfile::tempdir().expect("temporary directory");
        let path = dir.path().join("authority.json");
        std::fs::write(&path, bundle.to_json_bytes().expect("json")).expect("write bundle");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
                .expect("owner-only bundle");
        }
        ProductionAuthorityBundle::load_pinned(&path, &bundle.bundle_sha256)
            .expect("load pinned bundle");
        assert!(matches!(
            ProductionAuthorityBundle::load_pinned(
                &path,
                &Sha256Digest::for_bytes(b"wrong bundle"),
            ),
            Err(ProductionAuthorityBundleError::DigestMismatch)
        ));
    }
}
