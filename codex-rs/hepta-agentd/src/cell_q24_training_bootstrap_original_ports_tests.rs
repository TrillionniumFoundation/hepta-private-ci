//! Same-process adapters to the actual deferred Trainer. The initial channels
//! are created before Material/T completion and never return canned evidence.
use super::super::connection;
pub(crate) use super::super::connection::recovered_peer;
use super::super::readonly;
use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use std::thread::JoinHandle;
use std::time::Duration;

pub(crate) fn command<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingCommandConnectionV1,
    JoinHandle<Result<u64, Error>>,
)> {
    let (initial, mut channel) = connection::fresh_peer(material, Duration::from_secs(300))?;
    let thread = std::thread::spawn(move || owner.serve_command_channel(&mut channel));
    Ok((initial, thread))
}

pub(crate) fn readonly<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingReadbackConnectionV1,
    JoinHandle<Result<u64, Error>>,
)> {
    let (initial, mut channel) =
        readonly::test_support::connection(material, Duration::from_secs(300))?;
    let thread =
        std::thread::spawn(move || owner.serve_original_training_readback_channel(&mut channel));
    Ok((initial, thread))
}

pub(crate) fn readonly_channel(
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingReadbackConnectionV1,
    HostAuthorityPeerChannel,
)> {
    readonly::test_support::connection(material, Duration::from_secs(300))
}

