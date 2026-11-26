fn write_atomic_file(
    directory: &Path,
    final_name: &str,
    bytes: &[u8],
    temporary_label: &str,
    failpoints: &mut dyn JournalFailpointController,
    after_fsync: Option<JournalFailpoint>,
    after_rename: Option<JournalFailpoint>,
) -> Result<(), JournalGenerationError> {
    if !safe_file_name(final_name) {
        return Err(JournalGenerationError::InvalidConfiguration);
    }
    let temp_name = format!(
        ".{}.{}.{}.tmp",
        final_name,
        temporary_label,
        std::process::id()
    );
    let temp_path = directory.join(&temp_name);
    let final_path = directory.join(final_name);
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = match options.open(&temp_path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            fs::remove_file(&temp_path)?;
            options.open(&temp_path)?
        }
        Err(error) => return Err(error.into()),
    };
    let result = (|| {
        file.write_all(bytes)?;
        file.sync_all()?;
        if let Some(point) = after_fsync {
            failpoints.hit(point)?;
        }
        fs::rename(&temp_path, &final_path)?;
        if let Some(point) = after_rename {
            failpoints.hit(point)?;
        }
        sync_directory(directory)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    result
}

fn verify_file(
    path: &Path,
    expected_bytes: u64,
    expected_sha256: JournalDigest32,
    maximum_bytes: u64,
    corrupt_error: JournalGenerationError,
) -> Result<(), JournalGenerationError> {
    let bytes = read_bounded(path, maximum_bytes)?;
    if bytes.len() as u64 != expected_bytes || digest_bytes(&bytes) != expected_sha256 {
        return Err(corrupt_error);
    }
    Ok(())
}

fn read_bounded(path: &Path, maximum_bytes: u64) -> Result<Vec<u8>, JournalGenerationError> {
    let file = File::open(path).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            JournalGenerationError::NotFound
        } else {
            error.into()
        }
    })?;
    if file.metadata()?.len() > maximum_bytes {
        return Err(JournalGenerationError::CapacityExceeded);
    }
    let mut bytes = Vec::new();
    file.take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum_bytes {
        return Err(JournalGenerationError::CapacityExceeded);
    }
    Ok(bytes)
}

fn ensure_private_directory(path: &Path) -> Result<(), JournalGenerationError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(path)?.permissions();
        if permissions.mode() & 0o077 != 0 {
            permissions.set_mode(0o700);
            fs::set_permissions(path, permissions)?;
        }
    }
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), JournalGenerationError> {
    #[cfg(unix)]
    File::open(path)?.sync_all()?;
    Ok(())
}

fn safe_file_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 512
        && !value.contains('/')
        && !value.contains('\\')
        && value != "."
        && value != ".."
        && !value.as_bytes().contains(&0)
}

fn digest_bytes(bytes: &[u8]) -> JournalDigest32 {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().into()
}

fn digest_serialized<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<JournalDigest32, JournalGenerationError> {
    let payload = serde_json::to_vec(value).map_err(|_| JournalGenerationError::Encoding)?;
    let mut hasher = Sha256::new();
    hasher.update((domain.len() as u64).to_be_bytes());
    hasher.update(domain);
    hasher.update((payload.len() as u64).to_be_bytes());
    hasher.update(payload);
    Ok(hasher.finalize().into())
}

fn hex_digest(digest: JournalDigest32) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(64);
    for byte in digest {
        value.push(HEX[(byte >> 4) as usize] as char);
        value.push(HEX[(byte & 0x0f) as usize] as char);
    }
    value
}
