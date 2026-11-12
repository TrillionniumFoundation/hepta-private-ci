//! One original source connection, owned and joined with the B serving scope.
//! The absence of a source connection never turns NoUpdate into an execution.

use super::*;
use crate::root_independent_b_source_protocol::FRAME_BOUND;
use crate::root_independent_b_source_protocol::PURPOSE;
use crate::root_independent_b_source_protocol::SourceAcknowledgement;
use crate::root_independent_b_source_protocol::SourceRequest;

pub(super) fn serve_until(
    bound: &BoundRootIndependentBEvaluationV1,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(listener) = &bound.source_listener else {
        if bound.runtime.source.peer.is_some() {
            return Err(io::Error::other("unbound original B source peer"));
        }
        return original();
    };
    let peer = bound
        .runtime
        .source
        .peer
        .as_ref()
        .ok_or_else(|| io::Error::other("original B source pin missing"))?;
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
                match listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(error) => return Err(error),
                }
            };
            {
                let mut slot = active
                    .lock()
                    .map_err(|_| io::Error::other("B source stream poisoned"))?;
                if stop.load(Ordering::Acquire) {
                    return Ok(());
                }
                *slot = Some(stream.try_clone()?);
            }
            peer.require_live()?;
            let policy = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: peer.lifetime.uid,
                    pid: peer.lifetime.pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime: end
                    .checked_duration_since(Instant::now())
                    .ok_or_else(|| io::Error::other("B source original end expired"))?,
                request_bound: FRAME_BOUND,
                response_bound: FRAME_BOUND,
            };
            let mut channel =
                HostAuthorityPeerChannel::from_stream(stream, policy, peer.original_descriptor()?)
                    .map_err(io::Error::other)?;
            channel.limit_original_end(end).map_err(io::Error::other)?;
            let mut admitted = None;
            let exchanged = channel
                .exchange_with_original_deadline(|bytes, frame_end| {
                    let request: SourceRequest = serde_json::from_slice(bytes)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if serde_json::to_vec(&request)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?
                        != bytes
                        || request.schema != 1
                        || request.purpose != PURPOSE
                        || request.binding != bound.runtime.bootstrap.binding
                    {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    }
                    bound.runtime.source.flow.require_prepared()
                        .map_err(|_| HostIssuerTransportError::Unavailable)?;
                    let response = OriginalRootIndependentBEvaluationFilesV1::retain_original_signed_source(
                        &bound.runtime.host,
                        service,
                        config,
                        registration,
                        owner,
                        peer,
                        frame_end,
                        &request,
                    )
                    .map_err(|_| HostIssuerTransportError::Unavailable)?;
                    let acknowledgement: SourceAcknowledgement = serde_json::from_slice(&response)
                        .map_err(|_| HostIssuerTransportError::Unavailable)?;
                    if serde_json::to_vec(&acknowledgement).map_err(|_| HostIssuerTransportError::Unavailable)? != response {
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    admitted = Some(acknowledgement);
                    Ok(response)
                })
                .map_err(io::Error::other)?;
            if !exchanged && !stop.load(Ordering::Acquire) {
                return Err(io::Error::other(
                    "original B source ended without admission",
                ));
            }
            if exchanged {
                let source = admitted.ok_or_else(|| io::Error::other("original B source exchange retained no cut"))?;
                // Only the full original admission and its frame have returned.
                // This readiness is DATA; Complete rechecks the retained files.
                bound.runtime.source.flow.publish_admitted(source, end, || {
                    if stop.load(Ordering::Acquire) {
                        return Err(io::Error::other("original B source serving stopped"));
                    }
                    // The source may exit only after the separate finalized
                    // notice sent here, after the whole frame has returned.
                    owner_alive(owner, end)
                })?;
            }
            Ok(())
            })();
            if result.is_err() { bound.runtime.source.flow.refuse(); }
            result
        });
        let result = original();
        stop.store(true, Ordering::Release);
        bound.runtime.source.flow.refuse();
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("B source stream poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let served = worker
            .join()
            .map_err(|_| io::Error::other("B source worker panicked"))?;
        result.and(served)
    })
}
