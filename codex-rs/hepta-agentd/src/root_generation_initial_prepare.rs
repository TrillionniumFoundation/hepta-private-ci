//! Consumer-side original preparation. The initial proxy is installed only
//! after the actual files, independent selection and original initial-target
//! validator agree. The existing publication owner performs claim/dispatch.

use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalObserverV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use std::sync::Arc;

use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdSelectedGenerationV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalRootGenerationInitialV1;
use crate::PreparedAgentdGenerationInitialV1;
use crate::ReadyAgentdGenerationInitialV1;
use crate::RootGenerationInitialModeV1;
use crate::RootGenerationJournalInputsV1;

impl OriginalRootGenerationInitialV1 {
    pub(crate) fn prepare_original_initial(
        self,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        mut selected: AgentdSelectedGenerationV1,
        files: RootGenerationJournalInputsV1,
    ) -> Result<PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore>, AgentdError> {
        if self.client.mode() != RootGenerationInitialModeV1::Reserve {
            return Err(invalid("initial recovery cannot prepare a new operation"));
        }
        let profile = self.client.profile().clone();
        let observer = self.require_original_target(&files)?;
        observer.require_original_unwritten().map_err(invalid)?;
        let artifact_owner = Arc::clone(&authorities.artifacts);
        let artifacts = artifact_owner.lock().map_err(invalid)?;
        selected.revalidate(&artifacts, authorities.now()?)?;
        if selected.observation().digest().to_string() != profile.selection {
            return Err(invalid("initial independent selection differs from Root"));
        }
        let target = open_target(files)?;
        if crate::neuron_generation_initial::validate_initial_target(&selected, &target)?
            != profile.deployment.target
        {
            return Err(invalid("initial original target differs from Root"));
        }
        observer.require_original_unwritten().map_err(invalid)?;
        self.client.prepare_initial_current()?;
        // CURRENT is already durable. Any later failure is an uncertain
        // acknowledgement, never permission to initialize or claim again.
        let completed = (|| {
            let current = Arc::new(NeuronGenerationCurrentOwnerV1::from_original_root_initial(
                self.client,
            )?);
            let prepared = current.recover_initial_operation(
                &profile.deployment.operation,
                profile.intent.parse().map_err(invalid)?,
            )?;
            if prepared.target() != &profile.deployment.target
                || prepared.final_use_binding() != &profile.final_use
                || prepared.selection_observation_digest().to_string() != profile.selection
            {
                return Err(invalid("original Root initial preparation changed"));
            }
            let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
            let journal = CellGenerationJournalV2::open_guarded(
                target.file,
                target.witness,
                target.config,
                target.max_records,
                guard,
            )
            .map_err(invalid)?;
            journal.prepared_checkpoint().map_err(invalid)?;
            let observed = observer.observe().map_err(invalid)?;
            if !observed.is_genesis() || observed.owner_binding() != prepared.target() {
                return Err(invalid(
                    "actual initial genesis differs from original Root files",
                ));
            }
            drop(artifacts);
            Ok(PreparedAgentdGenerationInitialV1::from_parts(
                current,
                authorities,
                prepared,
                journal,
                selected,
            ))
        })();
        completed.map_err(crate::root_generation_initial_client::uncertain_after_prepare)
    }

    pub(crate) fn recover_original_initial(
        self,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        files: RootGenerationJournalInputsV1,
    ) -> Result<ReadyAgentdGenerationInitialV1<FileAnchorWitnessStore>, AgentdError> {
        if self.client.mode() != RootGenerationInitialModeV1::Recover {
            return Err(invalid(
                "initial readback requires explicit original recovery",
            ));
        }
        let profile = self.client.profile().clone();
        let observer = self.require_original_target(&files)?;
        let current = Arc::new(NeuronGenerationCurrentOwnerV1::from_original_root_initial(
            self.client,
        )?);
        let retained = current.recover_initial_operation(
            &profile.deployment.operation,
            profile.intent.parse().map_err(invalid)?,
        )?;
        if matches!(
            current.read_initial_operation(&retained)?,
            crate::NeuronGenerationInitialReadbackV1::Prepared
        ) {
            return Err(invalid(
                "original initial publication is pending; no redispatch",
            ));
        }
        observer.observe().map_err(invalid)?;
        crate::recover_agentd_generation_initial_v1(
            current,
            authorities,
            selected,
            open_target(files)?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: profile.deployment.operation,
                intent_digest: profile.intent.parse().map_err(invalid)?,
            },
        )
    }

    fn require_original_target(
        &self,
        files: &RootGenerationJournalInputsV1,
    ) -> Result<CellGenerationJournalObserverV1, AgentdError> {
        let profile = self.client.profile();
        let deployment = crate::HostGenerationInitialDeploymentV1::new(
            profile.deployment.operation.clone(),
            &files.config,
        )?;
        if deployment != profile.deployment || files.witness.metadata()?.len() == 0 {
            return Err(invalid(
                "original target context or initialized witness missing",
            ));
        }
        let observer = CellGenerationJournalObserverV1::from_original_files(
            files.journal.try_clone()?,
            files.witness.try_clone()?,
            files.config.clone(),
        )
        .map_err(invalid)?;
        if observer.files_binding().to_string() != profile.target_files
            || observer.owner_binding() != &profile.deployment.target
        {
            return Err(invalid("original target inode pair differs from Root"));
        }
        Ok(observer)
    }
}

fn open_target(
    files: RootGenerationJournalInputsV1,
) -> Result<AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>, AgentdError> {
    if files.witness.metadata()?.len() == 0 {
        return Err(invalid(
            "initial witness recovery cannot initialize absence",
        ));
    }
    let witness = FileAnchorWitnessStore::open(
        files.witness,
        files.config.witness_scope,
        files.config.witness_generation,
        files.config.witness_records,
    )
    .map_err(invalid)?;
    Ok(AgentdGenerationUpdateTargetV1 {
        file: files.journal,
        witness,
        config: files.config.generation,
        max_records: files.config.journal_records,
    })
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}
