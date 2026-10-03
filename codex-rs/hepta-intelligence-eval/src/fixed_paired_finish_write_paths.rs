use super::*;

/// Read-only launch paths decoded by the original complete finish codec.
/// Gold/witness inputs remain read-only; only the original CAS and independent
/// FULL sink/ACK output parents need writes inside the strict mount namespace.
pub fn fixed_paired_finish_write_paths_v1(bytes: &[u8]) -> HostResult<Vec<PathBuf>> {
    let config: Config = serde_json::from_slice(bytes)?;
    if config.schema != "hepta.fixed-paired-custody-finish-config.v1" {
        return Err("fixed custody finish write purpose schema".into());
    }
    let evidence = config
        .evidence_path
        .parent()
        .ok_or("original evidence parent")?
        .to_owned();
    let ack = config
        .ack_path
        .parent()
        .ok_or("original ACK parent")?
        .to_owned();
    if evidence == ack {
        return Err("original independent FULL sink/ACK parents".into());
    }
    Ok(vec![
        config.private_directory.join("holdout-cas.bin"),
        evidence,
        ack,
    ])
}
