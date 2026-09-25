//! Bounded, non-following reads for operator-selected local configuration.
use crate::error::ShellError;
use serde::de::DeserializeOwned;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read as _;
use std::path::Path;

pub(crate) fn open_regular_file(path: &Path) -> Result<File, ShellError> {
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "local input path must be absolute".into(),
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        // NONBLOCK makes opening a FIFO non-blocking; metadata below rejects it.
        options.custom_flags(
            (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
        );
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt as _;
        options.custom_flags(0x0020_0000); // FILE_FLAG_OPEN_REPARSE_POINT
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(ShellError::InvalidInput(
            "local input must be a regular file".into(),
        ));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt as _;
        if metadata.file_attributes() & 0x400 != 0 {
            // FILE_ATTRIBUTE_REPARSE_POINT
            return Err(ShellError::InvalidInput(
                "local input cannot be a reparse point".into(),
            ));
        }
    }
    Ok(file)
}

/// Read one bounded JSON object. Growth between stat and read cannot bypass the limit.
pub fn read_json_file<T: DeserializeOwned>(path: &Path, maximum: u64) -> Result<T, ShellError> {
    Ok(serde_json::from_slice(&read_bytes(path, maximum)?)?)
}

pub fn read_bytes(path: &Path, maximum: u64) -> Result<Vec<u8>, ShellError> {
    let file = open_regular_file(path)?;
    if file.metadata()?.len() > maximum {
        return Err(ShellError::InvalidInput(
            "local JSON input exceeds its byte limit".into(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(maximum.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(ShellError::InvalidInput(
            "local JSON input exceeded its byte limit while reading".into(),
        ));
    }
    Ok(bytes)
}
