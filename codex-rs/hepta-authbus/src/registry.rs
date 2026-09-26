//! Persistent owner-controlled issuer registries used by product callers.
//!
//! These loaders are the only public path from a file-backed trust registry to
//! a [`VerifiedIssuerHandle`]. They validate ownership, permissions, identity,
//! bounds and schema before sealing any key material.

use std::collections::BTreeSet;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AuthBusAuthorityError;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::VerifiedIssuerHandle;

const MAX_MESSAGE_REGISTRY_BYTES: u64 = 16 * 1024;
const MAX_ROLE_REGISTRY_BYTES: u64 = 32 * 1024;
const MAX_ROUTES: usize = 16;
const MAX_ROLE_ISSUERS: usize = 32;
const MAX_ROLES_PER_ISSUER: usize = 16;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MessageRegistryDocument {
    schema_version: u32,
    agent_id: String,
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    thread_ids: Vec<String>,
}

/// Exact snapshot of one owner-controlled message issuer registry.
#[derive(Clone, Debug)]
pub struct MessageIssuerRegistrySnapshot {
    owner_id: String,
    issuer: VerifiedIssuerHandle,
    route_ids: Vec<String>,
    document_digest: Digest32,
}

impl MessageIssuerRegistrySnapshot {
    pub fn load(
        path: &Path,
        expected_parent: &Path,
        expected_owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner_id(expected_owner_id)?;
        let bytes = read_private_registry_file(path, expected_parent, MAX_MESSAGE_REGISTRY_BYTES)?;
        let document: MessageRegistryDocument = serde_json::from_slice(&bytes)
            .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
        if document.schema_version != 1
            || document.agent_id != expected_owner_id
            || document.thread_ids.is_empty()
            || document.thread_ids.len() > MAX_ROUTES
        {
            return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
        }
        let mut routes = BTreeSet::new();
        for route in &document.thread_ids {
            if route.is_empty()
                || route.len() > 128
                || !routes.insert(route.clone())
                || route.bytes().any(|byte| byte.is_ascii_control())
            {
                return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
            }
        }
        let document_digest = Digest32::of_bytes(&bytes);
        let issuer = verified_entry(
            &document.issuer_id,
            document.key_epoch,
            &document.public_key_hex,
            document.revoked,
            document.schema_version,
            document_digest,
        )?;
        Ok(Self {
            owner_id: document.agent_id,
            issuer,
            route_ids: document.thread_ids,
            document_digest,
        })
    }

    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }

    pub fn issuer(&self) -> &VerifiedIssuerHandle {
        &self.issuer
    }

    pub fn route_ids(&self) -> &[String] {
        &self.route_ids
    }

    pub fn permits_route(&self, route_id: &str) -> bool {
        self.issuer.is_active() && self.route_ids.iter().any(|route| route == route_id)
    }

    pub fn document_digest(&self) -> Digest32 {
        self.document_digest
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RoleIssuerDocument {
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    roles: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RoleRegistryDocument {
    schema_version: u32,
    agent_id: String,
    issuers: Vec<RoleIssuerDocument>,
}

#[derive(Clone, Debug)]
struct RoleIssuerEntry {
    issuer: VerifiedIssuerHandle,
    roles: Vec<String>,
}

/// Bounded file-backed registry for message issuers assigned one or more named
/// roles. Role names remain opaque to AuthBus; the consuming product interprets
/// them after the registry loader has sealed issuer identity and key state.
#[derive(Clone, Debug)]
pub struct RoleIssuerRegistrySnapshot {
    owner_id: String,
    entries: Vec<RoleIssuerEntry>,
    document_digest: Digest32,
}

impl RoleIssuerRegistrySnapshot {
    pub fn load(
        path: &Path,
        expected_parent: &Path,
        expected_owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner_id(expected_owner_id)?;
        let bytes = read_private_registry_file(path, expected_parent, MAX_ROLE_REGISTRY_BYTES)?;
        let document: RoleRegistryDocument = serde_json::from_slice(&bytes)
            .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
        if document.schema_version != 1
            || document.agent_id != expected_owner_id
            || document.issuers.is_empty()
            || document.issuers.len() > MAX_ROLE_ISSUERS
        {
            return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
        }
        let document_digest = Digest32::of_bytes(&bytes);
        let mut identities = BTreeSet::new();
        let mut entries = Vec::with_capacity(document.issuers.len());
        for configured in document.issuers {
            if !identities.insert((configured.issuer_id.clone(), configured.key_epoch))
                || configured.roles.is_empty()
                || configured.roles.len() > MAX_ROLES_PER_ISSUER
            {
                return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
            }
            let mut roles = BTreeSet::new();
            for role in &configured.roles {
                if !valid_role(role) || !roles.insert(role.clone()) {
                    return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
                }
            }
            let issuer = verified_entry(
                &configured.issuer_id,
                configured.key_epoch,
                &configured.public_key_hex,
                configured.revoked,
                document.schema_version,
                document_digest,
            )?;
            entries.push(RoleIssuerEntry {
                issuer,
                roles: configured.roles,
            });
        }
        Ok(Self {
            owner_id: document.agent_id,
            entries,
            document_digest,
        })
    }

    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }

    pub fn document_digest(&self) -> Digest32 {
        self.document_digest
    }

    pub fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: &str,
    ) -> Result<VerifiedIssuerHandle, AuthBusAuthorityError> {
        if !valid_role(role) {
            return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
        }
        self.entries
            .iter()
            .find(|entry| {
                entry.issuer.issuer_id().as_str() == issuer_id
                    && entry.issuer.key_epoch().get() == key_epoch
                    && entry.roles.iter().any(|configured| configured == role)
            })
            .map(|entry| entry.issuer.clone())
            .ok_or(AuthBusAuthorityError::IssuerMissing)
    }

    pub fn active_bindings(
        &self,
    ) -> impl Iterator<Item = (&VerifiedIssuerHandle, &str)> {
        self.entries
            .iter()
            .filter(|entry| entry.issuer.is_active())
            .flat_map(|entry| {
                entry
                    .roles
                    .iter()
                    .map(move |role| (&entry.issuer, role.as_str()))
            })
    }
}

