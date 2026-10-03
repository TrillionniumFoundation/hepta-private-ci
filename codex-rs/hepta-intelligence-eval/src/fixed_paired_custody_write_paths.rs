use super::*;

/// Read-only launch material from the same full original purpose codec.
/// These paths grant no custody or role authority; the native owner retains
/// all process, key, controller, CAS, current-source and expiry admission.
pub fn fixed_paired_execution_write_paths_v1(bytes: &[u8]) -> HostResult<Vec<PathBuf>> {
    let config: Config = serde_json::from_slice(bytes)?;
    if config.schema
        != format!(
            "hepta.fixed-paired-custody-execution-config.v{}",
            config.withdrawal.version()
        )
    {
        return Err("fixed custody write purpose schema".into());
    }
    Ok(vec![
        config.work_directory,
        config.private_directory.join("holdout-cas.bin"),
    ])
}
