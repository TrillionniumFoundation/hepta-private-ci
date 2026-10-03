//! Public pinned configuration bytes only. Effect slots remain private.
use super::*;

fn public_directory(directory: &Path) -> Result<()> {
    ensure!(
        directory.is_absolute() && directory.canonicalize()? == directory,
        "noncanonical Root public source directory"
    );
    for ancestor in directory.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        ensure!(
            metadata.is_dir()
                && metadata.uid() == 0
                && metadata.mode() & 0o022 == 0
                && metadata.mode() & 0o001 != 0,
            "Root public source ancestors must be protected and traversable"
        );
    }
    let metadata = std::fs::symlink_metadata(directory)?;
    ensure!(
        metadata.mode() & 0o005 == 0o005,
        "Root public source directory must be readable"
    );
    Ok(())
}

pub(super) fn public_root_source(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> Result<InstalledCpuSourceV1> {
    // The directory comes from the original Root-pinned per-round configuration.
    // Installation owns its creation; this purpose cannot chmod a private ancestor.
    public_directory(directory)?;
    ensure!(
        !name.is_empty()
            && Path::new(name).components().count() == 1
            && matches!(
                Path::new(name).components().next(),
                Some(std::path::Component::Normal(_))
            ),
        "Root public source name must be one original leaf"
    );
    let source = root_source(directory, name, bytes, maximum)?;
    let metadata = std::fs::symlink_metadata(&source.path)?;
    ensure!(
        metadata.is_file()
            && metadata.uid() == 0
            && metadata.mode() & 0o222 == 0
            && metadata.mode() & 0o444 == 0o444
            && metadata.nlink() == 1,
        "Root public source must remain immutable and independently readable"
    );
    public_directory(directory)?;
    Ok(source)
}

#[cfg(test)]
#[path = "root_self_iteration_owners_public_sources_tests.rs"]
mod tests;
