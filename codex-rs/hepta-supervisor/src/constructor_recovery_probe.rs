//! Constructor-only absence probes after a complete Fleet read and independent
//! process-owner recovery. Presence never supplies recovery or mutation input:
//! it retains the original fresh full-Fleet validation and bounded codecs.

use std::io::ErrorKind;
use std::path::Path;

pub(super) fn restart_required(run_root: &Path) -> bool {
    !known_absent(
        run_root,
        &[
            crate::control_intent::CONTROL_INTENT_FILE,
            crate::restart_journal::RESTART_JOURNAL_FILE,
            crate::restart_lineage::RESTART_LINEAGE_FILE,
        ],
    )
}

pub(super) fn release_required(run_root: &Path) -> bool {
    !known_absent(
        run_root,
        &[crate::release_transaction::RELEASE_TRANSACTION_FILE],
    )
}

pub(super) fn known_absent(run_root: &Path, names: &[&str]) -> bool {
    let Ok(parent) = std::fs::symlink_metadata(run_root) else {
        return false;
    };
    if !parent.is_dir() || parent.file_type().is_symlink() {
        return false;
    }
    // A symlink, FIFO, directory, unreadable or damaged file is still evidence
    // to validate. Only a physical parent plus explicit NotFound may skip work.
    // I/O failures retain the original path rather than becoming absence.
    names.iter().all(|name| {
        matches!(
            std::fs::symlink_metadata(run_root.join(name)),
            Err(error) if error.kind() == ErrorKind::NotFound
        )
    })
}

#[cfg(test)]
#[path = "constructor_recovery_probe_tests.rs"]
mod tests;
