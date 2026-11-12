//! Same-process Version framing only. Commands still enter the actual host;
//! no fixture constructs a phase, grant, signed cut or publication result.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitRetainedVersionClientV1;
use crate::OriginalCircuitEvaluatedVersionProgressV1 as Progress;
use super::super::super::super::RetainedVersionOriginV1;
use crate::learning_iteration_evidence_client::command_test_support;

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            // SAFETY: only the live test process is admitted by this fixture.
            peer: HostIssuerPeer { uid: unsafe { libc::geteuid() }, pid: std::process::id() },
            timeout: Duration::from_secs(30),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        }, command_test_support::pidfd()?,
    )?)
}

impl OriginalCircuitRetainedVersionHostV1 {
    pub(crate) fn original_evaluated_version_fixture_client(
        self: Arc<Self>,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> anyhow::Result<(OriginalCircuitRetainedVersionClientV1, std::thread::JoinHandle<Result<u64, Error>>)> {
        let (consumer, provider) = UnixStream::pair()?;
        let client = match self.origin {
            RetainedVersionOriginV1::Fresh => OriginalCircuitRetainedVersionClientV1::bind_original_evaluated_stage_channel(
                channel(consumer)?, material, dataset, training, evaluation,
            ),
            RetainedVersionOriginV1::Recovered => OriginalCircuitRetainedVersionClientV1::recover_original_evaluated_stage_channel(
                channel(consumer)?, material, dataset, training, evaluation,
            ),
        }?;
        let mut server = channel(provider)?;
        let permit = Arc::clone(&self.connections).try_acquire_owned()?;
        let peer = std::thread::spawn(move || {
            let _permit = permit;
            for request_id in 1..=128 {
                self.require_lifetime()?;
                let mut failure = None;
                let exchanged = server.exchange(|bytes| self.command_response(bytes, request_id).map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::InvalidRequest
                }));
                match exchanged {
                    Ok(true) => {}
                    Ok(false) => return Ok(request_id - 1),
                    Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
                }
            }
            Err(Error::Unavailable)
        });
        Ok((client, peer))
    }

    /// Exercise the codec with the actual already-bound four-cut. Corrupt
    /// correlation and state values are attack inputs, never original evidence.
    pub(crate) async fn verify_original_progress_protocol_fixture(
        self: Arc<Self>,
    ) -> anyhow::Result<Progress> {
        tokio::task::spawn_blocking(move || {
            let (progress, full_read) = {
                let state = self.state.try_lock().map_err(|_| Error::Busy)?;
                let cut = state.cut.as_ref().ok_or(Error::ReadbackRequired)?;
                (VersionRequest::publication_progress(cut, 1)?, VersionRequest::new(cut, 1, wire::Action::Readback))
            };
            let request = progress.encode()?;
            anyhow::ensure!(serde_json::from_slice::<wire::Request>(&request).is_err(), "legacy request accepted evaluated progress");
            anyhow::ensure!(progress.action().is_err(), "progress became a full-readback action");
            let response = self.command_response(&request, 1)?;
            anyhow::ensure!(progress.decode_response(&response).is_err(), "progress became original readback");
            anyhow::ensure!(full_read.decode_progress_response(&response).is_err(), "readback accepted progress response");
            for field in ["purpose", "initial_binding", "binding", "operation_id", "evaluation_head", "action"] {
                let mut bad: serde_json::Value = serde_json::from_slice(&request)?;
                bad[field] = serde_json::json!("changed-original-correlation");
                anyhow::ensure!(self.command_response(&serde_json::to_vec(&bad)?, 1).is_err(), "changed request {field} accepted");
                let mut bad: serde_json::Value = serde_json::from_slice(&response)?;
                bad["request"][field] = serde_json::json!("changed-original-correlation");
                anyhow::ensure!(progress.decode_progress_response(&serde_json::to_vec(&bad)?).is_err(), "changed response {field} accepted");
            }
            for request_id in [0, 2, 129] {
                let mut bad: serde_json::Value = serde_json::from_slice(&request)?;
                bad["request_id"] = serde_json::json!(request_id);
                anyhow::ensure!(self.command_response(&serde_json::to_vec(&bad)?, 1).is_err(), "changed request id accepted");
            }
            for state in ["prepared", "installed"] {
                let mut bad: serde_json::Value = serde_json::from_slice(&response)?;
                bad["result"] = serde_json::json!({"state":state,"intent":"not-an-authority"});
                anyhow::ensure!(progress.decode_progress_response(&serde_json::to_vec(&bad)?).is_err(), "publication state accepted as progress");
            }
            let result = progress.decode_progress_response(&response)?.decode()?;
            Ok::<_, anyhow::Error>(result)
        }).await?
    }
}
