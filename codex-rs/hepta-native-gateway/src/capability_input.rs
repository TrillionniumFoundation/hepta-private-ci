//! Optional installer-owned input for a gateway with its own system UID.
//! The desktop continues to use its OS keyring; no capability appears in argv.

use std::io::Read;
use std::path::Path;

use anyhow::Result;

pub(super) fn load(path: &Path) -> Result<String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if !path.is_absolute() || path.canonicalize()? != path {
            anyhow::bail!("capability input must be one canonical protected path");
        }
        for parent in path.parent().into_iter().flat_map(Path::ancestors) {
            let metadata = std::fs::symlink_metadata(parent)?;
            if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                anyhow::bail!("capability input ancestors must deny non-root writes");
            }
        }
        let file = std::fs::File::open(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.nlink() != 1
            || metadata.mode() & 0o027 != 0
            || metadata.len() > 256
        {
            anyhow::bail!("capability input must be a bounded root-owned private file");
        }
        let mut token = String::new();
        file.take(257).read_to_string(&mut token)?;
        crate::validate_bearer_token(&token)?;
        Ok(token)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        anyhow::bail!("protected installer capability input requires Unix ownership");
    }
}

#[cfg(all(test, unix))]
#[path = "capability_input_tests.rs"]
mod tests;
