//! Signed repository-source inventory for the production HCSN host.
//! Observations are bounded and reject aliases; they are not an atomic file
//! system snapshot. The deployment owner must keep the source tree immutable
//! throughout supervisor and worker execution, including between checks.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use rustix::fs::Mode;
use rustix::fs::OFlags;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::Error as _;
use serde::de::MapAccess;
use serde::de::Visitor;

const MAX_SOURCE_FILES: usize = 512;
const MAX_SOURCE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_TREE_ENTRIES: usize = 16_384;
const MAX_TREE_DEPTH: usize = 32;
const MAX_SOURCE_PATH_BYTES: usize = 512;
const SOURCE_ROOTS: [&str; 2] = ["qualification/hcsn", "qualification/hcsn_training"];
const ROOT_INIT: &str = "qualification/__init__.py";

#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub(super) struct HcsnSourceManifest(BTreeMap<String, Sha256Digest>);

impl<'de> Deserialize<'de> for HcsnSourceManifest {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ManifestVisitor;
        impl<'de> Visitor<'de> for ManifestVisitor {
            type Value = HcsnSourceManifest;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a bounded map of repository Python paths to SHA-256 digests")
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut entries = BTreeMap::new();
                while let Some((path, digest)) = map.next_entry::<String, Sha256Digest>()? {
                    if entries.len() == MAX_SOURCE_FILES || !valid_source_path(&path) {
                        return Err(A::Error::custom(
                            "invalid HCSN source inventory bounds or path",
                        ));
                    }
                    Sha256Digest::parse(digest.as_str()).map_err(A::Error::custom)?;
                    if entries.insert(path, digest).is_some() {
                        return Err(A::Error::custom("duplicate HCSN source inventory path"));
                    }
                }
                if entries.is_empty() {
                    return Err(A::Error::custom("HCSN source inventory is empty"));
                }
                Ok(HcsnSourceManifest(entries))
            }
        }
        deserializer.deserialize_map(ManifestVisitor)
    }
}

impl HcsnSourceManifest {
    pub(super) fn verify(&self, repository: &Path) -> io::Result<()> {
        if !repository.is_absolute() {
            return invalid("HCSN source repository must be absolute");
        }
        let expected: BTreeSet<_> = self.0.keys().cloned().collect();
        if observe_inventory(repository)? != expected {
            return invalid("HCSN source inventory differs from its signed deployment");
        }
        let mut remaining = MAX_SOURCE_BYTES;
        for (relative, expected_digest) in &self.0 {
            let (digest, bytes) = read_source_digest(&repository.join(relative), remaining)?;
            if &digest != expected_digest {
                return invalid("HCSN source content differs from its signed deployment");
            }
            remaining -= bytes;
        }
        // An addition made during source reads must not be silently omitted.
        if observe_inventory(repository)? != expected {
            return invalid("HCSN source inventory changed during observation");
        }
        Ok(())
    }
}

fn valid_source_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= MAX_SOURCE_PATH_BYTES
        && !path.contains(['\\', '\0'])
        && path.ends_with(".py")
        && path
            .split('/')
            .all(|part| !part.is_empty() && part != "." && part != "..")
        && (path == ROOT_INIT
            || SOURCE_ROOTS.iter().any(|root| {
                path.strip_prefix(root)
                    .is_some_and(|tail| tail.starts_with('/'))
            }))
}

