//! Unverified same-request FD preparation; promotion requires full byte proof.

use super::*;
use prefix::CatalogProgramRead;
use prefix::program_namespace;
use std::io::Seek;
use std::io::SeekFrom;

/// Owns the actual catalog FDs without claiming their content is valid.
/// No caller can construct this context or convert it to a byte proof without
/// the catalog's complete read. It contains no Agent allowance or authority.
pub struct PreparedReleaseRead {
    programs: Vec<PreparedProgram>,
}

struct PreparedProgram {
    program: PathBuf,
    file: File,
    snapshot: Snapshot,
    manifest: ManifestRead,
    expected_sha256: String,
    namespace: Vec<DirectoryIdentity>,
}

impl PreparedReleaseRead {
    pub(crate) fn new() -> Self {
        Self {
            programs: Vec::new(),
        }
    }

    pub(crate) fn prepare_program(
        &mut self,
        program: &Path,
        manifest: &ManifestRead,
        expected_sha256: &str,
    ) -> Result<(), FleetRegistryError> {
        let namespace = program_namespace(program)?;
        let file = File::options()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(program)?;
        let snapshot = Snapshot::capture(program, &file)?;
        manifest.verify_current()?;
        if program_namespace(program)? != namespace {
            return Err(changed("program namespace changed during preparation"));
        }
        self.programs.push(PreparedProgram {
            program: program.to_path_buf(),
            file,
            snapshot,
            manifest: manifest.clone(),
            expected_sha256: expected_sha256.to_owned(),
            namespace,
        });
        Ok(())
    }

    pub(crate) fn verify_catalog_program(
        &self,
        program: &Path,
        manifest: &ManifestRead,
        expected_sha256: &str,
    ) -> Result<(), FleetRegistryError> {
        self.programs
            .iter()
            .find(|fact| fact.program == program)
            .ok_or_else(|| changed("descriptor is outside the prepared catalog"))?
            .verify_current(manifest, expected_sha256)
    }

    pub(crate) fn read_verified_program(
        &mut self,
        cache: &ReleaseDigestCache,
        program: &Path,
        manifest: &ManifestRead,
        expected_sha256: &str,
    ) -> Result<CatalogProgramRead, FleetRegistryError> {
        let index = self
            .programs
            .iter()
            .position(|fact| fact.program == program)
            .ok_or_else(|| changed("physical use is outside the prepared catalog"))?;
        let mut fact = self.programs.swap_remove(index);
        fact.verify_current(manifest, expected_sha256)?;
        fact.file.seek(SeekFrom::Start(0))?;
        let entry = cache.opened_hashes(program, manifest, &mut fact.file, false)?;
        if entry.sha256 != expected_sha256 {
            return Err(changed("prepared program differs from immutable metadata"));
        }
        fact.verify_current(manifest, expected_sha256)?;
        Ok(CatalogProgramRead {
            program: fact.program,
            file: fact.file,
            entry,
            namespace: fact.namespace,
        })
    }
}

impl PreparedProgram {
    fn verify_current(
        &self,
        manifest: &ManifestRead,
        expected_sha256: &str,
    ) -> Result<(), FleetRegistryError> {
        if self.expected_sha256 != expected_sha256
            || self.manifest.sha256 != manifest.sha256
            || self.manifest.snapshot != manifest.snapshot
            || Snapshot::capture(&self.program, &self.file)? != self.snapshot
            || program_namespace(&self.program)? != self.namespace
        {
            return Err(changed(
                "prepared catalog identity changed before verification",
            ));
        }
        manifest.verify_current()
    }
}
