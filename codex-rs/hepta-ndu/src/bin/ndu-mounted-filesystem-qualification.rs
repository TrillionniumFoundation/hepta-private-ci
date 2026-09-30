//! Native fixture for real mounted-filesystem failures, driven over stdin by
//! the qualification orchestrator. It never opens a user or production store.
use std::error::Error;
use std::io;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;

use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreError;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_types::Digest32;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn phase(expected: &str) -> Result<(), Box<dyn Error>> {
    let mut line = String::new();
    io::stdin().lock().take(64).read_line(&mut line)?;
    if line.trim_end() != expected {
        return Err("unexpected or missing qualification phase".into());
    }
    Ok(())
}

fn report(value: &str) -> Result<(), Box<dyn Error>> {
    let mut out = io::stdout().lock();
    writeln!(out, "{value}")?;
    out.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() != 2 || !cfg!(target_os = "linux") {
        return Err("requires an empty private Linux fixture directory and enospc or erofs".into());
    }
    let root = PathBuf::from(&arguments[0]);
    if !root.is_absolute() || root.canonicalize()? != root || root.read_dir()?.next().is_some() {
        return Err(
            "qualification may only initialize an empty canonical fixture directory".into(),
        );
    }
    let errno = match arguments[1].to_str() {
        Some("enospc") => 28,
        Some("erofs") => 30,
        _ => return Err("unregistered mounted-filesystem fault".into()),
    };
    let mut store = NduProjectionStoreV1::open(&root)?;
    let objective = digest("mounted-fs-objective");
    let subject = digest("mounted-fs-subject");
    let projection = digest("mounted-fs-projection");
    store.append_projection(
        NduProjectionKindV1::Preference,
        digest("mounted-fs-append"),
        objective,
        subject,
        projection,
    )?;
    store.select_projection(digest("mounted-fs-select"), objective, subject, projection)?;
    let stale_backup = store.backup_bytes()?;
    store.revoke_projection(digest("mounted-fs-revoke"), objective, subject, projection)?;
    let before = store.backup_bytes()?;
    if store.entries()?.len() != 3
        || store
            .selected_projection_digest(objective, subject)?
            .is_some()
    {
        return Err("revocation fixture did not reach its expected state".into());
    }
    report("READY")?;
    phase("APPLY")?;
    let failed = store.append_projection(
        NduProjectionKindV1::Preference,
        digest("mounted-fs-failed-append"),
        objective,
        subject,
        digest("mounted-fs-next-projection"),
    );
    let expected = NduProjectionStoreError::Io(io::Error::from_raw_os_error(errno).kind());
    if failed != Err(expected) || store.is_indeterminate() || store.backup_bytes()? != before {
        return Err(
            format!("mounted filesystem did not preserve pre-commit state: {failed:?}").into(),
        );
    }
    report("FAULT_OBSERVED")?;
    phase("RECOVER")?;
    drop(store);
    let mut reopened = NduProjectionStoreV1::open(&root)?;
    if reopened.backup_bytes()? != before
        || reopened
            .selected_projection_digest(objective, subject)?
            .is_some()
        || reopened.restore_backup(&stale_backup) != Err(NduProjectionStoreError::BackupRegression)
    {
        return Err(
            "reopen or stale-backup rejection failed after mounted filesystem fault".into(),
        );
    }
    reopened.append_projection(
        NduProjectionKindV1::Preference,
        digest("mounted-fs-recovery-append"),
        objective,
        subject,
        digest("mounted-fs-recovery-projection"),
    )?;
    drop(reopened);
    let recovered = NduProjectionStoreV1::open(&root)?;
    if recovered.entries()?.len() != 4
        || recovered
            .selected_projection_digest(objective, subject)?
            .is_some()
    {
        return Err("recovered writer lost history or resurrected a revoked projection".into());
    }
    report("RECOVERED")
}
