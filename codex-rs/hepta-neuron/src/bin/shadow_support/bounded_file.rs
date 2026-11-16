//! Bounded file reads for the standalone research executables.

use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn read_file(path: &Path, maximum: usize) -> Result<Vec<u8>, String> {
    if path.is_symlink() || path.parent().is_some_and(Path::is_symlink) {
        return Err("symlinked research artifact".to_owned());
    }
    let mut file = File::open(path).map_err(|error| error.to_string())?;
    let before = file.metadata().map_err(|error| error.to_string())?;
    if !before.is_file() || before.len() == 0 || before.len() > maximum as u64 {
        return Err("physical file size or type rejected".to_owned());
    }
    // Bind both metadata observations to the opened file. An input that grows
    // after the first observation still cannot make this read exceed its cap.
    let bytes = read_capped(&mut file, maximum)?;
    let after = file.metadata().map_err(|error| error.to_string())?;
    if bytes.len() as u64 != before.len()
        || after.len() != before.len()
        || after.modified().ok() != before.modified().ok()
    {
        return Err("source changed while reading".to_owned());
    }
    Ok(bytes)
}

fn read_capped(reader: impl Read, maximum: usize) -> Result<Vec<u8>, String> {
    let limit = u64::try_from(maximum)
        .ok()
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| "invalid research file byte limit".to_owned())?;
    let mut bytes = Vec::new();
    reader
        .take(limit)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() > maximum {
        return Err("research file exceeds byte limit".to_owned());
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "bounded_file_tests.rs"]
mod tests;
