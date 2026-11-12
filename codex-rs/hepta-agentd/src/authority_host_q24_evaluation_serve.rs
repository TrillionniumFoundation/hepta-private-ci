//! One purpose connection, owned by the original Root serving scope. Stop
//! closes that stream and joins the actual worker; no detached B task survives.

use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;

use super::*;
use crate::root_independent_b_protocol::*;

#[path = "authority_host_q24_evaluation_source_serve.rs"]
mod source;

pub(crate) fn serve_optional_until(
    bound: Option<&BoundRootIndependentBEvaluationV1>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original_end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(bound) = bound else {
        return original();
    };
    let end = bound.runtime.end.min(original_end);
    owner_alive(owner, end)?;
    bound
        .runtime
        .phase
        .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| io::Error::other("original B serving opportunity already consumed"))?;
    source::serve_until(bound, service, config, registration, owner, end, || {
        serve_evaluation_until(bound, service, config, registration, owner, end, original)
    })
}

fn serve_evaluation_until(
    bound: &BoundRootIndependentBEvaluationV1,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let stop = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let result = (|| {
            let stream = loop {
                if stop.load(Ordering::Acquire) {
                    return Ok(());
                }
                owner_alive(owner, end)?;
                match bound.listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(error) => return Err(error),
                }
            };
            {
                let mut slot = active
                    .lock()
                    .map_err(|_| io::Error::other("B active stream poisoned"))?;
                if stop.load(Ordering::Acquire) {
                    return Ok(());
                }
                *slot = Some(stream.try_clone()?);
            }
            let policy = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime: end
                    .checked_duration_since(Instant::now())
                    .ok_or_else(|| io::Error::other("B original end expired"))?,
                request_bound: 16_384,
                response_bound: 16_384,
            };
            let mut channel =
                HostAuthorityPeerChannel::from_stream(stream, policy, owner.try_clone()?)
                    .map_err(io::Error::other)?;
            channel.limit_original_end(end).map_err(io::Error::other)?;
            let mut sequence = 1_u64;
            let mut wait_source = false;
            loop {
                let exchanged = channel
                .exchange_with_original_deadline(|bytes, frame_end| {
                    let request: Request = serde_json::from_slice(bytes)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if serde_json::to_vec(&request)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?
                        != bytes
                        || request.schema != 1
                        || request.purpose != PURPOSE
                        || request.sequence != sequence
                        || sequence > 32
                        || request.binding != bound.runtime.bootstrap.binding
                        || (sequence == 1) != matches!(&request.command, Command::Observe)
                    {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    }
                    let response = match request.command {
                        Command::Observe => encode_response(
                            sequence,
                            &bound.runtime.bootstrap.binding,
                            Observation::Bound {
                                initial: bound
                                    .runtime
                                    .host
                                    .observe_original_binding(
                                        service,
                                        config,
                                        registration,
                                        owner,
                                        frame_end,
                                    )
                                    .map_err(|_| HostIssuerTransportError::Unavailable)?,
                            },
                        )
                        .map_err(|_| HostIssuerTransportError::Unavailable)?,
                        Command::PrepareCandidate {
                            training_head,
                            training_attestation,
                        } => {
                            let head = digest(&training_head)
                                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            let (_, signed) =
                                crate::learning_owner_evidence::decode(&training_attestation)
                                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            let (response, candidate) = OriginalRootIndependentBEvaluationFilesV1::prepare_original_candidate(&bound.runtime.host,
                                    service,
                                    config,
                                    registration,
                                    owner,
                                    frame_end,
                                    head,
                                    &signed,
                                    |actual| {
                                        encode_response(
                                            sequence,
                                            &bound.runtime.bootstrap.binding,
                                            Observation::Prepared(Box::new(actual)),
                                        )
                                    },
                                )
                                .map_err(|_| HostIssuerTransportError::Unavailable)?;
                            // The complete original Root context and durable Ready
                            // have returned. Only DATA is sent to the source here.
                            bound.runtime.source.flow.publish_candidate(candidate, frame_end, || {
                                if stop.load(Ordering::Acquire) {
                                    return Err(io::Error::other("original B serving stopped"));
                                }
                                owner_alive(owner, end)?;
                                if let Some(peer) = &bound.runtime.source.peer { peer.require_live()?; }
                                Ok(())
                            }).map_err(|_| HostIssuerTransportError::Unavailable)?;
                            wait_source = true;
                            response
                        }
                        Command::Complete {
                            training_head,
                            training_attestation,
                            plan_attestation,
                            source_admission,
                        } => {
                            bound.runtime.source.flow.require_admitted(&source_admission)
                                .map_err(|_| HostIssuerTransportError::Unavailable)?;
                            let head = digest(&training_head)
                                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            let (_, signed) =
                                crate::learning_owner_evidence::decode(&training_attestation)
                                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            let (_, plan_signed) =
                                crate::learning_owner_evidence::decode(&plan_attestation)
                                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            OriginalRootIndependentBEvaluationFilesV1::complete_from_original_training(&bound.runtime.host,
                                    service,
                                    config,
                                    registration,
                                    owner,
                                    frame_end,
                                    head,
                                    &signed,
                                    &plan_signed,
                                    &source_admission,
                                    |actual| {
                                        encode_response(
                                            sequence,
                                            &bound.runtime.bootstrap.binding,
                                            completed_data(actual)?,
                                        )
                                    },
                                )
                                .map_err(|_| HostIssuerTransportError::Unavailable)?
                        }
                        Command::Readback { training_head } => {
                            let head = digest(&training_head)
                                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                            OriginalRootIndependentBEvaluationFilesV1::with_original_completed_evaluation(&bound.runtime.host,
                                    service,
                                    config,
                                    registration,
                                    owner,
                                    frame_end,
                                    head,
                                    |actual| {
                                        encode_response(
                                            sequence,
                                            &bound.runtime.bootstrap.binding,
                                            completed_data(actual)?,
                                        )
                                    },
                                )
                                .map_err(|_| HostIssuerTransportError::Unavailable)?
                        }
                    };
                    sequence = sequence
                        .checked_add(1)
                        .ok_or(HostIssuerTransportError::Unavailable)?;
                    Ok(response)
                })
                .map_err(io::Error::other)?;
                if !exchanged { break; }
                if wait_source {
                    // No active frame, B state mutex or Root record gate is
                    // held while the independent source performs its business.
                    bound.runtime.source.flow.wait_admitted(end, || {
                        if stop.load(Ordering::Acquire) {
                            return Err(io::Error::other("original B serving stopped"));
                        }
                        owner_alive(owner, end)
                    })?;
                    wait_source = false;
                }
            }
            Ok(())
            })();
            if result.is_err() { bound.runtime.source.flow.refuse(); }
            result
        });
        let result = original();
        stop.store(true, Ordering::Release);
        bound.runtime.source.flow.refuse();
        bound.runtime.phase.store(2, Ordering::Release);
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("B active stream poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let served = worker
            .join()
            .map_err(|_| io::Error::other("original B worker panicked"))?;
        result.and(served)
    })
}

