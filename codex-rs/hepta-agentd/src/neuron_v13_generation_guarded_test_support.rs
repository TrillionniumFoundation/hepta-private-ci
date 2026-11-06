//! Real file owners and the original invalid-closure V13/Fleet fixture.
//! The predecessor's STOP is synthetic; the successor uses actual Python to
//! reject invalid assets. Neither fixture claims trained inference or adoption.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio_util::sync::CancellationToken;

use super::super::support::Fixture as V13Fixture;
use crate::AgentdConfig;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::neuron_generation_current::test_support::Fixture as CurrentFixture;
use crate::neuron_generation_service::spawn_neuron_generation_service;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeV1;
use crate::neuron_generation_update_cold::AgentdGenerationUpdatePredecessorFilesV1;
use crate::neuron_generation_process_identity_digest_v1;
use crate::neuron_v13_generation_update::AgentdV13GenerationUpdateInputsV1;
use crate::neuron_v13_generation_update::PreparedAgentdV13GenerationUpdateV1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_update_v1;

pub(super) struct Fixture {
    pub(super) host: V13Fixture,
    pub(super) update: CurrentFixture,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
        let host = V13Fixture::new()?;
        let mut old = host.config.generation.clone();
        old.initial.scope.run_id = "previous-v13-task".into();
        old.initial.generation -= 1;
        old.initial.writer_epoch -= 1;
        old.task_digest = Digest32::of_bytes(b"previous synthetic task").into_array();
        old.manifest.bundle_digest = Digest32::of_bytes(b"previous synthetic backend").into_array();
        old.initial.manifest_digest = old.manifest.digest()?;
        let update = CurrentFixture::new_with_target(old, host.config.generation.clone())?;
        drop(update.stopped_old()?);
        Ok(Self { host, update })
    }

    pub(super) fn inputs(&self) -> anyhow::Result<AgentdV13GenerationUpdateInputsV1<'_>> {
        Ok(AgentdV13GenerationUpdateInputsV1 {
            identity: &self.host.identity,
            config: self.host.config.clone(),
            files: self.host.files()?,
            prepared: &self.host.prepared,
        })
    }

    pub(super) fn prepare(
        &self,
        operation: &str,
    ) -> anyhow::Result<PreparedAgentdV13GenerationUpdateV1<FileAnchorWitnessStore>> {
        Ok(prepare_agentd_v13_generation_update_v1(
            self.update.current.clone(),
            self.update.authorities()?,
            self.update.old_journal()?,
            self.update.selection()?,
            self.inputs()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: operation.into(),
            },
        )?)
    }

    pub(super) fn predecessor(
        &self,
    ) -> anyhow::Result<AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>> {
        Ok(AgentdGenerationUpdatePredecessorFilesV1 {
            file: self.update.file("old-journal")?,
            witness: self.update.witness("old-witness", &self.update.old_config)?,
            config: self.update.old_config.clone(),
            max_records: self.host.config.max_records,
        })
    }

    pub(super) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.host.owner_bytes()?;
        for name in [
            "current.json",
            "final-use-frontier.json",
            "old-journal",
            "old-witness",
        ] {
            bytes.push(self.update.bytes(name)?);
        }
        Ok(bytes)
    }

    pub(super) fn options(&self) -> AgentdGenerationUpdateRuntimeOptionsV1 {
        AgentdGenerationUpdateRuntimeOptionsV1 {
            queue_capacity: self.host.config.queue_capacity,
            control_endpoint: false,
        }
    }

    pub(super) async fn start(
        &self,
        runtime: &mut AgentdGenerationUpdateRuntimeV1,
    ) -> anyhow::Result<(RuntimeTasks, Arc<AgentdState>)> {
        self.host.registry.compare_and_transition(
            &self.host.identity.agent_id,
            self.host.identity.spawn_generation,
            AgentLifecycle::Running,
        )?;
        let state = self.host.state().await?;
        let cancellation = CancellationToken::new();
        let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
        let bootstrap = runtime.config.take_neuron_generation_bootstrap()
            .ok_or_else(|| anyhow::anyhow!("typed update omitted its ordinary service"))?;
        spawn_neuron_generation_service(&mut tasks, bootstrap, state.clone(), cancellation)?;
        Ok((tasks, state))
    }

    pub(super) fn next_spawn(&mut self) -> anyhow::Result<()> {
        let starting = self.host.identity.spawn_generation;
        for (offset, lifecycle) in [
            (1, AgentLifecycle::Draining),
            (2, AgentLifecycle::Stopped),
            (3, AgentLifecycle::Starting),
        ] {
            self.host.registry.compare_and_transition(
                &self.host.identity.agent_id, starting + offset, lifecycle,
            )?;
        }
        self.host.identity.spawn_generation = starting + 4;
        self.host.config.expected_identity_digest =
            neuron_generation_process_identity_digest_v1(&self.host.identity)?;
        Ok(())
    }
}

pub(super) fn runtime_config(identity: &AgentdIdentity) -> anyhow::Result<AgentdConfig> {
    Ok(AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    )?)
}
