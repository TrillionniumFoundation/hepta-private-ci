//! Same-UID mechanism fixture. Public factories reject this custody; actual
//! framing, original pidfds, claims, witnesses and signed results still run.

use codex_hepta_contracts::HostIssuerPeer;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::thread::JoinHandle;

use super::*;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_iteration_evidence_client::training_command::command_test_support;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;

pub(super) use command_test_support::identity;
pub(super) use command_test_support::pidfd;

#[derive(Clone, Copy)]
pub(super) enum Mode {
    ExecuteOnce,
    ReadbackOnly,
}
#[derive(Clone, Copy)]
pub(super) enum Effect {
    Original,
    LoseAck,
    RenewExperience,
    WrongPurpose,
}

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: observe this fixture process's current credentials.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(30),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd()?,
    )?)
}

pub(super) fn connected(
    f: &MaterialCommandFixture,
    role: Role,
    mode: Mode,
    expected: Option<OriginalCellQ24MaterialCommandReceiptV1>,
    effect: Effect,
) -> anyhow::Result<(
    OriginalCellQ24MaterialCommandClientV1,
    JoinHandle<anyhow::Result<u64>>,
)> {
    let owner = Arc::clone(f.host.as_ref().expect("original command host"));
    let config = f.config.clone();
    let binding = wire::context_binding(&config, now()?)?;
    let (stream, server) = UnixStream::pair()?;
    let client = OriginalCellQ24MaterialCommandClientV1 {
        channel: Mutex::new(Some(Channel {
            peer: channel(stream)?,
            next_request_id: 1,
            execution_requested: matches!(mode, Mode::ReadbackOnly),
        })),
        config: config.clone(),
        role,
        binding,
        retained: Mutex::new(expected),
    };
    let mut channel = channel(server)?;
    let thread = std::thread::spawn(move || -> anyhow::Result<u64> {
        if matches!(effect, Effect::Original) {
            return Ok(owner.serve_command_channel(role, &mut channel)?);
        }
        for request_id in 1..=128 {
            let mut completed_before_loss = false;
            let result = channel.exchange(|bytes| {
                let response = owner
                    .command_response(role, bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: wire::Response = serde_json::from_slice(&response)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                match effect {
                    Effect::LoseAck => {
                        if !matches!(response.result, wire::CommandResult::Completed { .. }) {
                            return Err(HostIssuerTransportError::InvalidRequest);
                        }
                        completed_before_loss = true;
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    Effect::RenewExperience => {
                        renew_experience(&config, &mut response)
                            .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    }
                    Effect::WrongPurpose => response.operation = "other-purpose".into(),
                    Effect::Original => unreachable!("handled by actual serving loop"),
                }
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            });
            if matches!(effect, Effect::LoseAck) {
                anyhow::ensure!(
                    completed_before_loss && result.is_err(),
                    "only the ACK was lost after an actual original completion"
                );
                return Ok(request_id);
            }
            if !result? {
                return Ok(request_id - 1);
            }
        }
        anyhow::bail!("bounded fixture connection")
    });
    Ok((client, thread))
}

pub(super) fn finish(
    client: OriginalCellQ24MaterialCommandClientV1,
    thread: JoinHandle<anyhow::Result<u64>>,
) -> anyhow::Result<u64> {
    drop(client);
    thread
        .join()
        .map_err(|_| anyhow::anyhow!("original Material peer panicked"))?
}

fn renew_experience(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    response: &mut wire::Response,
) -> anyhow::Result<()> {
    let wire::CommandResult::Completed { snapshot, evidence } = &mut response.result else {
        anyhow::bail!("original completed Experience required");
    };
    let completed = decode_original_owner_snapshot_v1(&STANDARD_NO_PAD.decode(&*snapshot)?)?;
    anyhow::ensure!(completed.receipts.len() == 1 && evidence.len() == 1);
    let mut receipt = completed.receipts[0].clone();
    let mut signed = evidence.remove(0).decode()?;
    receipt.observed_unix_seconds += 1;
    signed.issued_at += 1;
    signed.expires_at = signed
        .issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or_else(|| anyhow::anyhow!("fixture renewal time"))?
        .min(config.experience_signer.principal.expires_at)
        .min(config.freeze_evidence.expires_at);
    signed.payload_digest = Digest32::of_bytes(
        &codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(&receipt)?,
    );
    signed.signature = SigningKey::from_bytes(&[4; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.initial.clone())?;
    coordinator.record(receipt, signed.issued_at)?;
    let renewed = OriginalCellQ24MaterialCommandReceiptV1 {
        snapshot: coordinator.snapshot().clone(),
        evidence: vec![signed.clone()],
        original_context: wire::context_binding(config, now()?)?,
    };
    // This negative is a valid signature, not malformed bytes or a future time.
    assert_eq!(
        wire::authenticate_cut(config, Role::Experience, renewed.clone(), now()?)?,
        renewed
    );
    *snapshot = STANDARD_NO_PAD.encode(encode_original_owner_snapshot_v1(coordinator.snapshot())?);
    evidence.push(super::super::super::evidence_wire::Evidence::from_original(
        &signed,
    ));
    Ok(())
}

/// Actual original Material service, with a deterministic occupied blocking pool.
pub(super) async fn cancel_queued_execute(
    fixture: &MaterialCommandFixture,
    role: Role,
) -> anyhow::Result<()> {
    let (client, peer) = connected(
        fixture,
        role,
        Mode::ExecuteOnce,
        /*expected*/ None,
        Effect::Original,
    )?;
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(/*val*/ 1)
            .build()?;
        runtime.block_on(async move {
            let (occupied, waiting) = tokio::sync::oneshot::channel();
            let (release, blocked) = std::sync::mpsc::channel();
            let blocker = tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                let _ = occupied.send(());
                blocked
                    .recv()
                    .map_err(|_| anyhow::anyhow!("queued cancellation release"))?;
                Ok(())
            });
            waiting.await?;
            let mut request = Box::pin(client.execute());
            let pending = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(std::future::Future::poll(request.as_mut(), cx).is_pending())
            })
            .await;
            // The only blocking worker is still occupied. Dropping this exact
            // future must fence the queued original Execute before release.
            drop(request);
            release.send(())?;
            blocker.await??;
            assert!(pending, "the actual Execute was queued before cancellation");
            assert!(matches!(client.readback().await, Err(Error::Unavailable)));
            assert!(matches!(client.execute().await, Err(Error::Unavailable)));
            assert_eq!(finish(client, peer)?, 0);
            Ok(())
        })
    })
    .await
    .map_err(|_| anyhow::anyhow!("queued cancellation runtime"))?
}
