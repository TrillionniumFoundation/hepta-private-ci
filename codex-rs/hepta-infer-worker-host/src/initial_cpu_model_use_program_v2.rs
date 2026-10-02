//! Retain the once-verified Root implementation FD; current use checks physical
//! identity rather than hashing the same large signer ELF for every Goal.
use super::*;
use std::fs::File;
use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;

type Identity = (u64, u64, u32, u32, u32, u64, u64, i64, i64, i64, i64);
fn identity(m: &Metadata) -> Identity {
    (
        m.dev(),
        m.ino(),
        m.uid(),
        m.gid(),
        m.mode(),
        m.nlink(),
        m.len(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    )
}
pub(super) struct Program {
    source: Source,
    file: File,
    original: Identity,
}
impl Program {
    pub(super) fn open(source: Source) -> HostResult<Self> {
        let mut file =
            codex_hepta_agent_components::learning_ledger::open_root_review_input(&source.path)?;
        let original = identity(&file.metadata()?);
        if original.6 == 0
            || original.6 > 512 * 1024 * 1024
            || Digest32::of_reader(&mut file, 512 * 1024 * 1024)? != digest(&source.digest)?
        {
            return Err("fixed current S implementation pin or size".into());
        }
        let program = Self {
            source,
            file,
            original,
        };
        program.revalidate()?;
        Ok(program)
    }
    pub(super) fn revalidate(&self) -> HostResult<()> {
        let current = codex_hepta_agent_components::learning_ledger::open_root_review_input(
            &self.source.path,
        )?;
        if identity(&self.file.metadata()?) != self.original
            || identity(&current.metadata()?) != self.original
        {
            return Err("fixed current S implementation changed at use".into());
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "initial_cpu_model_use_program_v2_tests.rs"]
mod tests;
