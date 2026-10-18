//! UI path text denotes the exact filename entered or selected. Whitespace is
//! part of a native filename and must not be removed before reopening it.

use std::path::PathBuf;

use crate::error::ShellError;
use crate::model::MAX_NATIVE_PATH_BYTES;

pub(super) fn absolute_path(text: &str) -> Result<PathBuf, ShellError> {
    if text.len() > MAX_NATIVE_PATH_BYTES || text.contains('\0') {
        return Err(ShellError::InvalidInput(
            "native input path exceeds its byte bound or contains NUL".into(),
        ));
    }
    let path = PathBuf::from(text);
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "native input path must be absolute".into(),
        ));
    }
    Ok(path)
}

#[cfg(test)]
#[path = "path_input_tests.rs"]
mod tests;
