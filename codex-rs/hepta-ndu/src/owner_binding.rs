//! Persistent policy/principal binding under the already held projection writer lock.
//! Generation fencing remains with the live host; this is not an off-host rollback witness.
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use crate::NduOwnerContextV1;
use crate::NduOwnerError;
use crate::NduProjectionStoreError;
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
                let mut actual = [0_u8; 33];
                let mut file = File::open(path)?.take(33);
                file.read_exact(&mut actual[..32])?;
                if file.read(&mut actual[32..])? != 0 || &actual[..32] != binding.as_array() {
                    return Err(NduOwnerError::InvalidContext(
                        "durable owner or policy changed",
                    ));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && empty => {
                match fs::remove_file(&pending) {
                    Ok(()) => {}
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
                let mut file = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&pending)?;
                file.write_all(binding.as_array())?;
                file.sync_all()?;
                fs::rename(&pending, path)?;
                File::open(root)?.sync_all()?;
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
