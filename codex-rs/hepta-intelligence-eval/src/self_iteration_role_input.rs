//! Read a bounded current publication from an installed role's sole directory.
//! The immutable Root config authorizes the path/UID; signatures authorize data.
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Component;
use std::path::Path;

/// Read only bounded bytes from the configured publisher's exclusive directory.
/// Every recipient must authenticate the original role signature separately.
pub fn read_self_iteration_role_input_v1(
    path: &Path,
    publisher_uid: u32,
    maximum: usize,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    if publisher_uid == 0
        || maximum == 0
        || maximum > 128 * 1024 * 1024
        || !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
    {
        return Err("installed role input path or UID".into());
    }
    let parent = path.parent().ok_or("role input parent")?;
    for (index, ancestor) in parent.ancestors().enumerate() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir()
            || metadata.mode() & 0o022 != 0
            || metadata.uid() != if index == 0 { publisher_uid } else { 0 }
        {
            return Err("installed role input directory ownership".into());
        }
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.uid() != publisher_uid
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > maximum as u64
    {
        return Err("installed role input file ownership or bound".into());
    }
    let file = File::open(path)?;
    let after = file.metadata()?;
    if !after.is_file()
        || after.dev() != before.dev()
        || after.ino() != before.ino()
        || after.uid() != publisher_uid
        || after.nlink() != 1
        || after.mode() & 0o022 != 0
        || after.len() > maximum as u64
    {
        return Err("installed role input changed while opening".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("installed role input grew beyond bound".into());
    }
    Ok(bytes)
}
