//! Closed import closures for the existing V7 and separately versioned V8 heads.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

#[path = "memory_cell_address_worker_profile_v9.rs"]
mod v9;

pub(super) struct SourceProfile {
    pub required: BTreeSet<PathBuf>,
    pub inventory_directories: Vec<PathBuf>,
    pub policy_files: BTreeMap<String, PathBuf>,
}

pub(super) fn source_profile(script: &Path, schema: Option<&str>) -> Result<SourceProfile, String> {
    let addressing = script.parent().ok_or("address worker parent is missing")?;
    let qualification = addressing
        .parent()
        .and_then(Path::parent)
        .ok_or("address worker import root is missing")?;
    let (mut required, inventory_directories, policy_files) = match schema {
        Some("hepta.memory.v7.intent-model.v1") => {
            let required = [
                "__init__.py",
                "contracts.py",
                "planner.py",
                "model.py",
                "capabilities.py",
            ]
            .into_iter()
            .map(|name| addressing.join(name))
            .collect::<BTreeSet<_>>();
            let policy = ["model.py", "capabilities.py", "contracts.py", "planner.py"]
                .into_iter()
                .map(|name| (name.to_string(), addressing.join(name)))
                .collect();
            (required, vec![addressing.to_path_buf()], policy)
        }
        Some("hepta.memory.v8.selective-intent-model.v1") => {
            if addressing != qualification.join("memory-cell-v8/addressing")
                || !["worker.py", "qualification_shadow_worker.py"]
                    .into_iter()
                    .any(|name| script == addressing.join(name))
            {
                return Err(
                    "V8 addressing requires its registered versioned entry point".to_string(),
                );
            }
            let package = addressing.join("v8_addressing");
            let frozen = qualification.join("memory-cell-v7/addressing");
            let mut paths = ["__init__.py", "model.py", "policy.py"]
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
            let policy = paths
                .iter()
                .map(|path| {
                    path.strip_prefix(qualification)
                        .map(|name| (name.to_string_lossy().replace('\\', "/"), path.clone()))
                        .map_err(|_| "V8 policy path escaped its qualification root".to_string())
                })
                .collect::<Result<BTreeMap<_, _>, _>>()?;
            (
                paths.into_iter().collect(),
                vec![addressing.to_path_buf(), package, frozen],
                policy,
            )
        }
        Some("hepta.memory.v9.compatibility-intent-model.v1") => return v9::source_profile(script),
        Some(_) | None => return Err("unregistered address model schema".to_string()),
    };
    required.insert(script.to_path_buf());
    required.insert(qualification.join("memory-cell-v6/v6/__init__.py"));
    required.insert(qualification.join("memory-cell-v6/v6/encoder.py"));
    Ok(SourceProfile {
        required,
        inventory_directories,
        policy_files,
    })
}

#[cfg(test)]
#[path = "memory_cell_address_worker_profile_v9_tests.rs"]
mod v9_tests;
