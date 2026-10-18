//! Original descriptor file rules shared by ordinary candidate/effect material.
use std::io::Read;
use std::path::Path;

use anyhow::Result;
use anyhow::ensure;

use crate::cognitive_process_bootstrap::FileAccess;
use crate::cognitive_process_bootstrap::open_bounded_regular;

pub(super) fn read_material(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let file = open_bounded_regular(path, limit, FileAccess::Read)?;
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= limit,
        "upgrade material exceeds its bound"
    );
    Ok(bytes)
}

/// Export plain immutable evidence bytes. Existing different bytes are never
/// overwritten, and a replay acknowledges file and directory durability again.
pub(super) fn persist_material(path: &Path, bytes: &[u8], limit: u64) -> Result<()> {
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::io::ErrorKind;
    use std::io::Write;
    ensure!(
        !bytes.is_empty() && bytes.len() as u64 <= limit,
        "material export exceeds its bound"
    );
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("material export has no parent"))?;
    ensure!(
        path.is_absolute() && parent.canonicalize()? == parent,
        "material export parent must be canonical"
    );
    match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(mut file) => {
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            ensure!(
                read_material(path, limit)? == bytes,
                "material export already contains different bytes"
            );
            File::open(path)?.sync_all()?;
        }
        Err(error) => return Err(error.into()),
    }
    File::open(parent)?.sync_all()?;
    ensure!(
        read_material(path, limit)? == bytes,
        "material export readback changed"
    );
    Ok(())
}
