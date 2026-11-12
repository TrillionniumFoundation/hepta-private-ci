//! Recover the actual same-A E/D journals. Only original fixture keys and
//! same-process transport are supplied; no receipt or command reply is made.

use super::*;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialEvidenceRoleV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialReceiptFilesV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;
use ed25519_dalek::SigningKey;

pub(super) struct OriginalDataset {
    pub(super) config: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) receipt: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) readback: OriginalCellQ24DatasetCommandReadbackV1,
    pub(super) peer: material_ports::Peer,
}

pub(super) async fn original_dataset(f: &PublicationFixture) -> anyhow::Result<OriginalDataset> {
    let config = f.host.original.command_config.clone();
    let root = &f.host.original.root;
    let open = |name: &str| -> anyhow::Result<File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join(name))?)
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
    let before = f.host.original.predecessor_bytes()?;
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
    let owner = Arc::new(owners.into_command_owner(
        f.original_source.as_ref().clone(),
        f.identity_a.clone(),
        Arc::clone(&f.host.original.ledger),
        Arc::clone(&f.host.original.baseline),
    )?);
    let (client, peer) = material_ports::commands_for_original(
        owner,
        config.clone(),
        OriginalCellQ24MaterialEvidenceRoleV1::Dataset,
    )?;
    let readback = client.into_original_dataset_readback(&config)?;
    let receipt = readback.readback().await?;
    assert_eq!(receipt.snapshot(), &f.trainer_context.dataset);
    assert_eq!(receipt.attestations(), &f.host.original.material_evidence);
    assert_eq!(f.host.original.predecessor_bytes()?, before);
    Ok(OriginalDataset {
        config,
        receipt,
        readback,
        peer,
    })
}
