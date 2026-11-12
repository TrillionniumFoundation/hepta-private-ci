//! Explicit same-UID transport and synthetic B time for original host tests.
//! Public production factories still require independent original processes.
//! Every successful response comes from the actual original host and journals.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::super::*;
use super::Channel;
use super::OriginalCellEvaluationCommandClientV1;

type Thread = std::thread::JoinHandle<anyhow::Result<u64>>;

fn pidfd() -> anyhow::Result<OwnedFd> {
    Ok(rustix::process::pidfd_open(
        rustix::process::getpid(), rustix::process::PidfdFlags::empty(),
    )?)
}

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::geteuid().as_raw(), pid: std::process::id(),
            },
            timeout: Duration::from_secs(30), lifetime: Duration::from_secs(300),
            request_bound: 16_384, response_bound: 16_384,
        }, pidfd()?,
    )?)
}

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_original_clock(&mut self, at: u64) -> anyhow::Result<()> {
        self.owners.get_mut().map_err(|_| anyhow::anyhow!("original host lock"))?
            .fixture_clock = Some(at);
        Ok(())
    }

    pub(crate) fn fixture_take_original_panel(self) -> anyhow::Result<Panel> {
        let Owners { panel, evaluator, .. } = self.owners.into_inner()
            .map_err(|_| anyhow::anyhow!("original host lock"))?;
        drop(evaluator);
        Ok(panel)
    }

    pub(crate) fn fixture_original_cohort_files(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        self.owners.try_lock().map_err(|_| anyhow::anyhow!("original host lock"))?
            .panel.fixture_cohort_bytes()
    }

    pub(crate) fn fixture_dispatch_consumed(&self) -> bool {
        self.execution_requested.load(Ordering::Acquire)
    }

    pub(crate) fn fixture_expired_original(
        &self, receipt: &OriginalCellEvaluationCommandReceiptV1,
    ) -> anyhow::Result<()> {
        assert!(wire::authenticate_completed(
            &self.context, receipt.snapshot().clone(), receipt.attestation().clone(),
            receipt.attestation().expires_at.checked_add(1)
                .ok_or_else(|| anyhow::anyhow!("fixture signature expiry overflow"))?,
        ).is_err(), "the original complete signature window cannot be renewed");
        Ok(())
    }

    /// The fixture bypasses only same-process admission. Context comes from the
    /// actual original host; no caller constructs a completed receipt or panel.
    pub(crate) fn fixture_commands(
        self: &Arc<Self>,
        readback_only: bool,
        expected: Option<OriginalCellEvaluationCommandReceiptV1>,
        fault: &'static str,
    ) -> anyhow::Result<(OriginalCellEvaluationCommandClientV1, Thread)> {
        let (stream, server) = UnixStream::pair()?;
        let client = OriginalCellEvaluationCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: channel(stream)?, next_request_id: 1,
                execution_requested: readback_only,
            })),
            context: self.context.clone(),
            binding: if fault == "wrong-context" { Digest32::ZERO } else { self.binding },
            retained: Mutex::new(expected),
        };
        let owner = Arc::clone(self);
        let mut peer = channel(server)?;
        let thread = std::thread::spawn(move || -> anyhow::Result<u64> {
            if fault == "original" || fault == "wrong-context" {
                return Ok(owner.fixture_serve_channel(&mut peer)?);
            }
            for request_id in 1..=128_u64 {
                let mut completed_before_loss = false;
                let exchange = peer.exchange(|bytes| {
                    let bytes = owner.fixture_command_response(bytes, request_id)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    let mut response: wire::Response = serde_json::from_slice(&bytes)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if fault == "lose-ack" {
                        if !matches!(&response.outcome, wire::Outcome::Completed { .. }) {
                            return Err(HostIssuerTransportError::InvalidRequest);
                        }
                        completed_before_loss = true;
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    let change = request_id > 1 || fault.starts_with("cold-");
                    if change {
                        response.outcome = match fault {
                            "after-missing" | "cold-missing" => wire::Outcome::Missing,
                            "after-pending" | "cold-pending" => wire::Outcome::Pending,
                            "after-renewal" => renew_original(
                                &owner.context, response.outcome,
                            ).map_err(|_| HostIssuerTransportError::InvalidRequest)?,
                            _ => return Err(HostIssuerTransportError::InvalidRequest),
                        };
                    }
                    serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
                });
                if fault == "lose-ack" {
                    anyhow::ensure!(completed_before_loss && exchange.is_err(),
                        "only the ACK is lost after original Evaluation completion");
                    return Ok(request_id);
                }
                if !exchange? { return Ok(request_id - 1); }
            }
            anyhow::bail!("original bounded Evaluation fixture");
        });
        Ok((client, thread))
    }

    pub(crate) async fn fixture_cancel_queued(
        self: &Arc<Self>,
    ) -> anyhow::Result<()> {
        let (client, thread) = self.fixture_commands(
            /*readback_only*/ false, /*expected*/ None, "original",
        )?;
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all().max_blocking_threads(/*val*/ 1).build()?;
            runtime.block_on(async move {
                let (occupied, waiting) = tokio::sync::oneshot::channel();
                let (release, blocked) = std::sync::mpsc::channel();
                let blocker = tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                    let _ = occupied.send(());
                    blocked.recv().map_err(|_| anyhow::anyhow!("queued Evaluation release"))?;
                    Ok(())
                });
                waiting.await?;
                let mut request = Box::pin(client.execute_evaluation());
                let pending = std::future::poll_fn(|cx| std::task::Poll::Ready(
                    std::future::Future::poll(request.as_mut(), cx).is_pending(),
                )).await;
                drop(request);
                release.send(())?;
                blocker.await??;
                assert!(pending, "the real Execute was queued before cancellation");
                assert!(matches!(client.readback().await, Err(Error::Unavailable)));
                assert!(matches!(client.execute_evaluation().await, Err(Error::Unavailable)));
                drop(client);
                assert_eq!(thread.join().expect("original Evaluation peer")?, 0);
                Ok(())
            })
        }).await.map_err(|_| anyhow::anyhow!("queued Evaluation runtime"))?
    }
}

fn renew_original(context: &Context, response: wire::Outcome) -> anyhow::Result<wire::Outcome> {
    let wire::Outcome::Completed { snapshot, original_evidence } = response else {
        anyhow::bail!("only a real completed original may be renewed in this negative");
    };
    let mut original = wire::decode_completed(context, snapshot, original_evidence, now()?)?;
    let previous = original.attestation.clone();
    original.attestation.expires_at = original.attestation.expires_at.checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("fixture expiry overflow"))?;
    original.attestation.signature = SigningKey::from_bytes(&[42; 32])
        .sign(&original.attestation.signing_bytes()).to_bytes();
    assert_ne!(original.attestation, previous);
    // This is a valid full Evaluator signature over the identical real payload;
    // the client must reject its changed original byte identity.
    Ok(wire::encode_completed(context, original, now()?)?)
}
