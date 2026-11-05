#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use crate::FleetRegistryError;
use crate::FleetReleaseTrustConfig;
use crate::release_authority::invalid;

impl FleetReleaseTrustConfig {
    /// Loads an explicitly named out-of-band configuration. No root, expected
    /// checkpoint, or service identity is inferred from the Fleet journal.
    #[cfg(unix)]
    pub fn read(path: &Path) -> Result<Self, FleetRegistryError> {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;
        use std::os::unix::fs::PermissionsExt;

        const MAX_CONFIG_BYTES: u64 = 64 * 1024;
        if !path.is_absolute() {
            return Err(invalid("release trust configuration path must be absolute"));
        }
        for ancestor in path
            .parent()
            .ok_or_else(|| invalid("configuration has no parent"))?
            .ancestors()
        {
            let metadata = std::fs::symlink_metadata(ancestor)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(invalid(
                    "release trust configuration requires physical ancestors",
                ));
            }
        }
        let file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.permissions().mode() & 0o022 != 0
            || metadata.len() > MAX_CONFIG_BYTES
        {
            return Err(invalid(
                "release trust configuration must be bounded, regular and not writable by other users",
            ));
        }
        let mut bytes = Vec::new();
        file.take(MAX_CONFIG_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != metadata.len() {
            return Err(invalid("release trust configuration changed while reading"));
        }
        let config: Self = serde_json::from_slice(&bytes)
            .map_err(|_| invalid("invalid release trust configuration"))?;
        config.validate()?;
        Ok(config)
    }

    #[cfg(not(unix))]
    pub fn read(_path: &Path) -> Result<Self, FleetRegistryError> {
        Err(invalid("PQ release authority requires Unix trust services"))
    }
}