fn encode_response(sequence: u64, binding: &str, result: Observation) -> io::Result<Vec<u8>> {
    let response = Response {
        schema: 1,
        purpose: PURPOSE.into(),
        sequence,
        binding: binding.into(),
        result,
    };
    let bytes = serde_json::to_vec(&response).map_err(io::Error::other)?;
    if bytes.len() > 16_384 {
        return Err(io::Error::other("bounded original B response required"));
    }
    Ok(bytes)
}

fn completed_data(actual: OriginalRootBEvaluationBorrowV1<'_>) -> io::Result<Observation> {
    let receipt = actual.receipt();
    let payload =
        codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(receipt)
            .map_err(io::Error::other)?;
    let comparison =
        serde_json::to_string(actual.execution().plan().record()).map_err(io::Error::other)?;
    Ok(Observation::Completed(Box::new(CompletedData {
        training_head: actual.training_snapshot().head_digest.to_string(),
        receipt: ReceiptData::from_original(receipt)?,
        attestation: crate::learning_owner_evidence::encode(&payload, actual.attestation())
            .map_err(io::Error::other)?,
        manifest: actual
            .execution()
            .plan()
            .record()
            .candidate
            .manifest
            .clone(),
        comparison_digest: Digest32::of_bytes(comparison.as_bytes()).to_string(),
        plan_digest: actual
            .execution()
            .plan()
            .product_plan()
            .frozen_plan
            .plan_digest
            .to_string(),
        execution_digest: actual.execution().temporal().execution_digest.to_string(),
    })))
}
