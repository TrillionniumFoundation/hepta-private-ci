//! Keep original fixture directories even when preparation or a business
//! phase returns early. Retention records no successful task or authority.
#![cfg(test)]

use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

#[path = "ordinary_q24_evidence_custody_check_tests.rs"]
mod tests;

pub(super) enum OriginalEvidenceDirectoryKind {
    AProtected,
    ARuntime,
    ModelWitness,
    IndependentBBusiness,
}

pub(super) struct OriginalEvidenceDirectory {
    directory: Option<tempfile::TempDir>,
    kind: OriginalEvidenceDirectoryKind,
}

impl OriginalEvidenceDirectory {
    pub(super) fn new(directory: tempfile::TempDir, kind: OriginalEvidenceDirectoryKind) -> Self {
        Self {
            directory: Some(directory),
            kind,
        }
    }

    pub(super) fn path(&self) -> &Path {
        self.directory
            .as_ref()
            .expect("original evidence directory is owned until consumed")
            .path()
    }

    pub(super) fn keep(mut self) -> PathBuf {
        self.retain_original("explicit_keep")
            .expect("original evidence directory is consumed once")
    }

    fn retain_original(&mut self, reason: &str) -> Option<PathBuf> {
        let path = self.directory.take()?.keep();
        let role = match self.kind {
            OriginalEvidenceDirectoryKind::AProtected => "a_protected",
            OriginalEvidenceDirectoryKind::ARuntime => "a_runtime",
            OriginalEvidenceDirectoryKind::ModelWitness => "post_a_model_witness",
            OriginalEvidenceDirectoryKind::IndependentBBusiness => "independent_b_business",
        };
        // Keep the same directory and inodes. A marker is custody data only;
        // output failure must not replace the original error or panic in Drop.
        let _ = writeln!(
            std::io::stderr(),
            "ORDINARY_Q24_RETAINED_DIRECTORY role={role} reason={reason} path={}",
            path.display()
        );
        Some(path)
    }
}

impl Drop for OriginalEvidenceDirectory {
    fn drop(&mut self) {
        let _ = self.retain_original("scope_exit");
    }
}
