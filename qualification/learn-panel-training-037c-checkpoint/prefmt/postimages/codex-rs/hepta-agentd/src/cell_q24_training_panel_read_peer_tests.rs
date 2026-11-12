//! Observe the original bounded readonly handler; every response comes from
//! the actual SourceBound Trainer. Faults change only this fixture's own file
//! or pause an already-admitted request, never manufacture a T signature.

use std::path::PathBuf;
use std::sync::atomic::AtomicU64;

use super::*;

pub(crate) enum PanelReadControl {
    Original,
    Withdraw { request: u64, path: PathBuf },
    Pause {
        request: u64,
        entered: tokio::sync::oneshot::Sender<()>,
        release: std::sync::mpsc::Receiver<()>,
    },
}

#[derive(Clone)]
pub(crate) struct PanelReadTrace {
    pub(crate) requests: Arc<AtomicU64>,
    pub(crate) current_responses: Arc<AtomicU64>,
}

pub(crate) fn panel_readonly<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
    mut control: PanelReadControl,
) -> (std::thread::JoinHandle<anyhow::Result<u64>>, PanelReadTrace) {
    let trace = PanelReadTrace {
        requests: Arc::new(AtomicU64::new(0)),
        current_responses: Arc::new(AtomicU64::new(0)),
    };
    let observed = trace.clone();
    let peer = std::thread::spawn(move || {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                observed.requests.fetch_add(1, Ordering::AcqRel);
                let trigger = match &control {
                    PanelReadControl::Original => false,
                    PanelReadControl::Withdraw { request, .. }
                    | PanelReadControl::Pause { request, .. } => *request == request_id,
                };
                if trigger {
                    match std::mem::replace(&mut control, PanelReadControl::Original) {
                        PanelReadControl::Withdraw { path, .. } => {
                            std::fs::OpenOptions::new()
                                .write(true)
                                .open(path)
                                .and_then(|file| file.set_len(0))
                                .map_err(|_| HostIssuerTransportError::Unavailable)?;
                        }
                        PanelReadControl::Pause { entered, release, .. } => {
                            entered.send(()).map_err(|_| HostIssuerTransportError::Unavailable)?;
                            release.recv_timeout(Duration::from_millis(250))
                                .map_err(|_| HostIssuerTransportError::Unavailable)?;
                        }
                        PanelReadControl::Original => {}
                    }
                }
                let response = owner.original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let decoded: wire::Response = serde_json::from_slice(&response)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if matches!(decoded.result, wire::CommandResult::Completed { .. }) {
                    observed.current_responses.fetch_add(1, Ordering::AcqRel);
                }
                Ok(response)
            })? {
                return Ok(request_id - 1);
            }
        }
        anyhow::bail!("bounded original panel Trainer peer")
    });
    (peer, trace)
}
