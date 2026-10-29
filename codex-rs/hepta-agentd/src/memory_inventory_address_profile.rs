//! Closed first-party import profile for the separate inventory router.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use super::SourceProfile;

pub(super) fn source_profile(script: &Path) -> Result<SourceProfile, String> {
    let package = script.parent().ok_or("inventory worker package is missing")?;
    let qualification = package.parent().ok_or("inventory qualification root is missing")?;
    if package != qualification.join("memory-cell-v10") || script != package.join("inventory_worker.py") {
        return Err("inventory worker requires its registered versioned entry point".to_string());
    }
    let encoder = qualification.join("memory-cell-adapters");
    let mut paths = ["inventory_worker.py", "routing.py", "reference.py", "export_native.py"]
        .into_iter().map(|name| package.join(name)).collect::<Vec<_>>();
    paths.push(encoder.join("encoder.py"));
    let policy_files = paths.iter().map(|path| {
        path.strip_prefix(qualification)
            .map(|relative| (relative.to_string_lossy().replace('\\', "/"), path.clone()))
            .map_err(|_| "inventory policy escaped its root".to_string())
    }).collect::<Result<BTreeMap<_, _>, _>>()?;
    Ok(SourceProfile {
        required: paths.into_iter().collect::<BTreeSet<_>>(),
        inventory_directories: vec![package.to_path_buf(), encoder],
        policy_files,
    })
}
