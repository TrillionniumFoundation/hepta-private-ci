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
    ensure!(bytes.len() as u64 <= limit, "upgrade material exceeds its bound");
    Ok(bytes)
}
