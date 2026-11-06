//! Independent host checks before invoking the declared Python interpreter.
//! The pinned helper checks installed bytes before third-party imports. These
//! observations do not hold an immutable executable namespace across check/use.

use std::collections::BTreeSet;
use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_agentd::NeuralCognitiveExecutionV1;
use codex_hepta_types::Digest32;
use sha2::Digest;
use sha2::Sha256;

pub(super) const MAX_SNAPSHOT_BYTES: usize = 16 * 1024 * 1024;

pub(super) fn snapshot_digest(raw: &[u8]) -> Result<Digest32, String> {
    if raw.is_empty() || raw.len() > MAX_SNAPSHOT_BYTES {
        return Err("neural runtime snapshot byte bound".to_owned());
    }
    Ok(Digest32::of_bytes(raw))
}

pub(super) fn verify_snapshot(
    python: &Path,
    raw: &[u8],
    execution: &NeuralCognitiveExecutionV1,
) -> Result<(), String> {
    verify_interpreter(python, raw, execution)?;
    let value: serde_json::Value = serde_json::from_slice(raw).map_err(|e| e.to_string())?;
    let files = value["files"]
        .as_object()
        .ok_or("neural runtime file map")?;
    let declared = value["managed_inventory"]
        .as_array()
        .ok_or("neural runtime inventory")?;
    if files.is_empty() || files.len() > 100_000 || declared.is_empty() || declared.len() > 100_000
    {
        return Err("neural runtime inventory bound".to_owned());
    }
    let expected = declared
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_owned)
                .ok_or_else(|| "neural runtime inventory path".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let mut observed = BTreeSet::new();
    let mut entries = 0_usize;
    // CPython can select an adjacent ._pth file before importing any stdlib.
    // This unpacked profile admits no such alternate startup search policy.
    let executable = Path::new(
        value["python"]["executable"]
            .as_str()
            .ok_or("neural interpreter")?,
    );
    let mut bootstrap_directories = BTreeSet::from([
        executable
            .parent()
            .ok_or("neural interpreter directory")?
            .to_path_buf(),
        python
            .parent()
            .ok_or("neural launch directory")?
            .to_path_buf(),
    ]);
    for path in files.keys().map(Path::new) {
        if path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.starts_with("libpython"))
        {
            bootstrap_directories.insert(
                path.parent()
                    .ok_or("neural library directory")?
                    .to_path_buf(),
            );
        }
    }
    for directory in bootstrap_directories {
        for entry in fs::read_dir(directory).map_err(|e| e.to_string())? {
            execution.check()?;
            entries += 1;
            if entries > 200_000 {
                return Err("neural runtime directory bound".to_owned());
            }
            if entry
                .map_err(|e| e.to_string())?
                .file_name()
                .to_string_lossy()
                .ends_with("._pth")
            {
                return Err("neural runtime unpacked profile forbids startup ._pth".to_owned());
            }
        }
    }
    for name in ["prefix", "stdlib_root"] {
        let root = Path::new(value[name].as_str().ok_or("neural runtime root")?);
        if !root.is_absolute()
            || root == Path::new("/")
            || !root.is_dir()
            || root.canonicalize().map_err(|e| e.to_string())? != root
        {
            return Err("neural runtime root identity".to_owned());
        }
        if name == "stdlib_root" {
            let version = root
                .file_name()
                .and_then(|name| name.to_str())
                .and_then(|name| name.strip_prefix("python"))
                .ok_or("neural runtime unpacked CPython stdlib required")?;
            let parts = version.split('.').collect::<Vec<_>>();
            if parts.len() != 2
                || parts
                    .iter()
                    .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
            {
                return Err("neural runtime stdlib version".to_owned());
            }
            let prefix = Path::new(value["prefix"].as_str().ok_or("neural runtime prefix")?);
            let cfg = prefix.join("pyvenv.cfg");
            let file = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                .open(&cfg)
                .map_err(|e| e.to_string())?;
            let metadata = file.metadata().map_err(|e| e.to_string())?;
            if !metadata.is_file() || metadata.len() > 65_536 {
                return Err("neural runtime private venv configuration bound".to_owned());
            }
            let mut cfg_bytes = Vec::new();
            file.take(65_537)
                .read_to_end(&mut cfg_bytes)
                .map_err(|e| e.to_string())?;
            if cfg_bytes.len() > 65_536
                || value["files"][cfg.to_str().ok_or("neural venv path")?].as_str()
                    != Some(Digest32::of_bytes(&cfg_bytes).to_string().as_str())
            {
                return Err("neural runtime private venv configuration changed".to_owned());
            }
            let cfg_text = std::str::from_utf8(&cfg_bytes).map_err(|e| e.to_string())?;
            let homes = cfg_text
                .lines()
                .filter_map(|line| line.split_once('='))
                .filter(|(key, _)| key.trim() == "home")
                .map(|(_, value)| Path::new(value.trim()))
                .collect::<Vec<_>>();
            if homes.len() != 1 || !homes[0].is_absolute() {
                return Err("neural runtime private venv home".to_owned());
            }
            let bases = BTreeSet::from([
                executable
                    .parent()
                    .and_then(Path::parent)
                    .ok_or("neural interpreter prefix")?,
                homes[0].parent().ok_or("neural venv base prefix")?,
            ]);
            let mut zip_parents =
                BTreeSet::from([root.parent().ok_or("neural stdlib parent")?.to_path_buf()]);
            for base in bases {
                for lib in ["lib", "lib64"] {
                    let lib = base.join(lib);
                    zip_parents.insert(lib.clone());
                    let alias = lib.join(format!("python{version}"));
                    match alias.symlink_metadata() {
                        Ok(_) if alias.canonicalize().map_err(|e| e.to_string())? == root => {}
                        Ok(_) => {
                            return Err("neural runtime bootstrap stdlib alias changed".to_owned());
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                        Err(error) => return Err(error.to_string()),
                    }
                }
            }
            for lib in ["lib", "lib64"] {
                zip_parents.insert(prefix.join(lib));
            }
            for parent in zip_parents {
                let zip = parent.join(format!("python{}{}.zip", parts[0], parts[1]));
                match zip.symlink_metadata() {
                    Ok(_) => {
                        return Err(
                            "neural runtime unpacked profile forbids startup ZIP".to_owned()
                        );
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.to_string()),
                }
            }
        }
        let mut pending = vec![root.to_path_buf()];
        while let Some(directory) = pending.pop() {
            execution.check()?;
            for entry in fs::read_dir(directory).map_err(|e| e.to_string())? {
                execution.check()?;
                entries += 1;
                if entries > 200_000 {
                    return Err("neural runtime directory bound".to_owned());
                }
                let path = entry.map_err(|e| e.to_string())?.path();
                if name == "stdlib_root"
                    && path
                        .strip_prefix(root)
                        .map_err(|e| e.to_string())?
                        .components()
                        .any(|part| part.as_os_str() == "site-packages")
                {
                    continue;
                }
                let metadata = path.symlink_metadata().map_err(|e| e.to_string())?;
                if metadata.is_dir() {
                    pending.push(path);
                } else if path.is_file() {
                    observed.insert(path.to_str().ok_or("neural runtime UTF-8 path")?.to_owned());
                }
            }
        }
    }
    if observed.into_iter().collect::<Vec<_>>() != expected
        || expected.iter().any(|path| !files.contains_key(path))
    {
        return Err("neural runtime installed inventory changed".to_owned());
    }
    let mut total = 0_u64;
    for (path, digest) in files {
        execution.check()?;
        let path = Path::new(path);
        if !path.is_absolute() {
            return Err("neural runtime absolute file pin".to_owned());
        }
        let expected = digest
            .as_str()
            .ok_or("neural runtime file digest")?
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        total = total
            .checked_add(verify_file(
                path,
                expected,
                16 * 1024 * 1024 * 1024,
                execution,
            )?)
            .ok_or("neural runtime byte overflow")?;
        if total > 16 * 1024 * 1024 * 1024 {
            return Err("neural runtime total byte bound".to_owned());
        }
    }
    execution.check()
}

