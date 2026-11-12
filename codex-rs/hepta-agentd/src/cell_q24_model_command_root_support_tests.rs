//! Same-process transport mechanism only. Successful record bytes are
//! recomputed from the actual original Model read and checked against that
//! original receipt by the production encoder. No production factory exists.
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use pretty_assertions::assert_eq;

use super::client::Channel;
use super::context::Context;
use super::*;
use crate::CellQ24ModelProposalReceiptV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::learning_iteration_evidence_client::training_command::serving::command_test_support;

fn context(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    completed: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1; 4],
) -> anyhow::Result<Context> {
    let mut cut = LearningIterationCoordinatorV1::from_snapshot(material.initial.clone())?;
    for receipt in &completed.receipts[..2] {
        cut.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    let dataset = OriginalCellQ24MaterialCommandReceiptV1::fixture_original_model_dataset(
        &material,
        cut.snapshot().clone(),
        signatures[..2].to_vec(),
    )?;
    let training = super::super::wire::authenticate_receipt(
        &OriginalCellQ24TrainingCommandContextV1 {
            dataset: dataset.snapshot().clone(),
            scope: material.scope.clone(),
            verifier: material.verifier.clone(),
        },
        completed.receipts[2].clone(),
        signatures[2].clone(),
        now()?,
    )?;
    let evaluation = OriginalCellEvaluationCommandReceiptV1::fixture_original_model_evaluation(
        dataset.snapshot().clone(),
        material.scope.clone(),
        registration.clone(),
        material.verifier.clone(),
        &training,
        completed.receipts[3].clone(),
        signatures[3].clone(),
    )?;
    Ok(Context::from_original(
        material,
        registration,
        dataset,
        training,
        evaluation,
    )?)
}

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::geteuid().as_raw(),
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(30),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        command_test_support::pidfd()?,
    )?)
}

enum FixtureAccess {
    Fresh,
    Readonly(OriginalCellQ24ModelCommandReceiptV1),
}
fn fixture_client(
    context: Context,
    access: FixtureAccess,
) -> anyhow::Result<(
    OriginalCellQ24ModelCommandClientV1,
    HostAuthorityPeerChannel,
)> {
    let (stream, peer) = UnixStream::pair()?;
    let (execution_requested, retained) = match access {
        FixtureAccess::Fresh => (false, None),
        FixtureAccess::Readonly(original) => (true, Some(original)),
    };
    Ok((
        OriginalCellQ24ModelCommandClientV1 {
            binding: context.binding()?,
            observed_at: now()?,
            context,
            channel: Mutex::new(Some(Channel {
                peer: channel(stream)?,
                next: 1,
                execution_requested,
            })),
            retained: Mutex::new(retained),
        },
        channel(peer)?,
    ))
}

fn response(
    context: &Context,
    actual: &CellQ24ModelProposalReceiptV1,
    material: Digest32,
    bytes: &[u8],
    action: wire::Action,
) -> Result<Vec<u8>, HostIssuerTransportError> {
    let request: wire::Request =
        serde_json::from_slice(bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)?;
    request
        .require_context(context, 1)
        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
    if request.action != action {
        return Err(HostIssuerTransportError::InvalidRequest);
    }
    let outcome = wire::encode_completed(
        context,
        actual,
        material,
        now().map_err(|_| HostIssuerTransportError::InvalidRequest)?,
    )
    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
    serde_json::to_vec(&wire::Response { request, outcome })
        .map_err(|_| HostIssuerTransportError::InvalidRequest)
}

impl OriginalCellQ24ModelCommandReceiptV1 {
    pub(crate) async fn fixture_original_model_response(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        completed: LearningIterationSnapshotV1,
        signatures: [SignedLearningEvidenceV1; 4],
        actual: CellQ24ModelProposalReceiptV1,
        material_digest: Digest32,
    ) -> anyhow::Result<Self> {
        let context = context(material, registration, &completed, &signatures)?;
        let (client, mut peer) = fixture_client(context.clone(), FixtureAccess::Fresh)?;
        let server = std::thread::spawn(move || -> anyhow::Result<()> {
            assert!(peer.exchange(|bytes| response(
                &context,
                &actual,
                material_digest,
                bytes,
                wire::Action::Readback
            ))?);
            Ok(())
        });
        let read = client.readback().await;
        drop(client);
        server
            .join()
            .map_err(|_| anyhow::anyhow!("original Model fixture peer"))??;
        let read = read?;
        assert_eq!(read.snapshot(), &completed);
        assert_eq!(read.predecessors.as_slice(), signatures.as_slice());
        Ok(read)
    }

    pub(crate) async fn fixture_unknown_does_not_recommit(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        completed: LearningIterationSnapshotV1,
        signatures: [SignedLearningEvidenceV1; 4],
        actual: CellQ24ModelProposalReceiptV1,
        material_digest: Digest32,
        retained: Self,
    ) -> anyhow::Result<()> {
        let context = context(material, registration, &completed, &signatures)?;
        let (client, mut peer) = fixture_client(context.clone(), FixtureAccess::Fresh)?;
        let frames = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&frames);
        let before = actual.clone();
        let server_context = context.clone();
        let server = std::thread::spawn(move || -> anyhow::Result<()> {
            assert!(
                peer.exchange(|bytes| {
                    // A genuine completed Model record was read before this ACK
                    // is deliberately lost. This fixture performs no extra commit.
                    let _ = response(
                        &server_context,
                        &before,
                        material_digest,
                        bytes,
                        wire::Action::Execute,
                    )?;
                    observed.fetch_add(1, Ordering::SeqCst);
                    Err(HostIssuerTransportError::Unavailable)
                })
                .is_err()
            );
            Ok(())
        });
        assert!(matches!(
            client.commit_model(Arc::new(AtomicBool::new(false))).await,
            Err(Error::CommitUncertain)
        ));
        assert!(matches!(
            client.commit_model(Arc::new(AtomicBool::new(false))).await,
            Err(Error::Unavailable)
        ));
        assert!(matches!(client.readback().await, Err(Error::Unavailable)));
        drop(client);
        server
            .join()
            .map_err(|_| anyhow::anyhow!("lost Model ACK fixture"))??;
        assert_eq!(frames.load(Ordering::SeqCst), 1);

        // A separately supplied original readonly handoff never inherits
        // Execute, even though the original completion and signature pin exist.
        let (cold, mut peer) =
            fixture_client(context.clone(), FixtureAccess::Readonly(retained.clone()))?;
        let server = std::thread::spawn(move || -> anyhow::Result<()> {
            assert!(peer.exchange(|bytes| response(
                &context,
                &actual,
                material_digest,
                bytes,
                wire::Action::Readback
            ))?);
            Ok(())
        });
        assert!(matches!(
            cold.commit_model(Arc::new(AtomicBool::new(false))).await,
            Err(Error::ReadbackRequired)
        ));
        let current = cold.readback().await;
        drop(cold);
        server
            .join()
            .map_err(|_| anyhow::anyhow!("readonly Model fixture"))??;
        assert_eq!(current?, retained);
        Ok(())
    }
}
