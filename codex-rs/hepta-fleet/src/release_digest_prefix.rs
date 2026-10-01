//! Pins only immutable byte facts; no allowance, operation or lease is retained.

use super::*;
#[cfg(not(unix))]
use std::path::PathBuf;

/// Keeps verified byte-prefix facts available while a request waits for its owner.
pub struct ReleaseReadPin {
    #[cfg(unix)]
    _programs: Vec<Arc<Entry>>,
}

/// Fixed original program-byte domains used by the installed local host.
#[cfg(unix)]
#[derive(Clone, Copy)]
pub enum LaunchDigestDomain {
    Agent,
    Matrix,
}

/// A hash prefix bound to the actual open program, visible path and manifest.
#[cfg(unix)]
pub struct VerifiedLaunchDigest {
    program: PathBuf,
    file: File,
    manifest: ManifestRead,
    entry: Arc<Entry>,
    hasher: Sha256,
}

/// Retains the actual program FD through resource preparation and child spawn.
#[cfg(unix)]
pub struct VerifiedLaunchProgram {
    program: PathBuf,
    file: File,
    manifest: ManifestRead,
    entry: Arc<Entry>,
    digest: [u8; 32],
}

#[cfg(unix)]
impl VerifiedLaunchProgram {
    pub fn digest(&self) -> [u8; 32] {
        self.digest
    }

    pub fn verify_current(&self) -> Result<(), FleetRegistryError> {
        if Snapshot::capture(&self.program, &self.file)? != self.entry.snapshot {
            return Err(changed("program changed after launch digest was computed"));
        }
        self.manifest.verify_current()
    }

    pub fn program(&self) -> &Path {
        &self.program
    }
}

#[cfg(unix)]
impl VerifiedLaunchDigest {
    pub fn update(&mut self, bytes: impl AsRef<[u8]>) {
        self.hasher.update(bytes);
    }

    /// Recheck the exact FD and root custody after all launch context was added.
    pub fn finalize(self) -> Result<[u8; 32], FleetRegistryError> {
        self.commit().map(|program| program.digest())
    }

    pub fn commit(self) -> Result<VerifiedLaunchProgram, FleetRegistryError> {
        let program = VerifiedLaunchProgram {
            program: self.program,
            file: self.file,
            manifest: self.manifest,
            entry: self.entry,
            digest: self.hasher.finalize().into(),
        };
        program.verify_current()?;
        Ok(program)
    }
}

impl ReleaseDigestCache {
    pub(crate) fn pin_programs(
        &self,
        paths: &[PathBuf],
        manifest: &ManifestRead,
    ) -> Result<ReleaseReadPin, FleetRegistryError> {
        #[cfg(unix)]
        {
            let mut programs = Vec::with_capacity(paths.len());
            for path in paths {
                let mut file = File::options()
                    .read(true)
                    .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                    .open(path)?;
                let snapshot = Snapshot::capture(path, &file)?;
                if snapshot.root_custody.is_none() || manifest.snapshot.root_custody.is_none() {
                    // Ordinary installations have no cached facts to retain.
                    // The caller already fully read their programs, and the
                    // final launch will fully read them again as before.
                    manifest.verify_current()?;
                    continue;
                }
                programs.push(
                    self.opened_hashes(path, manifest, &mut file, /*defer_cold_read*/ true)?,
                );
            }
            Ok(ReleaseReadPin {
                _programs: programs,
            })
        }
        #[cfg(not(unix))]
        {
            let _ = (paths, manifest);
            Ok(ReleaseReadPin {})
        }
    }

    #[cfg(unix)]
    pub(crate) fn launch_prefix(
        &self,
        program: &Path,
        manifest: ManifestRead,
        expected_sha256: &str,
        domain: LaunchDigestDomain,
    ) -> Result<VerifiedLaunchDigest, FleetRegistryError> {
        let mut file = File::options()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(program)?;
        // Admitted timers/recovery retain full validation on cache miss. A
        // new Start is pinned by its read worker before lifecycle admission.
        let entry = self.opened_hashes(
            program, &manifest, &mut file, /*defer_cold_read*/ false,
        )?;
        if entry.sha256 != expected_sha256 {
            return Err(changed("launch program differs from immutable manifest"));
        }
        let hasher = match domain {
            LaunchDigestDomain::Agent => entry.agent_prefix.clone(),
            LaunchDigestDomain::Matrix => entry.matrix_prefix.clone(),
        };
        Ok(VerifiedLaunchDigest {
            program: program.to_path_buf(),
            file,
            manifest,
            entry,
            hasher,
        })
    }
}

#[cfg(all(test, unix))]
#[path = "release_digest_prefix_tests.rs"]
mod tests;
