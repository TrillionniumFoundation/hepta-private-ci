//! Fixed normal-host loading under the same session and absolute operation end.

use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::FileAnchorWitnessStore;

use super::InitialHostPhase;
use super::PreparedHostAuthoritySession;
use super::PreparedRootHostInitialGenerationV1;
use super::invalid;
use super::require_original_session;
use crate::AgentdError;
use crate::HostAuthorityService;
use crate::RootHostInitialGenerationFilesV1;
use crate::authority_host_service::OriginalGenerationLoadPurpose;
use crate::authority_host_service::OriginalLoadedGeneration;

impl PreparedHostAuthoritySession {
    /// Load existing original Artifact/consumer state and real selection/target
    /// files, then retain Fresh inputs without publishing CURRENT or signing.
    /// The explicit empty target witness can receive its original header. An
    /// error is not a general promise that all supplied files are unchanged.
    pub fn prepare_original_initial_generation_from_files(
        self,
        deployment: &Path,
        files: RootHostInitialGenerationFilesV1,
    ) -> Result<PreparedRootHostInitialGenerationV1<FileAnchorWitnessStore>, AgentdError> {
        let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);
        require_original_session(&self, end)?;
        let OriginalLoadedGeneration::Fresh(inputs) = HostAuthorityService::load_original_initial_generation_inputs(
            &self.service, &self.config.state_dir, deployment, files, OriginalGenerationLoadPurpose::Fresh, end,
        )? else {
            return Err(invalid("the fixed Fresh input loader returned another purpose"));
        };
        let operation = HostAuthorityService::bind_original_initial_operation(&self.service, &inputs, end)?;
        require_original_session(&self, end)?;
        Ok(PreparedRootHostInitialGenerationV1 {
            session: self, operation, phase: InitialHostPhase::Fresh(inputs), end,
        })
    }

    /// Recover the exact existing publication under this retained session. The
    /// complete protected operation id/intent, target, signed selection, issuer,
    /// consumed nonce and CURRENT are checked by the original recovery factory.
    /// This path never falls back to Fresh or increases the original deadline.
    pub fn recover_original_initial_generation_from_files(
        self,
        deployment: &Path,
        files: RootHostInitialGenerationFilesV1,
    ) -> Result<PreparedRootHostInitialGenerationV1<FileAnchorWitnessStore>, AgentdError> {
        let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);
        require_original_session(&self, end)?;
        let OriginalLoadedGeneration::Recover(inputs) = HostAuthorityService::load_original_initial_generation_inputs(
            &self.service, &self.config.state_dir, deployment, files, OriginalGenerationLoadPurpose::Recover, end,
        )? else {
            return Err(invalid("the fixed recovery loader returned another purpose"));
        };
        let (operation, custody) = HostAuthorityService::recover_original_initial_operation(&self.service, inputs, end)?;
        require_original_session(&self, end)?;
        Ok(PreparedRootHostInitialGenerationV1 {
            session: self, operation, phase: InitialHostPhase::Ready(custody), end,
        })
    }
}
