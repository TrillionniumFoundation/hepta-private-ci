//! Version cold readback uses the same real Material journals, Source/Ledger,
//! native T and completed Ineligible B. Only same-process sockets and enrolled
//! fixture keys differ from deployment. No receipt is supplied as a response.

use super::*;
use anyhow::Context as _;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::time::Duration;
use crate::OriginalCellEvaluationCommandConnectionV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialEvidenceRoleV1;
use crate::OriginalCellQ24MaterialReceiptFilesV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::OriginalCircuitRetainedVersionHostV1 as Version;
use crate::OriginalCircuitRetainedVersionRecoveryV1;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports as training_ports;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;

struct HeldPredecessors {
    dataset: OriginalCellQ24DatasetCommandReadbackV1,
    dataset_receipt: OriginalCellQ24MaterialCommandReceiptV1,
    trainer: OriginalCellQ24TrainingCommandConnectionV1,
    evaluator: OriginalCellEvaluationCommandConnectionV1,
}

struct HeldPeers {
    dataset: material_ports::Peer,
    trainer: TrainerPeer,
    evaluator: std::thread::JoinHandle<anyhow::Result<u64>>,
}

impl HeldPeers {
    fn finish(self) -> anyhow::Result<[u64; 3]> {
        Ok([
            material_ports::finish(self.dataset)?,
            self.trainer.join().expect("same original T readback")?,
            self.evaluator.join().expect("same original E readback")?,
        ])
    }
}

async fn held_predecessors(f: &PublicationFixture) -> anyhow::Result<(HeldPredecessors, HeldPeers)> {
    let (evaluator, evaluator_peer) = f.host.host.as_ref().context("same original E host")?
        .fixture_original_readback_connection()?;
    held_predecessors_with_evaluator(f, evaluator, evaluator_peer).await
}

async fn held_predecessors_with_evaluator(
    f: &PublicationFixture,
    evaluator: OriginalCellEvaluationCommandConnectionV1,
    evaluator_peer: std::thread::JoinHandle<anyhow::Result<u64>>,
) -> anyhow::Result<(HeldPredecessors, HeldPeers)> {
    let original = &f.host.original;
    let material = &original.command_config;
    let objective = material.initial.request.envelope.objective_digest;
    // The original fixture dropped these initialized Material owners after
    // completing the exact same pair. Recovery is permanently command-readonly;
    // the original files, freeze, keys, Source and Ledger are reused.
    let owners = OriginalCellQ24MaterialReceiptOwnersV1::recover(
        OriginalCellQ24MaterialReceiptFilesV1 {
            experience: opened(&original.root, "positive-experience", false)?,
            experience_witness: original_witness(&original.root, "positive-experience-witness", &material.scope, objective, false)?,
            dataset: opened(&original.root, "positive-dataset", false)?,
            dataset_witness: original_witness(&original.root, "positive-dataset-witness", &material.scope, objective, false)?,
        },
        material.clone(), SigningKey::from_bytes(&[44; 32]), SigningKey::from_bytes(&[45; 32]),
    )?;
    let host = Arc::new(owners.into_command_owner(
        f.original_source.as_ref().clone(), f.identity_a.clone(),
        Arc::clone(&original.ledger), Arc::clone(&original.baseline),
    )?);
    let (dataset, dataset_peer) = material_ports::commands_for_original(
        host, material.clone(), OriginalCellQ24MaterialEvidenceRoleV1::Dataset,
    )?;
    let dataset = dataset.into_original_dataset_readback(material)?;
    let dataset_receipt = dataset.readback().await?;
    assert_eq!(dataset_receipt.snapshot(), &f.trainer_context.dataset);
    assert_eq!(dataset_receipt.attestations(), &original.material_evidence);
    let (trainer, channel) = training_ports::recovered_peer(
        material.clone(), Some((f.training.receipt().clone(), f.training.attestation().clone())), Duration::from_secs(300),
    )?;
    let trainer_peer = commands::serve(Arc::clone(&f.trainer), channel);
    Ok((HeldPredecessors { dataset, dataset_receipt, trainer, evaluator },
        HeldPeers { dataset: dataset_peer, trainer: trainer_peer, evaluator: evaluator_peer }))
}

async fn publish_for_recovery(
    f: &mut PublicationFixture,
    original_dataset: &OriginalCellQ24MaterialCommandReceiptV1,
) -> anyhow::Result<(support::Session, OriginalCircuitRetainedVersionRecoveryV1)> {
    let (trainer, evaluator, peers) = f.clients()?;
    let inputs = f.inputs()?;
    let current = Arc::clone(&inputs.current);
    let artifacts = Arc::clone(&inputs.authorities.artifacts);
    let artifact_selection = inputs.selection.signed.clone();
    let artifact_verifier = inputs.selection.verifier.clone();
    let checkpoint = f.host.original.version.retained_artifact_checkpoint()?;
    let prepared = crate::prepare_original_circuit_evaluated_retention_v1(f.context()?, trainer, evaluator, inputs).await?;
    let intent = prepared.intent_digest();
    let grant = f.host.original.version.sign(prepared.final_use_binding())?;
    let (task, trainer, evaluator) = prepared.publish_and_retain_original_evidence(grant).await?;
    let c = f.start_c(task).await?;
    drop(trainer);
    drop(evaluator);
    peers.finish()?;
    let mut attestations = original_dataset.attestations().to_vec();
    attestations.push(f.training.attestation().clone());
    attestations.push(f.evaluation.attestation().clone());
    let recovery = OriginalCircuitRetainedVersionRecoveryV1 {
        training: f.evaluation.snapshot().clone(), attestations, intent_digest: intent,
        cell: c.cell.clone(), source: Arc::clone(&c.source), identity: c.runtime.identity.clone(),
        current, artifacts, artifact_checkpoint: checkpoint, artifact_selection, artifact_verifier,
    };
    Ok((c, recovery))
}

fn cold_version(
    f: &PublicationFixture,
    held: HeldPredecessors,
    recovery: OriginalCircuitRetainedVersionRecoveryV1,
) -> Result<Arc<Version>, crate::OriginalCircuitRetainedVersionErrorV1> {
    Ok(Arc::new(Version::recover_from_original_evaluated_owners(
        f.host.original.command_config.clone(), held.dataset, held.trainer, held.evaluator,
        recovery, Duration::from_secs(300),
    )?))
}

#[path = "circuit_evaluated_version_recovery_tests.rs"]
mod tests;

#[path = "circuit_evaluated_version_final_use_tests.rs"]
mod final_use_tests;
