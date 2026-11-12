//! Same-process transport only; responses come from the actual original S
//! host and journal, with live T/B reads. No static receipt response is used.
//! This does not exercise independent process enrollment or ordinary closure.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::Channel;
use super::super::LearningIterationEvidenceClientV1;
use super::Error;
use super::OriginalCircuitEvaluatedSelectionReadbackOwnerV1;
use crate::learning_iteration_evidence_client::command_test_support;
use crate::root_observation_stream::RootObservationStream;

impl<W: AnchorWitnessStore + Send + 'static, C: AnchorWitnessStore + Send + 'static>
    OriginalCircuitEvaluatedSelectionReadbackOwnerV1<W, C>
{
    pub(crate) fn fixture_reject_wrong_requests(&self) -> anyhow::Result<()> {
        let request = super::wire::Request {
            schema: 1,
            operation: super::wire::OPERATION.into(),
            request_id: 1,
            binding: self.initial_head.to_string(),
            snapshot_head: self.selection.snapshot().head_digest.to_string(),
            operation_id: self.selection.snapshot().request.operation_id.to_string(),
            actor_id: self.selection.snapshot().owners.selector.to_string(),
            predecessor: self.selection.receipt().predecessor.to_string(),
            receipt_digest: self.selection.attestation().payload_digest.to_string(),
        };
        let encoded = serde_json::to_value(request)?;
        for field in [
            "schema",
            "operation",
            "request_id",
            "binding",
            "operation_id",
            "actor_id",
            "predecessor",
            "receipt_digest",
            "snapshot_head",
            "payload",
        ] {
            let mut changed = encoded.clone();
            changed[field] = match field {
                "schema" | "request_id" => serde_json::json!(2),
                "operation" => serde_json::json!("runtime.learning.selection.execute.v1"),
                "snapshot_head" => serde_json::json!("not-a-head"),
                _ => serde_json::json!("not-original"),
            };
            anyhow::ensure!(
                self.evidence_response(&serde_json::to_vec(&changed)?, 1)
                    .is_err(),
                "original read-only S must reject changed {field}",
            );
        }
        Ok(())
    }

    pub(crate) fn fixture_original_client(
        self: &Arc<Self>,
        invalidate_source_after_read: Option<(u64, File)>,
    ) -> anyhow::Result<(
        LearningIterationEvidenceClientV1,
        std::thread::JoinHandle<Result<u64, Error>>,
    )> {
        let (stream, server) = std::os::unix::net::UnixStream::pair()?;
        // SAFETY: inspect only this explicit fixture process's current UID.
        let uid = unsafe { libc::geteuid() };
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            command_test_support::identity()?,
            command_test_support::pidfd()?,
            Duration::from_millis(500),
            Duration::from_secs(300),
            uid,
        )?;
        let initial = LearningIterationCoordinatorV1::new(
            self.selection.snapshot().request.clone(),
            self.selection.snapshot().owners.clone(),
        )?;
        let (_, verifier, _) = self.selection.original_context().receipt_configuration();
        let client = LearningIterationEvidenceClientV1 {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            command: None,
            initial: initial.snapshot().clone(),
            actor_id: self.selection.snapshot().owners.selector.clone(),
            verifier,
        };
        let mut channel = HostAuthorityPeerChannel::from_stream(
            server,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid,
                    pid: std::process::id(),
                },
                timeout: Duration::from_millis(500),
                lifetime: Duration::from_secs(300),
                request_bound: 16_384,
                response_bound: 16_384,
            },
            command_test_support::pidfd()?,
        )?;
        let host = Arc::clone(self);
        let peer = std::thread::spawn(move || {
            for request_id in 1..=128_u64 {
                if !channel.exchange(|bytes| {
                    let response = host
                        .evidence_response(bytes, request_id)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if let Some((after, file)) = &invalidate_source_after_read {
                        if request_id == *after {
                            // The actual S response already passed its final
                            // T/B/Cell read. Only C's final Source check sees
                            // this durable original Source becoming unreadable.
                            file.set_len(0)
                                .map_err(|_| HostIssuerTransportError::Unavailable)?;
                        }
                    }
                    Ok(response)
                })? {
                    return Ok(request_id - 1);
                }
            }
            Err(Error::Unavailable)
        });
        Ok((client, peer))
    }
}