fn observe_inventory(repository: &Path) -> io::Result<BTreeSet<String>> {
    canonical_directory(repository)?;
    canonical_directory(&repository.join("qualification"))?;
    let mut sources = BTreeSet::new();
    let mut entries = 0;
    for relative in SOURCE_ROOTS {
        walk_sources(
            repository,
            &repository.join(relative),
            &mut sources,
            &mut entries,
            /*depth*/ 0,
        )?;
    }
    let init = repository.join(ROOT_INIT);
    match fs::symlink_metadata(&init) {
        Ok(metadata) => {
            if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.nlink() != 1 {
                return invalid("HCSN root initializer must be an unaliased regular source");
            }
            sources.insert(ROOT_INIT.to_string());
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    if sources.len() > MAX_SOURCE_FILES {
        return invalid("HCSN source inventory exceeds its file bound");
    }
    Ok(sources)
}

fn walk_sources(
    repository: &Path,
    directory: &Path,
    sources: &mut BTreeSet<String>,
    entries: &mut usize,
    depth: usize,
) -> io::Result<()> {
    if depth > MAX_TREE_DEPTH {
        return invalid("HCSN source tree exceeds its depth bound");
    }
    let initial = canonical_directory(directory)?;
    for entry in fs::read_dir(directory)? {
        *entries += 1;
        if *entries > MAX_TREE_ENTRIES {
            return invalid("HCSN source tree exceeds its traversal bound");
        }
        let path = entry?.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() {
            return invalid("HCSN source tree contains a symbolic alias");
        }
        if metadata.is_dir() {
            walk_sources(repository, &path, sources, entries, depth + 1)?;
        } else if metadata.is_file() {
            if path.extension().is_some_and(|extension| extension == "py") {
                let relative = path
                    .strip_prefix(repository)
                    .ok()
                    .and_then(Path::to_str)
                    .ok_or_else(|| io::Error::other("invalid HCSN source path"))?;
                if metadata.nlink() != 1 || !valid_source_path(relative) {
                    return invalid("HCSN source must have a canonical unaliased inventory path");
                }
                sources.insert(relative.to_string());
                if sources.len() > MAX_SOURCE_FILES {
                    return invalid("HCSN source inventory exceeds its file bound");
                }
            }
        } else {
            return invalid("HCSN source tree contains a non-regular entry");
        }
    }
    let observed = canonical_directory(directory)?;
    if file_observation(&initial) != file_observation(&observed) {
        return invalid("HCSN source directory changed during observation");
    }
    Ok(())
}

fn canonical_directory(path: &Path) -> io::Result<fs::Metadata> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_dir() || path.canonicalize()?.as_os_str() != path.as_os_str() {
        return invalid("HCSN source directory must have a canonical unaliased path");
    }
    Ok(metadata)
}

fn read_source_digest(path: &Path, maximum: u64) -> io::Result<(Sha256Digest, u64)> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("source has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| io::Error::other("source has no name"))?;
    let directory: File = rustix::fs::open(
        parent,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )?
    .into();
    let mut file: File = rustix::fs::openat(
        &directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )?
    .into();
    let initial = file.metadata()?;
    if !initial.is_file()
        || initial.nlink() != 1
        || initial.len() > maximum
        || path.canonicalize()?.as_os_str() != path.as_os_str()
    {
        return invalid("HCSN source must be a bounded unaliased regular file");
    }
    let length =
        usize::try_from(initial.len()).map_err(|_| io::Error::other("source length overflow"))?;
    let mut bytes = vec![0; length];
    file.read_exact(&mut bytes)?;
    let mut extra = [0; 1];
    if file.read(&mut extra)? != 0 {
        return invalid("HCSN source grew during observation");
    }
    let observed = file.metadata()?;
    let named = fs::symlink_metadata(path)?;
    if !observed.is_file()
        || observed.nlink() != 1
        || named.file_type().is_symlink()
        || file_observation(&initial) != file_observation(&observed)
        || file_observation(&initial) != file_observation(&named)
        || path.canonicalize()?.as_os_str() != path.as_os_str()
    {
        return invalid("HCSN source changed during observation");
    }
    Ok((Sha256Digest::for_bytes(&bytes), initial.len()))
}

fn file_observation(metadata: &fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
    (
        metadata.dev(),
        metadata.ino(),
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}

fn invalid<T>(message: &str) -> io::Result<T> {
    Err(io::Error::new(io::ErrorKind::InvalidData, message))
}

#[cfg(test)]
#[path = "automation_hcsn_source_tests.rs"]
mod tests;
