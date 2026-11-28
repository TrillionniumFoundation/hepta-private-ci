//! Assemble one learner from the original installed product owner and a Ledger
//! already held by its embedding. This module opens no store and issues no grant.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::workspace_binding_digest;
use codex_hepta_types::StableId;

use super::AgentdProductionWriterHost;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdSharedReplayHostV1;
use crate::AgentdTerminalLearningOwnerV1;
use crate::PairedTerminalCompositionV1;
use crate::PairedTerminalEvaluatorInboxV1;
use crate::TerminalLearningHandleV1;
use crate::TerminalLearningRuntimeBootstrapV1;
use crate::terminal_learning_channel_v1;

impl AgentdProductionWriterHost {
    #[allow(clippy::too_many_arguments)]
    async fn terminal_bootstrap_from_original(
        &self,
        config: &AgentdConfig,
        ledger: Arc<Mutex<LedgerWriter>>,
        producer: StableId,
        parameter_scope: String,
        maximum_jobs: usize,
        capacity: usize,
        composition: PairedTerminalCompositionV1,
        end: tokio::time::Instant,
    ) -> Result<
        (
            TerminalLearningHandleV1,
            TerminalLearningRuntimeBootstrapV1,
            PairedTerminalEvaluatorInboxV1,
        ),
        AgentdError,
    > {
        let installed = config
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        if !std::ptr::eq(installed.as_ref(), self)
            || self.spawn_generation != config.identity().spawn_generation
            || self.writer.owner_agent_id() != &config.identity().agent_id
            || self.mutation.is_none()
        {
            return Err(AgentdError::GenerationFenced(
                "terminal learner requires the same installed production owner".into(),
            ));
        }
        let remaining = end.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || remaining > Duration::from_secs(/*secs*/ 30) {
            return Err(AgentdError::Invalid(
                "bounded original assembly deadline required".into(),
            ));
        }
        tokio::time::timeout_at(end, async {
            self.writer.verify_current_authority().await?;
            let source = self
                .cognitive_runtime
                .available_store()
                .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
            let consumer = FederationConsumerAccess::new(
                config.identity().agent_id.clone(),
                workspace_binding_digest(&config.identity().workspace),
            );
            let replay = AgentdSharedReplayHostV1::from_original_production_owner(
                Arc::clone(source),
                consumer,
                parameter_scope,
                config.identity().agent_id.clone(),
                Arc::clone(&self.writer),
            )
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
            let owner = AgentdTerminalLearningOwnerV1::new(
                config.identity().agent_id.clone(),
                producer,
                ledger,
                Arc::new(replay),
                maximum_jobs,
            )
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
            let (handle, bootstrap) = terminal_learning_channel_v1(
                config.identity().agent_id.clone(),
                self.spawn_generation,
                owner,
                capacity,
            )?;
            let (bootstrap, inbox) = bootstrap.with_original_paired_composition(composition)?;
            self.writer.verify_current_authority().await?;
            if tokio::time::Instant::now() >= end {
                return Err(AgentdError::Invalid(
                    "original terminal assembly deadline expired".into(),
                ));
            }
            self.terminal_owner_claimed
                .compare_exchange(
                    /*current*/ false,
                    /*new*/ true,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                )
                .map_err(|_| {
                    AgentdError::Invalid("original terminal owner already assembled".into())
                })?;
            Ok((handle, bootstrap, inbox))
        })
        .await
        .map_err(|_| AgentdError::Invalid("original terminal assembly deadline expired".into()))?
    }
}

impl AgentdConfig {
    /// Explicit embedding composition after its real production host is installed.
    /// The caller retains the existing activated Ledger; no disk path, raw trace,
    /// local JSON or alleged consent can substitute for that owned object.
    #[allow(clippy::too_many_arguments)]
    pub async fn with_original_terminal_learning_owners_v1(
        self,
        ledger: Arc<Mutex<LedgerWriter>>,
        producer: StableId,
        parameter_scope: String,
        maximum_jobs: usize,
        capacity: usize,
        composition: PairedTerminalCompositionV1,
        end: tokio::time::Instant,
    ) -> Result<
        (
            Self,
            TerminalLearningHandleV1,
            PairedTerminalEvaluatorInboxV1,
        ),
        AgentdError,
    > {
        self.require_terminal_learning_unconfigured()?;
        if !(1..=64).contains(&capacity) {
            return Err(AgentdError::Invalid(
                "bounded terminal queue required".into(),
            ));
        }
        let host = self
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        let (handle, bootstrap, inbox) = host
            .terminal_bootstrap_from_original(
                &self,
                ledger,
                producer,
                parameter_scope,
                maximum_jobs,
                capacity,
                composition,
                end,
            )
            .await?;
        Ok((
            self.with_terminal_learning_bootstrap(bootstrap)?,
            handle,
            inbox,
        ))
    }
}
