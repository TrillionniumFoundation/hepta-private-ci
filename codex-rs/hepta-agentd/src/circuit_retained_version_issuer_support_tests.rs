//! UID-0 issuer protocol and actual retained Version host mechanisms. The
//! original A/Artifact/Control/FinalUse/C factory are real. E/D/T and the Root
//! response signer are explicit test credentials, not a deployed learning loop.
use super::*;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::OriginalCircuitRetainedVersionErrorV1;
use crate::OriginalCircuitRetainedVersionHostV1;
use crate::OriginalCircuitRetainedVersionReadbackV1;
use crate::learning_iteration_evidence_client::command_test_support;
use crate::learning_iteration_evidence_client::retained_version_dataset_fixture;

#[path = "circuit_retained_version_issuer_metadata_tests.rs"]
mod metadata;
#[path = "circuit_retained_version_issuer_tests.rs"]
mod tests;

struct RetainedIssuerFixtureV1 {
    original: RetainedPublicationFixture,
    host: Option<Arc<OriginalCircuitRetainedVersionHostV1>>,
    dataset_peer: std::thread::JoinHandle<anyhow::Result<usize>>,
    training_peer: std::thread::JoinHandle<anyhow::Result<usize>>,
    root_peer: Option<UnixStream>,
    _c: RuntimeFixture,
}

impl RetainedIssuerFixtureV1 {
    async fn ready() -> anyhow::Result<Self> {
        // SAFETY: this ignored test is explicitly selected by the Root runner.
        anyhow::ensure!(unsafe { libc::geteuid() } == 0, "actual UID-0 issuer fixture required");
        let mut original = RetainedPublicationFixture::ready_with_clock(
            RetainedPublicationFixtureClockV1::LiveArtifactClock,
        ).await?;
        let (material, evidence) = metadata::rebuild_metadata(&mut original)?;
        let (dataset, dataset_peer) = retained_version_dataset_fixture(
            material.clone(), original.dataset(), evidence,
        )?;
        let (training, training_peer) = command_test_support::retained_version_training_connection(
            material.clone(), OriginalCellQ24TrainingCommandContextV1 {
                dataset: original.dataset(), scope: material.scope.clone(),
                verifier: material.verifier.clone(),
            }, original.metadata.training.clone(), original.metadata.training_signature.clone(),
        )?;
        let (stream, root_peer) = UnixStream::pair()?;
        let issuer = AgentdUnixFinalUseGrantProvider::from_root_stream(
            stream, std::process::id(), command_test_support::pidfd()?,
            Duration::from_secs(30), Duration::from_secs(300),
        )?;
        let (task, runtime) = support::retained_version_task_inputs(
            original.c.take().context("one actual C admission")?, original.definition.clone(),
            original.source_c.clone(), Arc::clone(&original.model), original.bundle.clone(),
            original.original_source.as_ref().clone(), original.identity_a.clone(),
        )?;
        let checkpoint = original.version.retained_artifact_checkpoint()?;
        let inputs = original.inputs()?;
        let host = OriginalCircuitRetainedVersionHostV1::from_original_owners(
            material, dataset, training, inputs, task, checkpoint, issuer, Duration::from_secs(300),
        )?;
        Ok(Self { original, host: Some(Arc::new(host)), dataset_peer, training_peer,
            root_peer: Some(root_peer), _c: runtime })
    }

    fn host(&self) -> Arc<OriginalCircuitRetainedVersionHostV1> {
        Arc::clone(self.host.as_ref().expect("original host fixture"))
    }

    async fn prepare(&self) -> anyhow::Result<(OriginalCircuitRetainedVersionReadbackV1, FinalUseBinding)> {
        let result = OriginalCircuitRetainedVersionHostV1::prepare_original_version_fixture(self.host()).await?;
        anyhow::ensure!(result.publication().is_none(), "actual prepared Control only");
        let binding = OriginalCircuitRetainedVersionHostV1::read_original_final_use_binding(self.host()).await?;
        anyhow::ensure!(binding.destination_id == "agentd.cell-generation.next-task-same-model",
            "same exact retained purpose");
        Ok((result, binding))
    }

    fn finish(mut self) -> anyhow::Result<()> {
        drop(self.host.take());
        drop(self.root_peer.take());
        anyhow::ensure!(self.dataset_peer.join().map_err(|_| anyhow::anyhow!("Dataset peer"))?? > 0,
            "actual Dataset codec was read");
        anyhow::ensure!(self.training_peer.join().map_err(|_| anyhow::anyhow!("Trainer peer"))?? > 0,
            "actual Trainer codec was read");
        Ok(())
    }
}

enum RetainedIssuerReplyV1 { Signed(SignedFinalUseGrant), Denied, LoseAck }

fn root_reply(
    mut stream: UnixStream, expected: FinalUseBinding, reply: RetainedIssuerReplyV1,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        stream.set_read_timeout(Some(Duration::from_secs(30)))?;
        let mut length = [0; 4]; stream.read_exact(&mut length)?;
        let length = u32::from_be_bytes(length) as usize;
        anyhow::ensure!((1..=4096).contains(&length), "original bounded Root request");
        let mut bytes = vec![0; length]; stream.read_exact(&mut bytes)?;
        let request: serde_json::Value = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(request == serde_json::json!({
            "schema_version": 1, "operation": "runtime.agentd.production_operation",
            "binding": expected,
        }), "only the actual original prepared intent is requested");
        if matches!(reply, RetainedIssuerReplyV1::LoseAck) { return Ok(()); }
        let (grant, denial) = match reply {
            RetainedIssuerReplyV1::Signed(grant) => (Some(grant), None),
            RetainedIssuerReplyV1::Denied => (None, Some("explicit fixture policy denied")),
            RetainedIssuerReplyV1::LoseAck => unreachable!("handled above"),
        };
        let response = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "revocations": { "authority_epoch": 1, "revision": 1, "revoked_grant_ids": [] },
            "grant": grant, "denial_reason": denial,
        }))?;
        stream.write_all(&(response.len() as u32).to_be_bytes())?;
        stream.write_all(&response)?;
        let mut extra = [0; 1];
        anyhow::ensure!(stream.read(&mut extra)? == 0, "one request; original issuer is not retained for retry");
        Ok(())
    })
}

fn no_root_frame(mut stream: UnixStream) -> anyhow::Result<()> {
    stream.set_read_timeout(Some(Duration::from_millis(50)))?;
    let mut byte = [0; 1];
    match stream.read(&mut byte) {
        Ok(0) => Ok(()),
        Err(error) if matches!(error.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) => Ok(()),
        other => anyhow::bail!("no Root frame expected: {other:?}"),
    }
}

async fn require_no_second_issuer(host: Arc<OriginalCircuitRetainedVersionHostV1>) {
    assert!(matches!(OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(host).await,
        Err(OriginalCircuitRetainedVersionErrorV1::ReadbackRequired)));
}
