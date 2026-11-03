//! V9's finite first-party import closure, including its frozen host contracts.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use super::SourceProfile;

pub(super) fn source_profile(script: &Path) -> Result<SourceProfile, String> {
    let addressing = script
        .parent()
        .ok_or("V9 address worker parent is missing")?;
    let qualification = addressing
        .parent()
        .and_then(Path::parent)
        .ok_or("V9 address worker import root is missing")?;
    if addressing != qualification.join("memory-cell-v9/addressing")
        || !["worker.py", "qualification_shadow_worker.py"]
            .into_iter()
            .any(|name| script == addressing.join(name))
    {
        return Err("V9 addressing requires its registered versioned entry point".to_string());
    }
    let package = addressing.join("v9_addressing");
    let frozen = qualification.join("memory-cell-v7/addressing");
    let mut paths = [
        "__init__.py",
        "identity.py",
        "model.py",
        "artifact.py",
        "policy.py",
        "capabilities.py",
    ]
    .into_iter()
    .map(|name| package.join(name))
    .collect::<Vec<_>>();
    paths.extend(
        [
            "worker.py",
            "qualification_shadow_worker.py",
            "bootstrap.py",
        ]
        .into_iter()
        .map(|name| addressing.join(name)),
    );
    paths.extend(
        [
            "__init__.py",
            "contracts.py",
            "capabilities.py",
            "model.py",
            "planner.py",
            "worker.py",
        ]
        .into_iter()
        .map(|name| frozen.join(name)),
    );
    paths.extend(
        ["__init__.py", "encoder.py"]
            .into_iter()
            .map(|name| qualification.join("memory-cell-v6/v6").join(name)),
    );
    let policy_files = paths
        .iter()
        .map(|path| {
            path.strip_prefix(qualification)
                .map(|name| (name.to_string_lossy().replace('\\', "/"), path.clone()))
                .map_err(|_| "V9 policy path escaped its qualification root".to_string())
        })
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    Ok(SourceProfile {
        required: paths.into_iter().collect::<BTreeSet<_>>(),
        inventory_directories: vec![addressing.to_path_buf(), package, frozen],
        policy_files,
    })
}
