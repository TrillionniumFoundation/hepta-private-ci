//! One original task export retains the same session for Material and V3.
//! No owner, task, runtime, clock or live capability leaves this private tree.

use std::sync::Arc;
use std::time::Instant;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;

use codex_hepta_neuron::FileAnchorWitnessStore;

use super::{OriginalHostInitialOperation, OriginalRootCircuitTaskCustodyV1,
    PreparedHostAuthoritySession, PreparedRootHostCircuitTaskV1,
    PreparedRootMaterialSourceHostV1, require_original_session};
use crate::AgentdError;
use crate::authority_host_runtime::{OriginalTaskResidentPrepared,
    OriginalTaskResidentInputs, OriginalTaskResidentPaths, OriginalTaskResidentPurpose,
    OriginalTaskPrefreezeState};
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;

pub(crate) struct OriginalLoadedTaskFollowups {
    session: Arc<PreparedHostAuthoritySession>,
    operation: Arc<OriginalHostInitialOperation>,
    custody: Arc<OriginalRootCircuitTaskCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
    end: Instant,
}

impl PreparedRootHostCircuitTaskV1<FileAnchorWitnessStore, FileAnchorWitnessStore> {
    pub(crate) fn take_original_loader_followups(&mut self) -> Result<(
        PreparedRootMaterialSourceHostV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        OriginalLoadedTaskFollowups,
    ), AgentdError> {
        // The existing single-use bit is consumed by the original exporter.
        // Failure does not return it, the task lane, or a fresh execution right.
        let material = PreparedRootHostCircuitTaskV1::prepare_original_material_source_host(self)?;
        let followups = OriginalLoadedTaskFollowups {
            session: Arc::clone(&self.session), operation: Arc::clone(&self.operation),
            custody: Arc::clone(&self.custody), end: self.end,
        };
        followups.require_original_task_followups()?;
        Ok((material, followups))
    }
}

impl OriginalLoadedTaskFollowups {
    pub(crate) fn require_original_task_followups(&self) -> Result<(), AgentdError> {
        require_original_session(&self.session, self.end)?;
        let observed = OriginalRootCircuitTaskCustodyV1::read_original_operation(&self.custody)?;
        if !matches!(observed, NeuronGenerationInitialReadbackV1::Published(_)) {
            return Err(AgentdError::Invalid("the original task generation is not Published".into()));
        }
        OriginalHostInitialOperation::require_observed(&self.operation, &observed)?;
        require_original_session(&self.session, self.end)
    }

    pub(crate) fn prepare_resident(
        &self, paths: OriginalTaskResidentPaths, original: OriginalTaskResidentInputs,
        prefreeze: &OriginalTaskPrefreezeState, purpose: OriginalTaskResidentPurpose, startup_end: Instant,
    ) -> Result<OriginalTaskResidentPrepared, AgentdError> {
        self.require_original_task_followups()?;
        let prepared = crate::authority_host_runtime::prepare_original_task_resident(
            &self.session.service, &self.session.config, &self.session.registration,
            &self.custody, paths, original, prefreeze, purpose, startup_end.min(self.end), self.end,
        )?;
        self.require_original_task_followups()?;
        Ok(prepared)
    }

    pub(crate) fn prepare_prefreeze(
        &self, disclosure_file: &Path, evidence_file: &Path,
        stream: UnixStream, original_material_pidfd: OwnedFd, startup_end: Instant,
    ) -> Result<(crate::OriginalRootPrefreezeSourceRegistrationV1, OriginalTaskPrefreezeState), AgentdError> {
        self.require_original_task_followups()?;
        let original = crate::authority_host_runtime::prepare_original_task_prefreeze(
            &self.session.config, &self.session.registration, disclosure_file, evidence_file,
            stream, original_material_pidfd, startup_end.min(self.end),
        )?;
        self.require_original_task_followups()?;
        Ok(original)
    }

    pub(crate) fn require_startup_end(&self, requested: Instant) -> Result<Instant, AgentdError> {
        self.require_original_task_followups()?;
        Ok(requested.min(self.end))
    }
}
