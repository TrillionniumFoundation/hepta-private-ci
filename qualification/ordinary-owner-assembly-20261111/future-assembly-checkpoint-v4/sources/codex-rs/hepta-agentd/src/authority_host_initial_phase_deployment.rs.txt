//! Same-phase access to the original Initial deployment reader. These methods
//! expose pinned material only; registration still consumes the real Root cap.

use super::RootGenerationInitialDeploymentFilesV1;
use super::inputs::InitialOriginalFiles;
use super::shared_files::OriginalFile;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;
use std::io;
use std::path::Path;
use std::sync::Arc;

impl RootGenerationInitialDeploymentFilesV1 {
    pub(in crate::authority_host_runtime::session) fn original_phase_initial_current(
        &self,
    ) -> io::Result<Arc<RootAuthorityDirectory>> {
        self.require_original_initial_files()?;
        if !matches!(self.data.mode, crate::RootGenerationInitialModeV1::Reserve) {
            return Err(io::Error::other("fresh phase requires original Initial Reserve mode"));
        }
        Ok(Arc::clone(&self.inputs.current))
    }

    pub(in crate::authority_host_runtime::session) fn original_phase_initial_current_path(
        &self,
    ) -> &Path {
        &self.data.current_directory
    }

    pub(in crate::authority_host_runtime::session) fn original_phase_initial_consumer_root(
        &self,
    ) -> &Path {
        &self.data.consumer_state_root
    }

    pub(in crate::authority_host_runtime::session) fn original_phase_initial_trigger(
        &self,
    ) -> &Path {
        &self.data.trigger
    }

    pub(in crate::authority_host_runtime::session) fn original_phase_initial_digest(
        &self,
    ) -> Digest32 {
        self.descriptor.digest()
    }

    pub(in crate::authority_host_runtime::session) fn original_phase_initial_inputs(
        &self,
        consumer_uid: u32,
    ) -> io::Result<(crate::RootGenerationInitialEnrollmentV1, Vec<OriginalFile>)> {
        self.require_original_initial_files()?;
        let original: &InitialOriginalFiles = &self.inputs;
        let inputs = original.initial_enrollment_inputs(&self.data, consumer_uid)?;
        self.require_original_initial_files()?;
        Ok(inputs)
    }

    pub(in crate::authority_host_runtime::session) fn require_original_phase_initial_files(
        &self,
    ) -> io::Result<()> {
        self.require_original_initial_files()
    }
}
