pub fn native_output_from_verified_settlement(
    verified: &VerifiedSettlementReceiptV1,
    persisted: &PersistedSettlementEvidence,
    owner_authority: NativeOwnerAuthority,
) -> Result<NativeRunOutput, ReconciliationEvidenceError> {
    if verified.receipt_sha256() != persisted.receipt_sha256 {
        return Err(ReconciliationEvidenceError::ReceiptMismatch);
    }
    let receipt = verified.receipt();
    let (status, boundary_status, terminal_observed, stop_reason) = match receipt.terminal {
        SettlementTerminalV1::Succeeded => (
            NativeRunStatus::Completed,
            NativeBoundaryStatus::Succeeded,
            true,
            None,
        ),
        SettlementTerminalV1::Failed => (
            NativeRunStatus::Failed,
            NativeBoundaryStatus::Failed,
            true,
            Some("verified provider failure".to_string()),
        ),
        SettlementTerminalV1::Interrupted => (
            NativeRunStatus::Interrupted,
            NativeBoundaryStatus::Interrupted,
            true,
            Some("verified provider interruption".to_string()),
        ),
        SettlementTerminalV1::Cancelled => (
            NativeRunStatus::Interrupted,
            NativeBoundaryStatus::Cancelled,
            true,
            Some("verified provider cancellation".to_string()),
        ),
        SettlementTerminalV1::TimedOut => (
            NativeRunStatus::Failed,
            NativeBoundaryStatus::TimedOut,
            true,
            Some("verified provider timeout".to_string()),
        ),
        SettlementTerminalV1::Indeterminate => (
            NativeRunStatus::Indeterminate,
            NativeBoundaryStatus::Indeterminate,
            false,
            Some("signed observation remains indeterminate".to_string()),
        ),
    };
    Ok(NativeRunOutput {
        thread_id: receipt.thread_id.clone(),
        turn_id: receipt.turn_id.clone(),
        model: receipt.model_id.clone(),
        model_provider: receipt.provider_id.clone(),
        status,
        boundary_status,
        output: String::new(),
        observed_output_tokens: receipt.observed_output_tokens,
        terminal_observed,
        stop_reason,
        owner_authority,
        codex_terminal_correlation_digest: Some(hex_digest(verified.receipt_sha256())),
    })
}

fn persist_exact(
    directory: &Path,
    path: &Path,
    bytes: &[u8],
) -> Result<(), ReconciliationEvidenceError> {
    if bytes.len() as u64 > MAX_EVIDENCE_BYTES {
        return Err(ReconciliationEvidenceError::EvidenceTooLarge);
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(path) {
        Ok(mut file) => {
            let result = (|| {
                file.write_all(bytes)?;
                file.sync_all()?;
                sync_directory(directory)?;
                Ok(())
            })();
            if result.is_err() {
                let _ = fs::remove_file(path);
            }
            result
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let mut existing = Vec::new();
            File::open(path)?
                .take(MAX_EVIDENCE_BYTES + 1)
                .read_to_end(&mut existing)?;
            if existing == bytes {
                Ok(())
            } else {
                Err(ReconciliationEvidenceError::EvidenceConflict)
            }
        }
        Err(error) => Err(error.into()),
    }
}

fn ensure_private_directory(path: &Path) -> Result<(), ReconciliationEvidenceError> {
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

fn sync_directory(path: &Path) -> Result<(), ReconciliationEvidenceError> {
    #[cfg(unix)]
    File::open(path)?.sync_all()?;
    Ok(())
}

fn hex_digest(digest: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(64);
    for byte in digest {
        value.push(HEX[(byte >> 4) as usize] as char);
        value.push(HEX[(byte & 0x0f) as usize] as char);
    }
    value
}