fn verified_entry(
    issuer_id: &str,
    key_epoch: u64,
    public_key_hex: &str,
    revoked: bool,
    registry_revision: u32,
    registry_digest: Digest32,
) -> Result<VerifiedIssuerHandle, AuthBusAuthorityError> {
    let issuer_id = StableId::new(issuer_id)
        .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
    let key_epoch = Generation::new(key_epoch)
        .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
    let verifying_key = VerifyingKey::from_bytes(&decode_hex_32(public_key_hex)?)
        .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
    VerifiedIssuerHandle::from_registry_entry(
        issuer_id,
        IssuerPurpose::Message,
        key_epoch,
        verifying_key,
        if revoked {
            IssuerLifecycleState::Revoked
        } else {
            IssuerLifecycleState::Active
        },
        u64::from(registry_revision),
        registry_digest,
    )
}

fn validate_owner_id(value: &str) -> Result<(), AuthBusAuthorityError> {
    if value.is_empty()
        || value.len() > 256
        || value.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    Ok(())
}

fn valid_role(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}

fn decode_hex_32(value: &str) -> Result<[u8; 32], AuthBusAuthorityError> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    let mut bytes = [0; 32];
    for (index, output) in bytes.iter_mut().enumerate() {
        *output = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| AuthBusAuthorityError::InvalidIssuerRegistry)?;
    }
    Ok(bytes)
}

#[cfg(unix)]
fn read_private_registry_file(
    path: &Path,
    expected_parent: &Path,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute()
        || !expected_parent.is_absolute()
        || path.parent() != Some(expected_parent)
        || expected_parent
            .canonicalize()
            .map_err(storage)?
            != expected_parent
    {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    let parent = std::fs::metadata(expected_parent).map_err(storage)?;
    let before = std::fs::symlink_metadata(path).map_err(storage)?;
    if !parent.is_dir()
        || parent.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != parent.uid()
        || before.mode() & 0o077 != 0
        || before.len() > maximum_bytes
        || path.canonicalize().map_err(storage)? != path
    {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(storage)?;
    let opened = file.metadata().map_err(storage)?;
    if metadata_identity(&opened) != metadata_identity(&before) {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(storage)?;
    let after = std::fs::symlink_metadata(path).map_err(storage)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || metadata_identity(&after) != metadata_identity(&before)
        || metadata_identity(&file.metadata().map_err(storage)?) != metadata_identity(&before)
    {
        return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
    }
    Ok(bytes)
}

#[cfg(unix)]
fn metadata_identity(metadata: &std::fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
    use std::os::unix::fs::MetadataExt;

    (
        metadata.dev(),
        metadata.ino(),
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}

#[cfg(not(unix))]
fn read_private_registry_file(
    _path: &Path,
    _expected_parent: &Path,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::InvalidIssuerRegistry)
}

fn storage(error: std::io::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}