/// A transport fault after the second actual original read. The original
/// Generator never re-signs: only this explicit test peer changes its reply.
pub(crate) fn renew_second_actual_read<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
    expected: crate::OriginalCellQ24TrainingCommandReceiptV1,
) -> JoinHandle<anyhow::Result<u64>> {
    use super::super::wire;
    use crate::learning_iteration_evidence_client::wire as evidence_wire;
    use codex_hepta_contracts::HostIssuerTransportError;
    use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
    use ed25519_dalek::Signer;
    std::thread::spawn(move || {
        for request_id in 1..=128 {
            if !channel.exchange(|bytes| {
                let actual = owner
                    .original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: wire::Response = serde_json::from_slice(&actual)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if request_id == 2 {
                    let wire::CommandResult::Completed { snapshot, evidence } = response.result
                    else {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    };
                    let mut changed = evidence
                        .decode()
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if changed != *expected.attestation() {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    }
                    changed.expires_at = changed
                        .expires_at
                        .checked_add(1)
                        .ok_or(HostIssuerTransportError::InvalidRequest)?;
                    changed.signature = SigningKey::from_bytes(&[41; 32])
                        .sign(&changed.signing_bytes())
                        .to_bytes();
                    let payload = learning_iteration_receipt_signing_bytes_v1(expected.receipt())
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    owner
                        .config
                        .material
                        .verifier
                        .verify(
                            LearningEvidenceRoleV1::Generator,
                            &changed,
                            &payload,
                            now().map_err(|_| HostIssuerTransportError::InvalidRequest)?,
                        )
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    response.result = wire::CommandResult::Completed {
                        snapshot,
                        evidence: evidence_wire::Evidence::from_original(&changed),
                    };
                }
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        anyhow::bail!("bounded original Trainer renewal fault")
    })
}

/// Only test transport custody: one Candidate readback and two Training
/// evidence channels, all bound to the same actual Bootstrap before D/T.
/// Shutdown makes every error/drop path terminal; it does not cancel an
/// already admitted original owner operation or fabricate a successful count.
pub(crate) struct OriginalTrainingPeers {
    candidate: Option<crate::OriginalCellQ24TrainingCommandConnectionV1>,
    trainers: [Option<crate::OriginalCellQ24TrainingReadbackConnectionV1>; 2],
    shutdown: Vec<std::os::unix::net::UnixStream>,
    servers: Vec<JoinHandle<Result<u64, Error>>>,
}

impl OriginalTrainingPeers {
    pub(crate) fn new<
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
    >(
        owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
        material: OriginalCellQ24MaterialReceiptConfigV1,
    ) -> anyhow::Result<Self> {
        let lifetime = Duration::from_secs(300);
        let (candidate, mut candidate_server, close_candidate) =
            crate::OriginalCellQ24TrainingCommandConnectionV1::fixture_peer_with_shutdown(
                material.clone(),
                lifetime,
            )?;
        let (primary, mut primary_server, close_primary) =
            crate::OriginalCellQ24TrainingReadbackConnectionV1::fixture_connection_with_shutdown(
                material.clone(),
                lifetime,
            )?;
        let (retention, mut retention_server, close_retention) =
            crate::OriginalCellQ24TrainingReadbackConnectionV1::fixture_connection_with_shutdown(
                material, lifetime,
            )?;
        let mut result = Self {
            candidate: Some(candidate),
            trainers: [Some(primary), Some(retention)],
            shutdown: vec![close_candidate, close_primary, close_retention],
            servers: Vec::new(),
        };
        let candidate_owner = Arc::clone(&owner);
        result.servers.push(std::thread::spawn(move || {
            candidate_owner.serve_candidate_material_channel(&mut candidate_server)
        }));
        let primary_owner = Arc::clone(&owner);
        result.servers.push(std::thread::spawn(move || {
            primary_owner.serve_original_training_readback_channel(&mut primary_server)
        }));
        result.servers.push(std::thread::spawn(move || {
            owner.serve_original_training_readback_channel(&mut retention_server)
        }));
        Ok(result)
    }

    pub(crate) fn take_candidate(
        &mut self,
    ) -> anyhow::Result<crate::OriginalCellQ24TrainingCommandConnectionV1> {
        self.candidate
            .take()
            .ok_or_else(|| anyhow::anyhow!("one original Candidate connection"))
    }

    pub(crate) fn take_trainers(
        &mut self,
    ) -> anyhow::Result<[crate::OriginalCellQ24TrainingReadbackConnectionV1; 2]> {
        let first = self.trainers[0]
            .take()
            .ok_or_else(|| anyhow::anyhow!("one original primary Trainer connection"))?;
        let second = self.trainers[1]
            .take()
            .ok_or_else(|| anyhow::anyhow!("one original retention Trainer connection"))?;
        Ok([first, second])
    }

    fn close(&mut self) {
        for stream in &self.shutdown {
            let _ = stream.shutdown(std::net::Shutdown::Both);
        }
        drop(self.candidate.take());
        for client in &mut self.trainers {
            drop(client.take());
        }
    }

    pub(crate) fn finish(mut self) -> anyhow::Result<[u64; 3]> {
        self.close();
        let mut counts = Vec::new();
        let mut failure = None;
        for server in self.servers.drain(..) {
            match server.join() {
                Ok(Ok(count)) => counts.push(count),
                Ok(Err(error)) => {
                    if failure.is_none() {
                        failure = Some(anyhow::Error::from(error));
                    }
                }
                Err(_) => {
                    if failure.is_none() {
                        failure = Some(anyhow::anyhow!("original Trainer peer panicked"));
                    }
                }
            }
        }
        if let Some(error) = failure {
            return Err(error);
        }
        counts
            .try_into()
            .map_err(|_| anyhow::anyhow!("all three actual Trainer peers joined"))
    }
}

impl Drop for OriginalTrainingPeers {
    fn drop(&mut self) {
        self.close();
        // Best-effort error teardown still joins every owned thread. Only the
        // explicit finish path can return and assert original handler results.
        for server in self.servers.drain(..) {
            let _ = server.join();
        }
    }
}

/// One test-only observation of actual Training completion and Candidate
/// material. Call from the fixture's existing bounded blocking lane: the
/// original SourceBound read performs real synchronous I/O. This helper adds
/// no wait loop or deadline and consumes none of the three pre-held clients.
/// Ready alone is not completion. After Some, subsequent B/channel operations
/// must still perform their own original live reads; this is no future grant.
pub(crate) fn completed_candidate_training<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: &Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
) -> Result<Option<crate::OriginalCellQ24TrainingCommandReceiptV1>, Error> {
    let original = {
        let state = match owner.state.try_lock() {
            Ok(state) => state,
            Err(std::sync::TryLockError::WouldBlock) => return Ok(None),
            Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Busy),
        };
        match &*state {
            State::Awaiting(_) | State::Starting => return Ok(None),
            State::Fenced => return Err(Error::Uncertain),
            State::Ready(original) => Arc::clone(original),
        }
    };
    // Release the Bootstrap state lock before the original Stage lane I/O.
    OriginalCellQ24TrainingCommandOwnerV1::fixture_completed_candidate_receipt(&original)
        .map_err(Error::from)
}

impl OriginalTrainingPeers {
    /// Same original handlers, with only one purpose-bound evidence channel
    /// for the primary and retention members' existing local Arc sharing.
    /// This private transport fixture is not a public-permit admission test.
    pub(crate) fn new_shared<
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
    >(
        owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
        material: OriginalCellQ24MaterialReceiptConfigV1,
    ) -> anyhow::Result<Self> {
        let lifetime = Duration::from_secs(300);
        let (candidate, mut candidate_server, close_candidate) =
            crate::OriginalCellQ24TrainingCommandConnectionV1::fixture_peer_with_shutdown(
                material.clone(),
                lifetime,
            )?;
        let (trainer, mut trainer_server, close_trainer) =
            crate::OriginalCellQ24TrainingReadbackConnectionV1::fixture_connection_with_shutdown(
                material, lifetime,
            )?;
        let mut result = Self {
            candidate: Some(candidate),
            trainers: [Some(trainer), None],
            shutdown: vec![close_candidate, close_trainer],
            servers: Vec::new(),
        };
        let candidate_owner = Arc::clone(&owner);
        result.servers.push(std::thread::spawn(move || {
            candidate_owner.serve_candidate_material_channel(&mut candidate_server)
        }));
        result.servers.push(std::thread::spawn(move || {
            owner.serve_original_training_readback_channel(&mut trainer_server)
        }));
        Ok(result)
    }

    pub(crate) fn take_shared_trainer(
        &mut self,
    ) -> anyhow::Result<crate::OriginalCellQ24TrainingReadbackConnectionV1> {
        anyhow::ensure!(
            self.servers.len() == 2 && self.trainers[1].is_none(),
            "one original shared Trainer transport fixture"
        );
        self.trainers[0]
            .take()
            .ok_or_else(|| anyhow::anyhow!("one original shared Trainer connection"))
    }

    pub(crate) fn finish_shared(mut self) -> anyhow::Result<[u64; 2]> {
        self.close();
        let mut counts = Vec::new();
        let mut failure = None;
        for server in self.servers.drain(..) {
            match server.join() {
                Ok(Ok(count)) => counts.push(count),
                Ok(Err(error)) => {
                    if failure.is_none() {
                        failure = Some(anyhow::Error::from(error));
                    }
                }
                Err(_) => {
                    if failure.is_none() {
                        failure = Some(anyhow::anyhow!("original Trainer peer panicked"));
                    }
                }
            }
        }
        if let Some(error) = failure {
            return Err(error);
        }
        counts
            .try_into()
            .map_err(|_| anyhow::anyhow!("both actual Trainer peers joined"))
    }
}
