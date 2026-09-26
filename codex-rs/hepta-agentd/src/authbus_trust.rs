//! One explicitly installed owner key and bounded thread allowlist.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::MessageIssuerRegistrySnapshot;
use codex_hepta_authbus::VerifiedIssuerHandle;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Clone, Debug)]
pub(crate) struct TextTrust {
    snapshot: MessageIssuerRegistrySnapshot,
}

impl TextTrust {
    /// Reload the owner-controlled file for every admission and dispatch stage.
    /// AuthBus validates the persistent registry and returns only a sealed
    /// issuer handle; this crate cannot construct trusted key state directly.
    pub fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let snapshot = MessageIssuerRegistrySnapshot::load(
            path,
            identity.home_root.as_path(),
            identity.agent_id.as_str(),
        )
        .map_err(|error| invalid(&error.to_string()))?;
        Ok(Self { snapshot })
    }

    pub fn issuer(&self) -> Result<VerifiedIssuerHandle, AgentdError> {
        Ok(self.snapshot.issuer().clone())
    }

    pub fn permits(&self, thread_id: &str) -> bool {
        self.snapshot.permits_route(thread_id)
    }
}

pub(crate) fn hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(invalid("invalid fixed-width hexadecimal value"));
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| invalid("invalid hexadecimal value"))?;
    }
    Ok(bytes)
}

// Shared private-file reader for non-issuer owner configuration. Issuer trust
// files must instead use the sealed AuthBus registry loaders above.
#[cfg(unix)]
pub(crate) fn read_private_owner_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "owner file must be a direct child of the canonical Agent home",
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
        || before.len() > maximum_bytes
        || path.canonicalize()? != path
    {
        return Err(invalid(
            "owner file must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let metadata_identity = |metadata: &std::fs::Metadata| {
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
    if metadata_identity(&opened) != metadata_identity(&before) {
        return Err(invalid("owner file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || metadata_identity(&after) != metadata_identity(&before)
        || metadata_identity(&file.metadata()?) != metadata_identity(&before)
    {
        return Err(invalid("owner file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
pub(crate) fn read_private_owner_file(
    _path: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "private owner configuration currently requires Unix ownership checks",
    ))
}

pub(crate) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("AuthBus: {message}"))
}
