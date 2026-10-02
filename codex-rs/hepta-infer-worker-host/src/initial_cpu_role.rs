//! Check the actual immutable process and only its separately retained key.
use super::*;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;

pub(super) fn actual_role(inputs: &Inputs, role: &Role) -> HostResult<SigningKey> {
    let key = actual_role_for_program(&inputs.profile.program, role)?;
    inputs.revalidate()?;
    Ok(key)
}

pub(super) fn actual_role_for_program(
    program_source: &Source,
    role: &Role,
) -> HostResult<SigningKey> {
    require_actual_program(program_source, role)?;
    let path = &role.private_key_path;
    if !path.is_absolute() || path.canonicalize()? != *path {
        return Err("role key canonical path".into());
    }
    for ancestor in path.parent().ok_or("role private directory")?.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir()
            || ![0, role.uid].contains(&metadata.uid())
            || metadata.mode() & 0o022 != 0
        {
            return Err("role private key parent boundary".into());
        }
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.uid() != role.uid
        || before.gid() != role.gid
        || before.mode() & 0o077 != 0
        || before.nlink() != 1
        || before.len() != 32
    {
        return Err("role's exclusive original seed boundary".into());
    }
    let file = File::open(path)?;
    let opened = file.metadata()?;
    if before.dev() != opened.dev() || before.ino() != opened.ino() {
        return Err("role key identity changed".into());
    }
    let mut bytes = Vec::new();
    file.take(33).read_to_end(&mut bytes)?;
    let seed: [u8; 32] = bytes.try_into().map_err(|_| "role seed width")?;
    let key = SigningKey::from_bytes(&seed);
    if key.verifying_key().to_bytes() != public(&role.public_key_hex)? {
        return Err("role owns a different Root-pinned key".into());
    }
    Ok(key)
}
/// Check physical process custody without opening any role seed.
pub(super) fn require_actual_program(program_source: &Source, role: &Role) -> HostResult<()> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    require_actual_status(&status, role)?;
    let program = std::env::current_exe()?;
    if program.canonicalize()? != program_source.path
        || program_source.read(512 * 1024 * 1024)?.is_empty()
    {
        return Err("actual fixed CPU composition executable".into());
    }
    Ok(())
}
fn require_actual_status(status: &str, role: &Role) -> HostResult<()> {
    let field = |label: &str| {
        status
            .lines()
            .find_map(|line| line.strip_prefix(label))
            .map(str::trim)
            .ok_or("actual role status field")
    };
    let exact = |label, expected: u32| -> HostResult<()> {
        let values = field(label)?
            .split_whitespace()
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()?;
        if values != vec![expected; 4] {
            return Err("actual role changed UID/GID".into());
        }
        Ok(())
    };
    exact("Uid:", role.uid)?;
    exact("Gid:", role.gid)?;
    if field("NoNewPrivs:")? != "1"
        || u64::from_str_radix(field("CapEff:")?, 16)? != 0
        || u64::from_str_radix(field("CapPrm:")?, 16)? != 0
        || field("Groups:")?
            .split_whitespace()
            .any(|group| group.parse::<u32>() != Ok(role.gid))
    {
        return Err("actual role has privilege or another role's group".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "initial_cpu_role_tests.rs"]
mod tests;
