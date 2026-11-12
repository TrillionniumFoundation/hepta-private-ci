//! Same original A, native Candidate, actual D/T owners and independent B.
//! Role credentials, Product declarations and B observation time remain
//! explicit mechanism fixtures; this does not qualify ordinary deployment.

use anyhow::Context as _;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialEvidenceRoleV1;
use crate::OriginalCellQ24MaterialReceiptFilesV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24TrainingCommandOwnerV1;
use crate::learning_iteration_evidence_client::command_test_support as commands;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports as training_ports;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;

type Trainer =
    OriginalCellQ24TrainingCommandOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

enum Control {
    Original,
    WithdrawNativeAt(u64),
    PauseAt {
        request: u64,
        entered: tokio::sync::oneshot::Sender<()>,
        release: std::sync::mpsc::Receiver<()>,
    },
}

struct TrainingFixture {
    host: Box<HostFixture>,
    peer: std::thread::JoinHandle<anyhow::Result<u64>>,
    trace: commands::PanelReadTrace,
}

impl TrainingFixture {
    async fn new(control: Control) -> anyhow::Result<Self> {
        let panel = Box::pin(PanelFixture::completed_for_publication(
            TrainingPeer::Original,
            PublicationMode::RetainOriginalA,
        ))
        .await?;
        let dataset = original_dataset(&panel.original).await?;
        let mut training_cut = panel.primary.config.training.clone();
        let completed = training_cut
            .receipts
            .pop()
            .context("actual original Training")?;
        training_cut.head_digest = completed.predecessor;
        assert_eq!(dataset.snapshot(), &training_cut);
        let context = OriginalCellQ24TrainingCommandContextV1 {
            dataset: training_cut,
            scope: panel.primary.config.scope.clone(),
            verifier: panel.primary.config.verifier.clone(),
        };
        let trainer = Arc::new(
            Trainer::recover_original_stage(
                Arc::clone(&panel.original.stage),
                context.clone(),
                Arc::new(AtomicBool::new(false)),
            )
            .await?,
        );
        let (client, channel) = commands::client(context, true, None)?;
        let original_peer = commands::serve(Arc::clone(&trainer), channel);
        let training = client.readback().await?;
        assert_eq!(training.receipt(), &completed);
        assert_eq!(
            training.attestation(),
            &panel.primary.config.training_evidence
        );
        drop(client);
        assert_eq!(original_peer.join().expect("original Trainer command")?, 1);
        let (connection, channel) =
            training_ports::readonly_channel(panel.original.command_config.clone())?;
        let control = match control {
            Control::Original => commands::PanelReadControl::Original,
            Control::WithdrawNativeAt(request) => commands::PanelReadControl::Withdraw {
                request,
                path: panel.original.root.join("positive-native-training"),
            },
            Control::PauseAt {
                request,
                entered,
                release,
            } => commands::PanelReadControl::Pause {
                request,
                entered,
                release,
            },
        };
        let (peer, trace) = commands::panel_readonly(trainer, channel, control);
        let host = HostFixture::from_panel_with_training(
            panel,
            false,
            TrainingComposition::Original {
                connection,
                dataset,
                training,
            },
        )?;
        Ok(Self { host, peer, trace })
    }

    fn requests(&self) -> u64 {
        self.trace.requests.load(Ordering::Acquire)
    }

    fn current_responses(&self) -> u64 {
        self.trace.current_responses.load(Ordering::Acquire)
    }

    async fn finish(mut self) -> anyhow::Result<(u64, [usize; 2])> {
        // Close every actual T client before joining its owner. No process or
        // native worker is killed; the original finite channel observes EOF.
        drop(self.host.host.take());
        let frames = self.peer.join().expect("actual panel Trainer readonly")?;
        let members = Box::pin(self.host.finish()).await?;
        Ok((frames, members))
    }
}

async fn original_dataset(
    original: &PositiveFixture,
) -> anyhow::Result<OriginalCellQ24MaterialCommandReceiptV1> {
    let config = original.command_config.clone();
    let open = |name: &str| -> anyhow::Result<File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .open(original.root.join(name))?)
    };
    let witness = |name: &str| -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            open(name)?,
            JournalScope {
                scope_digest: config.scope.binding(),
                objective_digest: config.initial.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            64,
        )?)
    };
    let before = original.predecessor_bytes()?;
    let owners = OriginalCellQ24MaterialReceiptOwnersV1::recover(
        OriginalCellQ24MaterialReceiptFilesV1 {
            experience: open("positive-experience")?,
            experience_witness: witness("positive-experience-witness")?,
            dataset: open("positive-dataset")?,
            dataset_witness: witness("positive-dataset-witness")?,
        },
        config.clone(),
        SigningKey::from_bytes(&[44; 32]),
        SigningKey::from_bytes(&[45; 32]),
    )?;
    let a = original.session.0.as_ref().context("same original A")?;
    let owner = Arc::new(owners.into_command_owner(
        a.source.as_ref().clone(),
        a.runtime.identity.clone(),
        Arc::clone(&original.ledger),
        Arc::clone(&original.baseline),
    )?);
    let (client, peer) = material_ports::commands_for_original(
        owner,
        config.clone(),
        OriginalCellQ24MaterialEvidenceRoleV1::Dataset,
    )?;
    let readback = client.into_original_dataset_readback(&config)?;
    let receipt = readback.readback().await?;
    assert_eq!(receipt.attestations(), &original.material_evidence);
    assert_eq!(original.predecessor_bytes()?, before);
    drop(readback);
    assert_eq!(peer.join().expect("same original Dataset")?, 1);
    Ok(receipt)
}

#[path = "circuit_original_evaluation_training_read_tests.rs"]
mod tests;
