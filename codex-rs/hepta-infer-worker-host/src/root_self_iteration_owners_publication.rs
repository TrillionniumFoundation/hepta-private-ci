//! Publish existing signed bytes to original bounded native-role input readers.
//! This performs no signing, role admission or artifact/registry publication.
use super::*;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub(in crate::root_frozen_generator) fn prepare_effect_directory(path: &Path) -> Result<()> {
    let parent = path.parent().context("original round parent absent")?;
    execution::protected_directory(parent)?;
    match std::fs::DirBuilder::new().mode(0o700).create(path) {
        Ok(()) => std::fs::File::open(parent)?.sync_all()?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
        Err(error) => return Err(error.into()),
    }
    execution::protected_directory(path)
}

fn role_directory(directory: &Path, uid: u32, gid: u32) -> Result<()> {
    ensure!(
        directory.is_absolute() && directory.canonicalize()? == directory,
        "noncanonical original role input directory"
    );
    let metadata = std::fs::symlink_metadata(directory)?;
    ensure!(
        metadata.is_dir()
            && metadata.uid() == uid
            && metadata.gid() == gid
            && metadata.mode() & 0o022 == 0,
        "original enrolled role input directory"
    );
    for ancestor in directory
        .parent()
        .context("original role input parent absent")?
        .ancestors()
    {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        ensure!(
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
            "original role input ancestor must remain Root protected"
        );
    }
    Ok(())
}

pub(super) fn root_source(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> Result<InstalledCpuSourceV1> {
    execution::protected_directory(directory)?;
    let path = directory.join(name);
    execution::immutable(&path, bytes, maximum)?;
    Ok(InstalledCpuSourceV1 {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    })
}
pub(super) fn root_existing(
    directory: &Path,
    name: &str,
    maximum: usize,
) -> Result<InstalledCpuSourceV1> {
    execution::protected_directory(directory)?;
    let path = directory.join(name);
    let bytes = read_root_review_input(&path, maximum as u64)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(!bytes.is_empty(), "whole original fixed role result absent");
    Ok(InstalledCpuSourceV1 {
        path,
        digest: Digest32::of_bytes(&bytes).to_string(),
    })
}

pub(in crate::root_frozen_generator) fn publish_consumer(
    config: &RoundConfiguration,
    bytes: &[u8],
    frozen: Digest32,
) -> Result<InstalledCpuSourceV1> {
    let directory = &config.consumer_directory;
    let maximum = MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES;
    ensure!(
        !frozen.is_zero(),
        "original immutable Generator consumer identity"
    );
    role_source(
        directory,
        &format!("consumer-{frozen}.bin"),
        bytes,
        maximum,
        config.generator_uid,
        config.generator_gid,
    )
}
pub(super) fn role_source(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
    uid: u32,
    gid: u32,
) -> Result<InstalledCpuSourceV1> {
    ensure!(
        uid > 0 && gid > 0 && !bytes.is_empty() && bytes.len() <= maximum,
        "whole existing signed native-role input bounds"
    );
    role_directory(directory, uid, gid)?;
    let path = directory.join(name);
    if !path.try_exists()? {
        let mut random = [0u8; 32];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut random)?;
        let temporary = directory.join(format!(".role-input-{}", Digest32::of_bytes(&random)));
        let mut file = std::fs::File::options()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)?;
        let result = (|| -> Result<()> {
            file.write_all(bytes)?;
            // Ownership belongs to the actual previously enrolled publisher;
            // the original signature is independently validated by every role.
            rustix::fs::fchown(
                &file,
                Some(rustix::process::Uid::from_raw(uid)),
                Some(rustix::process::Gid::from_raw(gid)),
            )?;
            file.set_permissions(std::fs::Permissions::from_mode(0o444))?;
            file.sync_all()?;
            match rustix::fs::renameat_with(
                rustix::fs::CWD,
                &temporary,
                rustix::fs::CWD,
                &path,
                rustix::fs::RenameFlags::NOREPLACE,
            ) {
                Ok(()) => (),
                Err(rustix::io::Errno::EXIST) => {
                    std::fs::remove_file(&temporary)?;
                }
                Err(error) => return Err(std::io::Error::from(error).into()),
            }
            std::fs::File::open(directory)?.sync_all()?;
            Ok(())
        })();
        if result.is_err() {
            let _ = std::fs::remove_file(&temporary);
        }
        result?;
    }
    ensure!(
        read_self_iteration_role_input_v1(&path, uid, maximum)
            .map_err(|error| anyhow::anyhow!("{error}"))?
            == bytes,
        "whole original signed input differs or is not atomically published"
    );
    role_directory(directory, uid, gid)?;
    Ok(InstalledCpuSourceV1 {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    })
}
