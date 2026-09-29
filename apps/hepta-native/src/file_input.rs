//! Bounded, non-following reads for operator-selected local configuration.
//!
//! The final path component must be a regular file, not a link or reparse point.
//! This is not a sandbox for parent directories: the caller still owns selection
//! of an absolute path. Validation and reading use the same open file handle.
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

/// Read one bounded JSON value. Growth between stat and read cannot bypass the limit.
pub fn read_json_file<T: DeserializeOwned>(path: &Path, maximum: u64) -> Result<T, ShellError> {
    Ok(serde_json::from_slice(&read_bytes(path, maximum)?)?)
}

fn read_limit(maximum: u64) -> Result<u64, ShellError> {
    maximum
        .checked_add(1)
        .filter(|limit| usize::try_from(*limit).is_ok())
        .ok_or_else(|| {
            ShellError::InvalidInput("local input byte limit is not representable".into())
        })
}

/// Read at most the requested limit plus one overflow sentinel byte. A stat is
/// only an early rejection optimization, never the authority for the byte bound.
fn read_bounded(reader: impl std::io::Read, maximum: u64) -> Result<Vec<u8>, ShellError> {
    let limit = read_limit(maximum)?;
    let mut bytes = Vec::new();
    reader.take(limit).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(ShellError::InvalidInput(
            "local input exceeded its byte limit while reading".into(),
        ));
    }
    Ok(bytes)
}

pub fn read_bytes(path: &Path, maximum: u64) -> Result<Vec<u8>, ShellError> {
    // Reject an invalid bound before opening any OS resource.
    read_limit(maximum)?;
    let file = open_regular_file(path)?;
    if file.metadata()?.len() > maximum {
        return Err(ShellError::InvalidInput(
            "local input exceeds its byte limit".into(),
        ));
    }
    read_bounded(file, maximum)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::io::Write as _;

    #[test]
    fn exact_limit_and_empty_input_are_accepted() {
        assert_eq!(read_bounded(Cursor::new(b"abcd"), 4).unwrap(), b"abcd");
        assert!(read_bounded(Cursor::new(b""), 0).unwrap().is_empty());
    }

    #[test]
    fn oversized_reader_consumes_only_one_sentinel_byte() {
        let mut reader = Cursor::new(b"abcdefghij");
        assert!(read_bounded(&mut reader, 4).is_err());
        assert_eq!(reader.position(), 5);
    }

    #[test]
    fn zero_limit_rejects_nonempty_input() {
        let mut reader = Cursor::new(b"abc");
        assert!(read_bounded(&mut reader, 0).is_err());
        assert_eq!(reader.position(), 1);
    }

    #[test]
    fn unrepresentable_limit_fails_without_reading() {
        let mut reader = Cursor::new(b"abc");
        assert!(read_bounded(&mut reader, u64::MAX).is_err());
        assert_eq!(reader.position(), 0);
    }

    #[test]
    fn relative_path_and_directory_are_rejected() {
        assert!(read_bytes(Path::new("relative.json"), 100).is_err());
        let dir = tempfile::tempdir().unwrap();
        assert!(read_bytes(dir.path(), 100).is_err());
    }

    #[test]
    fn real_file_has_identical_exact_and_oversized_boundaries() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("input.json");
        std::fs::write(&path, b"null").unwrap();
        assert_eq!(read_bytes(&path, 4).unwrap(), b"null");
        assert!(read_bytes(&path, 3).is_err());
    }

    #[test]
    fn file_growth_after_metadata_is_still_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("growing.json");
        std::fs::write(&path, b"12").unwrap();
        let file = open_regular_file(&path).unwrap();
        assert_eq!(file.metadata().unwrap().len(), 2);
        let mut writer = OpenOptions::new().append(true).open(&path).unwrap();
        writer.write_all(b"3456789").unwrap();
        writer.flush().unwrap();
        assert!(read_bounded(file, 4).is_err());
    }

    #[test]
    fn malformed_and_trailing_json_are_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("input.json");
        for invalid in [b"{".as_slice(), b"null true".as_slice()] {
            std::fs::write(&path, invalid).unwrap();
            assert!(read_json_file::<serde_json::Value>(&path, 100).is_err());
        }
    }

    #[test]
    fn read_error_does_not_return_partial_success() {
        struct Broken;
        impl std::io::Read for Broken {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("injected read failure"))
            }
        }
        assert!(read_bounded(Broken, 16).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn final_symlink_and_socket_are_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("target.json");
        let link = dir.path().join("link.json");
        std::fs::write(&target, b"null").unwrap();
        std::os::unix::fs::symlink(&target, &link).unwrap();
        assert!(read_bytes(&link, 100).is_err());
        let socket = dir.path().join("socket");
        let _listener = std::os::unix::net::UnixListener::bind(&socket).unwrap();
        assert!(read_bytes(&socket, 100).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn path_replacement_does_not_change_the_validated_open_handle() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("input.json");
        std::fs::write(&path, b"old").unwrap();
        let opened = open_regular_file(&path).unwrap();
        let replacement = dir.path().join("replacement.json");
        std::fs::write(&replacement, b"new").unwrap();
        std::fs::rename(&replacement, &path).unwrap();
        assert_eq!(read_bounded(opened, 3).unwrap(), b"old");
        assert_eq!(read_bytes(&path, 3).unwrap(), b"new");
    }
}
