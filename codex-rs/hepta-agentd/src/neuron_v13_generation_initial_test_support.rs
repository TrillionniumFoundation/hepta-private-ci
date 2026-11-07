//! Initial Prepared custody is an actual private file CAS, not an OS-root
//! deployment claim. Every later publication, worker FD check and runtime
//! transition uses the production implementation and original test issuers.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::super::super::support::Fixture as HostFixture;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::neuron_generation_current::test_support::Fixture as CurrentFixture;
use crate::neuron_generation_initial::PreparedAgentdGenerationInitialV1;
use crate::neuron_generation_initial::validate_initial_target;
use crate::neuron_generation_process_identity_digest_v1;
use crate::neuron_generation_service::spawn_neuron_generation_service;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_update_cold::AgentdGenerationUpdatePredecessorFilesV1;
use crate::neuron_v13_generation_bootstrap::V13GenerationOwnerModeV1;
use crate::neuron_v13_generation_initial::PreparedAgentdV13GenerationInitialV1;
use crate::neuron_v13_generation_initial::ReadyAgentdV13GenerationInitialV1;
use crate::neuron_v13_generation_initial::recover_agentd_v13_generation_initial_v1;
use crate::neuron_v13_generation_update::AgentdV13GenerationUpdateInputsV1;

pub(super) const OPERATION: &str = "initial-v13-publication";

pub(super) struct Fixture {
    pub(super) host: HostFixture,
    pub(super) current: CurrentFixture,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
        let host = HostFixture::new()?;
        let current = CurrentFixture::new_initial(host.config.generation.clone(), OPERATION)?;
        Ok(Self { host, current })
    }

    pub(super) fn inputs(&self) -> anyhow::Result<AgentdV13GenerationUpdateInputsV1<'_>> {
        Ok(AgentdV13GenerationUpdateInputsV1 {
            identity: &self.host.identity,
            config: self.host.config.clone(),
            files: self.host.files()?,
            prepared: &self.host.prepared,
        })
    }

    pub(super) fn prepare(&self) -> anyhow::Result<PreparedAgentdV13GenerationInitialV1> {
        let authorities = self.current.authorities()?;
        let mut selected = self.current.selection()?;
        let inputs = self.inputs()?;
        inputs.revalidate_selection(&authorities, &mut selected)?;
        let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
        let binding = validate_initial_target(&selected, &target)?;
        let prepared = self.current.initial_prepared(OPERATION)?;
        anyhow::ensure!(
            &binding == prepared.target(),
            "actual initial file binding differs"
        );
        anyhow::ensure!(
            target.file.metadata()?.len() == 0,
            "initial target is not empty"
        );
        anyhow::ensure!(
            target.witness.current()?.is_none(),
            "initial witness is not empty"
        );
        let guard: Arc<dyn CellGenerationCurrentV1> = self.current.current.clone();
        let journal = CellGenerationJournalV2::open_guarded(
            target.file,
            target.witness,
            target.config,
            target.max_records,
            guard,
        )?;
        journal.prepared_checkpoint()?;
        // Only RootAuthorityDirectory construction is replaced by the private
        // fixture's create-only FileCAS; these are the same sealed assembly
        // constructors used after the production root initializer succeeds.
        let initial = PreparedAgentdGenerationInitialV1::from_parts(
            self.current.current.clone(),
            authorities,
            prepared,
            journal,
            selected,
        );
        Ok(PreparedAgentdV13GenerationInitialV1::from_parts(
            initial, backend,
        ))
    }

    pub(super) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.host.owner_bytes()?;
        bytes.push(self.current.bytes("current.json")?);
        bytes.push(self.current.bytes("final-use-frontier.json")?);
        Ok(bytes)
    }

    pub(super) fn options(&self) -> AgentdGenerationUpdateRuntimeOptionsV1 {
        AgentdGenerationUpdateRuntimeOptionsV1 {
            queue_capacity: self.host.config.queue_capacity,
            control_endpoint: false,
        }
    }

    pub(super) async fn recover(
        &self,
        intent_digest: Digest32,
    ) -> anyhow::Result<ReadyAgentdV13GenerationInitialV1> {
        timeout(Duration::from_secs(5), async {
            loop {
                match recover_agentd_v13_generation_initial_v1(
                    self.current.reopen_current()?,
                    self.current.authorities()?,
                    self.current.selection()?,
                    self.inputs()?,
                    AgentdGenerationUpdateRecoveryV1 {
                        operation_id: OPERATION.into(),
                        intent_digest,
                    },
                ) {
                    Ok(ready) => return Ok(ready),
                    Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                        sleep(Duration::from_millis(1)).await;
                    }
                    Err(error) => return Err(error.into()),
                }
            }
        })
        .await?
    }

    pub(super) async fn predecessor(
        &self,
    ) -> anyhow::Result<AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>> {
        timeout(Duration::from_secs(5), async {
            loop {
                match self.inputs()?.reopen_predecessor() {
                    Ok(opened) => return Ok::<_, anyhow::Error>(opened),
                    Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                        sleep(Duration::from_millis(1)).await;
                    }
                    Err(error) => return Err(error.into()),
                }
            }
        })
        .await?
    }
}

pub(super) fn next_spawn(host: &mut HostFixture) -> anyhow::Result<()> {
    let starting = host.identity.spawn_generation;
    for (offset, lifecycle) in [
        (1, AgentLifecycle::Draining),
        (2, AgentLifecycle::Stopped),
        (3, AgentLifecycle::Starting),
    ] {
        host.registry.compare_and_transition(
            &host.identity.agent_id,
            starting + offset,
            lifecycle,
        )?;
    }
    host.identity.spawn_generation = starting + 4;
    host.config.expected_identity_digest =
        neuron_generation_process_identity_digest_v1(&host.identity)?;
    Ok(())
}

pub(super) async fn start(
    host: &HostFixture,
    config: &mut AgentdConfig,
) -> anyhow::Result<(RuntimeTasks, Arc<AgentdState>)> {
    host.registry.compare_and_transition(
        &host.identity.agent_id,
        host.identity.spawn_generation,
        AgentLifecycle::Running,
    )?;
    let state = host.state().await?;
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
    let bootstrap = config
        .take_neuron_generation_bootstrap()
        .ok_or_else(|| anyhow::anyhow!("typed initial runtime omitted the ordinary service"))?;
    spawn_neuron_generation_service(&mut tasks, bootstrap, state.clone(), cancellation)?;
    Ok((tasks, state))
}
