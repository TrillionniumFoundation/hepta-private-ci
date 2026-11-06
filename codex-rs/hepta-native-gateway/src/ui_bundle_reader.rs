//! Descriptor-relative reads follow the existing exec-server no-follow pattern.
//! No pathname reopen or canonicalize-then-open fallback is used after anchoring.

use std::path::Path;

use anyhow::Result;

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::path::Component;

#[cfg(unix)]
use anyhow::Context;
#[cfg(unix)]
use anyhow::ensure;
#[cfg(unix)]
use rustix::fs::Mode;
#[cfg(unix)]
use rustix::fs::OFlags;

pub(super) struct Directory {
    #[cfg(unix)]
    file: File,
}

impl Directory {
    #[cfg(unix)]
    pub(super) fn open(path: &Path) -> Result<Self> {
        ensure!(path.is_absolute(), "UI bundle directory must be absolute");
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        let mut file = File::from(rustix::fs::open("/", flags, Mode::empty())?);
        for component in path.components() {
            match component {
                Component::RootDir => {}
                Component::Normal(name) => {
                    file = File::from(
                        rustix::fs::openat(&file, name, flags, Mode::empty())
                            .context("open UI bundle directory without following links")?,
                    );
                }
                Component::CurDir | Component::ParentDir | Component::Prefix(_) => {
                    anyhow::bail!("UI bundle directory must be normalized");
                }
            }
        }
        Ok(Self { file })
    }

    #[cfg(not(unix))]
    pub(super) fn open(_path: &Path) -> Result<Self> {
        anyhow::bail!(
            "UI bundle serving is unsupported until this platform has a reviewed anchored reader; read-only health/runtime APIs remain available without a bundle"
        )
    }

    #[cfg(unix)]
    pub(super) fn read(&self, relative: &str, limit: usize) -> Result<Vec<u8>> {
        ensure!(
            super::valid_asset_path(relative),
            "invalid UI relative path"
        );
        let mut directory = self.file.try_clone()?;
        let mut components = relative.split('/').peekable();
        while let Some(name) = components.next() {
            if components.peek().is_some() {
                directory = File::from(
                    rustix::fs::openat(
                        &directory,
                        name,
                        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                        Mode::empty(),
                    )
                    .context("open anchored UI asset directory")?,
                );
                continue;
            }
            // NONBLOCK prevents a FIFO/device replacement from blocking before fstat.
            let file = File::from(
                rustix::fs::openat(
                    &directory,
                    name,
                    OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .context("open anchored UI asset")?,
            );
            let metadata = file.metadata()?;
            ensure!(metadata.is_file(), "UI resource is not a regular file");
            ensure!(
                metadata.len() <= u64::try_from(limit)?,
                "UI resource exceeds byte bound"
            );
            let mut bytes = Vec::new();
            file.take(
                u64::try_from(limit)?
                    .checked_add(1)
                    .context("UI read bound overflow")?,
            )
            .read_to_end(&mut bytes)?;
            ensure!(bytes.len() <= limit, "UI resource grew beyond byte bound");
            return Ok(bytes);
        }
        anyhow::bail!("UI resource path is empty")
    }

    #[cfg(not(unix))]
    pub(super) fn read(&self, _relative: &str, _limit: usize) -> Result<Vec<u8>> {
        anyhow::bail!("UI bundle serving is unsupported on this platform")
    }
}
