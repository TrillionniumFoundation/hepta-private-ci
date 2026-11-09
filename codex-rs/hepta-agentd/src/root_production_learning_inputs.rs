//! Consume a dedicated learning capability from the same original Root as
//! the mandatory production lanes. Public profile bytes never create an owner.

use std::io::Read;
use std::io::Seek;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdLearningCheckpointClientV1;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootProductionInputs;
use crate::HostAuthorityLearningBootstrapV1;
use crate::LearningIterationHandleV1;
use crate::LearningIterationRuntimeBootstrapV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::RootLearningHandoffV1;

/// One retained original learning connection and its immutable operation.
/// Receiving it establishes checkpoint access only. Real stage owners and
/// pinned evidence trust must still be supplied before any worker can start.
pub struct AgentdRootLearningInputsV1 {
    client: AgentdLearningCheckpointClientV1,
    initial: LearningIterationSnapshotV1,
    identity: AgentdIdentity,
    scope: Option<FrozenLearningScopeV2>,
}

impl RootLearningHandoffV1 {
    pub(crate) async fn connect(
        mut self,
        production: &AgentdRootProductionInputs,
        expected: &AgentdIdentity,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<AgentdRootLearningInputsV1, AgentdError> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(refused("bounded original learning timing required"));
        }
        let end = Instant::now() + lifetime;
        let length = self.bootstrap.metadata()?.len();
        if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("learning descriptor exceeds its bound"));
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
            return Err(refused("learning descriptor length changed"));
        }
        let bundle: HostAuthorityLearningBootstrapV1 = serde_json::from_slice(&bytes)?;
        let initial = validate_binding(&bundle, &production.bootstrap, expected, self.root_pid)?;
        let scope = bundle.decode_frozen_scope(&initial)?;
        let paths = &production.bootstrap.sockets;
        // SAFETY: getegid only observes this process's current credentials.
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
        let stream = tokio::time::timeout(
            timeout.min(remaining(end)?),
            tokio::net::UnixStream::connect(&bundle.socket_path),
        )
        .await
        .map_err(|_| refused("learning connection deadline elapsed"))??;
        let peer = AgentdRootAuthorityPeer {
            pid: bundle.root.pid,
            boot_id: bundle.root.boot_id,
            process_start_ticks: bundle.root.process_start_ticks,
        };
        let stream = stream.into_std()?;
        let client = match &scope {
            Some(scope) => AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2(
                stream,
                peer,
                self.root_pidfd,
                initial.clone(),
                scope.clone(),
                timeout,
                remaining(end)?,
            ),
            None => AgentdLearningCheckpointClientV1::from_root_stream(
                stream,
                peer,
                self.root_pidfd,
                initial.clone(),
                timeout,
                remaining(end)?,
            ),
        }
        .map_err(|error| refused(format!("learning Root transport: {error}")))?;
        // Confirm the actual registered CURRENT through its live writer before
        // retaining the capability. This observation is not a stage attestation.
        client
            .restore(&initial.request)
            .await
            .map_err(|error| refused(format!("learning original CURRENT: {error}")))?;
        remaining(end)?;
        Ok(AgentdRootLearningInputsV1 {
            client,
            initial,
            identity: expected.clone(),
            scope,
        })
    }
}

fn validate_binding(
    bundle: &HostAuthorityLearningBootstrapV1,
    original: &crate::HostAuthorityPublicBootstrapV1,
    expected: &AgentdIdentity,
    root_pid: u32,
) -> Result<LearningIterationSnapshotV1, AgentdError> {
    let socket = original
        .sockets
        .observation
        .parent()
        .ok_or_else(|| refused("original Root socket parent missing"))?
        .join("learning-checkpoint-v1.sock");
    if bundle.root != original.root
        || bundle.consumer != original.consumer
        || bundle.root.pid != root_pid
        || bundle.root.uid != 0
        || bundle.registered_identity.identity()? != *expected
        || original.registered_identity.identity()? != *expected
        || bundle.writer_proof_digest != original.writer_proof.sha256()?.as_str()
        || bundle.socket_path != socket
    {
        return Err(refused(
            "learning handoff differs from the original Root launch",
        ));
    }
    let initial = bundle.decode_initial()?;
    let _scope = bundle.decode_frozen_scope(&initial)?;
    if initial.request.agent_id.as_str() != expected.agent_id.as_str() {
        return Err(refused("learning operation belongs to another agent"));
    }
    Ok(initial)
}

impl AgentdRootLearningInputsV1 {
    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if &self.identity != identity {
            return Err(refused(
                "learning capability belongs to another process owner",
            ));
        }
        Ok(())
    }

    /// Consume this original capability beside actual stage owners. The
    /// request, owner roles, deadline and evidence trust cannot be replaced.
    pub fn into_learning_runtime(
        self,
        stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
        verifier: LearningEvidenceVerifierV1,
        capacity: usize,
    ) -> Result<
        (
            LearningIterationHandleV1,
            LearningIterationRuntimeBootstrapV1,
        ),
        AgentdError,
    > {
        let ports = self.client.with_stage_owners(stages);
        let (handle, bootstrap) = match self.scope {
            Some(scope) => crate::learning_iteration_channel_scoped_v2(
                self.identity.agent_id,
                self.identity.spawn_generation,
                self.initial.owners,
                ports,
                verifier,
                capacity,
                scope,
            ),
            None => crate::learning_iteration_channel_v1(
                self.identity.agent_id,
                self.identity.spawn_generation,
                self.initial.owners,
                ports,
                verifier,
                capacity,
            ),
        }?;
        Ok((
            handle,
            bootstrap.with_circuit_learning_delivery(self.initial.request)?,
        ))
    }
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| refused("original learning lifetime expired"))
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

#[cfg(test)]
#[path = "root_production_learning_inputs_tests.rs"]
mod tests;
