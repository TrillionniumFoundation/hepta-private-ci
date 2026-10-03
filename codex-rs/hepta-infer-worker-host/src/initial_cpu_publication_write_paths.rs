//! Read-only original Owner launch paths. No lease, writer, key or Gold is opened.
use super::*;
use std::os::unix::fs::MetadataExt;

pub(crate) fn original_publication_write_paths(
    configuration: &[u8],
) -> HostResult<Vec<std::path::PathBuf>> {
    let value: Value = serde_json::from_slice(configuration)?;
    if value["schema"] != "hepta.cpu-neuron.parameter-pre-registration-publication-config.v1" {
        return Err("fixed original artifact publication configuration".into());
    }
    let original_owner: Source = serde_json::from_value(value["original_owner"].clone())?;
    let deployment_bytes = original_owner.read(32 * 1024)?;
    let deployment: Deployment = serde_json::from_slice(&deployment_bytes)?;
    let profile_bytes = deployment.profile.read(64 * 1024)?;
    let profile: Profile = serde_json::from_slice(&profile_bytes)?;
    profile.validate(now_ms()?)?;
    let metadata = std::fs::symlink_metadata(&profile.original_owner_state)?;
    if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o077 != 0 {
        return Err("original Owner state must remain private Root custody".into());
    }
    let paths = vec![profile.owner_root.clone(), profile.original_owner_state];
    if original_owner.read(32 * 1024)? != deployment_bytes
        || deployment.profile.read(64 * 1024)? != profile_bytes
    {
        return Err("original Owner full launch material changed".into());
    }
    Ok(paths)
}