pub(super) fn verify_interpreter(
    python: &Path,
    raw: &[u8],
    execution: &NeuralCognitiveExecutionV1,
) -> Result<(), String> {
    snapshot_digest(raw)?;
    execution.check()?;
    let value: serde_json::Value = serde_json::from_slice(raw).map_err(|e| e.to_string())?;
    let executable = value["python"]["executable"]
        .as_str()
        .ok_or("neural runtime interpreter pin is required")?;
    let path = Path::new(executable);
    if value["schema"] != "hepta-controlled-cold-runtime-snapshot-v2"
        || !python.is_absolute()
        || !path.is_absolute()
        || python.canonicalize().map_err(|e| e.to_string())? != path
        || path.canonicalize().map_err(|e| e.to_string())? != path
    {
        return Err("neural runtime interpreter identity differs".to_owned());
    }
    let expected = value["files"][executable]
        .as_str()
        .ok_or("neural runtime interpreter bytes must be independently pinned")?
        .parse::<Digest32>()
        .map_err(|e| e.to_string())?;
    if verify_file(path, expected, 128 * 1024 * 1024, execution)? == 0 {
        return Err("neural runtime empty interpreter image".to_owned());
    }
    Ok(())
}

fn verify_file(
    path: &Path,
    expected: Digest32,
    maximum: u64,
    execution: &NeuralCognitiveExecutionV1,
) -> Result<u64, String> {
    let path = path.canonicalize().map_err(|e| e.to_string())?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(&path)
        .map_err(|e| e.to_string())?;
    let before = file.metadata().map_err(|e| e.to_string())?;
    if !before.is_file() || before.len() > maximum {
        return Err("neural runtime interpreter file bound".to_owned());
    }
    let mut hash = Sha256::new();
    let mut count = 0_u64;
    let mut block = [0_u8; 64 * 1024];
    loop {
        execution.check()?;
        let size = file.read(&mut block).map_err(|e| e.to_string())?;
        if size == 0 {
            break;
        }
        count += size as u64;
        if count > before.len() {
            return Err("neural runtime interpreter grew during admission".to_owned());
        }
        hash.update(&block[..size]);
    }
    let after = file.metadata().map_err(|e| e.to_string())?;
    if count != before.len()
        || before.dev() != after.dev()
        || before.ino() != after.ino()
        || before.mtime_nsec() != after.mtime_nsec()
        || before.mtime() != after.mtime()
        || before.ctime_nsec() != after.ctime_nsec()
        || before.ctime() != after.ctime()
        || Digest32::from_array(hash.finalize().into()) != expected
    {
        return Err("neural runtime interpreter bytes changed".to_owned());
    }
    execution.check()?;
    Ok(count)
}

#[cfg(test)]
#[path = "smollm_python_runtime_tests.rs"]
mod tests;
