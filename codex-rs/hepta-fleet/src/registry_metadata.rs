//! Public registry metadata remains root protected and workload readable.

use std::fs::File;
use std::path::Path;

use crate::FleetRegistryError;

pub(crate) fn inherit_protected_read_group(
    file: &File,
    path: &Path,
) -> Result<(), FleetRegistryError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        // Later lifecycle and release generations must inherit the same
        // protected read group as the Starting metadata prepared before spawn.
        // The callers publish these attributes with their existing file fsync.
        let parent = path
            .parent()
            .ok_or_else(|| FleetRegistryError::Invalid("record has no parent".into()))?;
        let metadata = std::fs::symlink_metadata(parent)?;
        if metadata.is_dir()
            && metadata.uid() == 0
            && metadata.mode() & 0o050 == 0o050
            && metadata.mode() & 0o022 == 0
        {
            std::os::unix::fs::fchown(file, /*uid*/ None, Some(metadata.gid()))?;
            file.set_permissions(std::fs::Permissions::from_mode(0o640))?;
        }
    }
    #[cfg(not(unix))]
    let _ = (file, path);
    Ok(())
}
