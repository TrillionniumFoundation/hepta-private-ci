//! Retain the independently selected original Worker ELF as a read-only fact.
use super::*;
use codex_hepta_agent_components::learning_ledger::open_root_review_input;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::os::unix::fs::MetadataExt;
type Identity = (u64, u64, u64, i64, i64, i64, i64);
fn identity(meta: &std::fs::Metadata) -> Identity {
    (
        meta.dev(),
        meta.ino(),
        meta.len(),
        meta.mtime(),
        meta.mtime_nsec(),
        meta.ctime(),
        meta.ctime_nsec(),
    )
}
pub(super) struct VerifiedWorker {
    source: InstalledCpuSourceV1,
    file: File,
    identity: Identity,
}
impl VerifiedWorker {
    pub(super) fn source(&self) -> &InstalledCpuSourceV1 {
        &self.source
    }
    pub(super) fn open(
        source: &InstalledCpuSourceV1,
        expected: Digest32,
    ) -> Result<Self, AgentdError> {
        if expected.is_zero() || digest(&source.digest)? != expected {
            return Err(invalid("Worker ELF differs from independent Fleet pin"));
        }
        let mut file =
            open_root_review_input(&source.path).map_err(|error| invalid(error.to_string()))?;
        let before = identity(&file.metadata()?);
        let mut magic = [0_u8; 4];
        file.read_exact(&mut magic)?;
        if magic != *b"\x7fELF" {
            return Err(invalid("original protected Worker input is not ELF"));
        }
        file.seek(SeekFrom::Start(0))?;
        if Digest32::of_reader(&mut file, 512 * 1024 * 1024)
            .map_err(|error| invalid(error.to_string()))?
            != expected
        {
            return Err(invalid("original protected Worker ELF SHA changed"));
        }
        let retained = Self {
            source: source.clone(),
            file,
            identity: before,
        };
        retained.revalidate()?;
        Ok(retained)
    }
    pub(super) fn revalidate(&self) -> Result<(), AgentdError> {
        let current = open_root_review_input(&self.source.path)
            .map_err(|error| invalid(error.to_string()))?;
        if identity(&self.file.metadata()?) != self.identity
            || identity(&current.metadata()?) != self.identity
        {
            return Err(invalid("original protected Worker ELF identity changed"));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "local_cpu_parameter_root_worker_tests_v2.rs"]
mod tests;
