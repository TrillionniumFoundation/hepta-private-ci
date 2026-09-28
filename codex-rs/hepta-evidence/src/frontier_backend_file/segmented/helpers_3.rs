fn read_locked_bytes(
    file: &mut File,
    maximum: u64,
) -> Result<Vec<u8>, EvidenceFrontierBackendError> {
    let before = file.metadata().map_err(unavailable)?;
    if before.len() > maximum {
        return Err(corrupt("frontier storage file exceeds its bounded size"));
    }
    file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
    let mut bytes = Vec::new();
    (&mut *file)
        .take(maximum.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    let after = file.metadata().map_err(unavailable)?;
    if bytes.len() as u64 != before.len()
        || before.len() != after.len()
        || before.modified().ok() != after.modified().ok()
    {
        return Err(EvidenceFrontierBackendError::Unavailable(
            "frontier storage file changed during locked read".to_string(),
        ));
    }
    Ok(bytes)
}

fn read_optional_private_file(
    path: &Path,
    parent: &Path,
    expected_uid: u32,
    maximum: u64,
) -> Result<Option<Vec<u8>>, EvidenceFrontierBackendError> {
    let Some(mut file) = open_existing_journal(path, parent, expected_uid)? else {
        return Ok(None);
    };
    file.lock_shared().map_err(unavailable)?;
    let bytes = read_locked_bytes(&mut file, maximum)?;
    if bytes.is_empty() {
        return Err(corrupt("frontier metadata file is empty"));
    }
    Ok(Some(bytes))
}

fn write_immutable_private_file(
    path: &Path,
    parent: &Path,
    expected_uid: u32,
    bytes: &[u8],
) -> Result<(), EvidenceFrontierBackendError> {
    if bytes.is_empty() || bytes.len() as u64 > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES {
        return Err(invalid(
            "immutable frontier file is empty or exceeds its bound",
        ));
    }
    validate_direct_path(path, parent)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(path)
        {
            Ok(mut file) => {
                file.write_all(bytes).map_err(unavailable)?;
                file.sync_all().map_err(unavailable)?;
                validate_journal_metadata(&file, expected_uid)?;
                Ok(())
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                let existing = read_private_regular_file(
                    path,
                    parent,
                    expected_uid,
                    EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES,
                )?;
                if existing != bytes {
                    return Err(corrupt(
                        "immutable frontier segment path was reused with different bytes",
                    ));
                }
                Ok(())
            }
            Err(error) => Err(unavailable(error)),
        }
    }
    #[cfg(not(unix))]
    {
        let _ = (path, parent, expected_uid, bytes);
        Err(EvidenceFrontierBackendError::Unsupported)
    }
}

fn validate_direct_file_name(value: &str) -> Result<(), EvidenceFrontierBackendError> {
    let path = Path::new(value);
    if value.is_empty()
        || value.len() > 255
        || value == "."
        || value == ".."
        || path.components().count() != 1
        || path.file_name() != Some(path.as_os_str())
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(invalid(
            "frontier storage filename is not one bounded token",
        ));
    }
    Ok(())
}

fn validate_direct_path(path: &Path, parent: &Path) -> Result<(), EvidenceFrontierBackendError> {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid("frontier storage path has no UTF-8 filename"))?;
    validate_direct_file_name(name)?;
    if path.parent() != Some(parent) {
        return Err(invalid("frontier storage path is not a direct child"));
    }
    Ok(())
}

fn backend_error_to_io(error: EvidenceFrontierBackendError) -> io::Error {
    io::Error::other(error.to_string())
}

fn invalid(message: &str) -> EvidenceFrontierBackendError {
    EvidenceFrontierBackendError::Invalid(message.to_string())
}

fn corrupt(message: &str) -> EvidenceFrontierBackendError {
    EvidenceFrontierBackendError::Corrupt(message.to_string())
}
