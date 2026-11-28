//! Consume a distinct sealed purpose from the same original Root and connect
//! after the real UID drop. Public plan bytes never grant a material read.

use std::io::Read;
use std::io::Seek;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdPairedMaterialClient;
use crate::AgentdRootProductionInputs;
use crate::HOST_AUTHORITY_PAIRED_TRAINING_BOOTSTRAP_V1;
use crate::HostAuthorityPairedTrainingBootstrapV1;
use crate::PairedTrainingPlanV1;
use crate::RootPairedTrainingHandoffV1;
use crate::paired_preparation::material_protocol::FRAME_BOUND;
use crate::paired_preparation::training::consumer::OriginalPairedTrainingDelivery;

pub(crate) struct AgentdRootPairedTrainingInputsV1 {
    plan: PairedTrainingPlanV1,
    client: AgentdPairedMaterialClient,
    identity: AgentdIdentity,
}

impl RootPairedTrainingHandoffV1 {
    pub(crate) async fn connect_original_paired_training(
        mut self,
        production: &AgentdRootProductionInputs,
        expected: &AgentdIdentity,
        startup_deadline: Instant,
        session_end: Instant,
    ) -> Result<AgentdRootPairedTrainingInputsV1, AgentdError> {
        if remaining(startup_deadline)? > Duration::from_secs(30)
            || remaining(session_end)? > Duration::from_secs(300)
        {
            return Err(refused(
                "bounded original paired startup and session required",
            ));
        }
        let length = self.bootstrap.metadata()?.len();
        if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("paired training descriptor exceeds its bound"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, length)?;
        self.bootstrap.rewind()?;
        let mut bytes = Vec::with_capacity(length as usize);
        self.bootstrap
            .by_ref()
            .take(length + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, length)?;
        if bytes.len() as u64 != length {
            return Err(refused("paired training descriptor length changed"));
        }
        let bundle: HostAuthorityPairedTrainingBootstrapV1 = serde_json::from_slice(&bytes)?;
        let plan = validate_binding(&bundle, &production.bootstrap, expected, self.root_pid)?;
        let paths = &production.bootstrap.sockets;
        // SAFETY: getegid only samples the current, already dropped credentials.
        crate::authority_host_runtime::validate_lane_paths(
            &[
                &paths.observation,
                &paths.issuer,
                &paths.checkpoint,
                &paths.device_frontier,
                &paths.notes_frontier,
                &bundle.socket_path,
            ],
            unsafe { libc::getegid() },
        )?;
        let connect_end = (Instant::now() + Duration::from_millis(500))
            .min(startup_deadline)
            .min(session_end);
        let stream = tokio::time::timeout_at(
            tokio::time::Instant::from_std(connect_end),
            tokio::net::UnixStream::connect(&bundle.socket_path),
        )
        .await
        .map_err(|_| refused("original paired training connection deadline elapsed"))??;
        let client = AgentdPairedMaterialClient::from_original_root(
            plan.preparation.clone(),
            plan.manifest.clone(),
            stream.into_std()?,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: 0,
                    pid: bundle.root.pid,
                },
                timeout: Duration::from_millis(500),
                lifetime: remaining(session_end)?,
                request_bound: FRAME_BOUND,
                response_bound: FRAME_BOUND,
            },
            self.root_pidfd,
        )?;
        remaining(startup_deadline)?;
        Ok(AgentdRootPairedTrainingInputsV1 {
            plan,
            client,
            identity: expected.clone(),
        })
    }
}

impl AgentdRootPairedTrainingInputsV1 {
    /// Compose only with an already installed real terminal owner and its live
    /// Evaluator exchange. The raw Root plan and canonical pins stay distinct.
    pub(crate) fn install_original_terminal_consumer(
        self,
        mut config: AgentdConfig,
        records: crate::PairedRecordPinsV1,
        session_end: Instant,
    ) -> Result<AgentdConfig, AgentdError> {
        let mut owner = config
            .take_terminal_learning_bootstrap()
            .ok_or_else(|| refused("original terminal owner factory has not been installed"))?;
        owner.require_identity(config.identity())?;
        owner.require_original_paired_policy(&self.plan, records)?;
        let (config, delivery) = self.install_original_consumer(config)?;
        owner.install_original_paired_delivery(delivery, session_end)?;
        config.with_terminal_learning_bootstrap(owner)
    }

    pub(crate) fn install_original_consumer(
        self,
        config: AgentdConfig,
    ) -> Result<
        (
            AgentdConfig,
            tokio::sync::oneshot::Receiver<OriginalPairedTrainingDelivery>,
        ),
        AgentdError,
    > {
        if config.identity() != &self.identity {
            return Err(refused(
                "paired training capability belongs to another process owner",
            ));
        }
        config.with_original_paired_training_consumer(self.plan, self.client)
    }
}

fn validate_binding(
    bundle: &HostAuthorityPairedTrainingBootstrapV1,
    original: &crate::HostAuthorityPublicBootstrapV1,
    expected: &AgentdIdentity,
    root_pid: u32,
) -> Result<PairedTrainingPlanV1, AgentdError> {
    let socket = original
        .sockets
        .observation
        .parent()
        .ok_or_else(|| refused("original Root socket parent missing"))?
        .join("paired-training-v1.sock");
    let proof = original.writer_proof.sha256()?;
    if bundle.schema_version != 1
        || bundle.operation != HOST_AUTHORITY_PAIRED_TRAINING_BOOTSTRAP_V1
        || bundle.root != original.root
        || bundle.consumer != original.consumer
        || bundle.root.pid != root_pid
        || bundle.root.uid != 0
        || bundle.registered_identity.identity()? != *expected
        || original.registered_identity.identity()? != *expected
        || bundle.writer_proof_digest != proof.as_str()
        || bundle.socket_path != socket
    {
        return Err(refused(
            "paired training handoff differs from the original Root launch",
        ));
    }
    Ok(bundle
        .profile
        .require_binding(expected, proof.as_str())?
        .training)
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| refused("original paired training lifetime expired"))
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

#[cfg(test)]
#[path = "root_production_paired_inputs_tests.rs"]
mod tests;
