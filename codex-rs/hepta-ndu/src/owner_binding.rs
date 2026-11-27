//! Persistent policy/principal binding under the already held projection writer lock.
//! Generation fencing remains with the live host; this is not an off-host rollback witness.
use std::fs;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use crate::NduOwnerContextV1;
use crate::NduOwnerError;
use crate::NduProjectionStoreError;
use crate::projection_store::open_directory;
use crate::projection_store::open_regular;
use codex_hepta_types::Digest32;

pub(crate) fn bind_owner(
    root: &Path,
    context: &NduOwnerContextV1,
    policy: Digest32,
    empty: bool,
) -> Result<(), NduOwnerError> {
    let binding = Digest32::of_parts(&[
        b"hepta.ndu.durable-owner-binding.v1\0",
        &(context.principal_id.as_str().len() as u64).to_be_bytes(),
        context.principal_id.as_str().as_bytes(),
        &(context.owner_id.as_str().len() as u64).to_be_bytes(),
        context.owner_id.as_str().as_bytes(),
        context.principal_scope_digest.as_array(),
        policy.as_array(),
    ]);
    let path = root.join("owner-binding.v1");
    let pending = root.join("owner-binding.v1.tmp");
    (|| -> Result<(), NduOwnerError> {
        match fs::symlink_metadata(&path) {
            Ok(meta) => {
                if !meta.is_file() || meta.file_type().is_symlink() || meta.len() != 32 {
                    return Err(NduOwnerError::InvalidContext("durable owner binding file"));
                }
                let file = open_regular(&path, /*create*/ false, /*exclusive*/ false)?;
                let mut actual = [0_u8; 33];
                let mut bounded = (&file).take(33);
                bounded.read_exact(&mut actual[..32])?;
                if bounded.read(&mut actual[32..])? != 0 || &actual[..32] != binding.as_array() {
                    return Err(NduOwnerError::InvalidContext(
                        "durable owner or policy changed",
                    ));
                }
                // Recover a prior bootstrap's unacknowledged rename before
                // treating the owner binding as durable on this generation.
                file.sync_all()?;
                open_directory(root)?.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && empty => {
                match fs::remove_file(&pending) {
                    Ok(()) => {}
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
                let mut file =
                    open_regular(&pending, /*create*/ true, /*exclusive*/ true)?;
                file.write_all(binding.as_array())?;
                file.sync_all()?;
                fs::rename(&pending, path)?;
                open_directory(root)?.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Err(NduOwnerError::InvalidContext(
                    "unbound historical store requires migration",
                ));
            }
            Err(error) => return Err(error.into()),
        }
        Ok(())
    })()
}

impl From<std::io::Error> for NduOwnerError {
    fn from(error: std::io::Error) -> Self {
        Self::Store(NduProjectionStoreError::from(error))
    }
}
