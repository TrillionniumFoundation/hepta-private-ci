//! Compare the actual normal Worker ELF with its protected whole-byte pin.
use super::*;
use std::os::unix::fs::MetadataExt;

fn identity(metadata: &std::fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
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

pub(super) fn verify(source: &Source) -> HostResult<()> {
    let expected = digest(&source.digest)?;
    codex_hepta_agent_components::intelligence_eval::verify_registered_operational_program_v3(
        &source.path,
        expected,
    )?;
    let mut actual = std::fs::File::open("/proc/self/exe")?;
    let before = identity(&actual.metadata()?);
    if Digest32::of_reader(&mut actual, 512 * 1024 * 1024)? != expected
        || identity(&actual.metadata()?) != before
    {
        return Err("Root body does not bind the whole actual normal WorkerHost ELF".into());
    }
    Ok(())
}
