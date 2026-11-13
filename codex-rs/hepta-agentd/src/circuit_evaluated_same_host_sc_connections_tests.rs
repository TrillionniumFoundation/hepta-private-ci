//! Two independent sets of real read-only predecessor channels for one
//! published original cut. Only the existing test transport differs from
//! deployment. No sealed bundle is constructed or modified by this fixture.

use super::*;
use anyhow::Context as _;

pub(super) async fn two_original_sets(
    fixture: &PublicationFixture,
) -> anyhow::Result<Vec<(HeldPredecessors, HeldPeers)>> {
    let evaluator_host = fixture.host.host.as_ref().context("same original E host")?;
    let original = &fixture.host.original;
    let material = &original.command_config;
    let objective = material.initial.request.envelope.objective_digest;
    // Recover the original completed Material once. Both Dataset channels
    // borrow this same actual host; never reopen a second active journal writer.
    let owners = OriginalCellQ24MaterialReceiptOwnersV1::recover(
        OriginalCellQ24MaterialReceiptFilesV1 {
            experience: opened(&original.root, "positive-experience", /*create*/ false)?,
            experience_witness: original_witness(
                &original.root,
                "positive-experience-witness",
                &material.scope,
                objective,
                /*create*/ false,
            )?,
            dataset: opened(&original.root, "positive-dataset", /*create*/ false)?,
            dataset_witness: original_witness(
                &original.root,
                "positive-dataset-witness",
                &material.scope,
                objective,
                /*create*/ false,
            )?,
        },
        material.clone(),
        SigningKey::from_bytes(&[44; 32]),
        SigningKey::from_bytes(&[45; 32]),
    )?;
    let host = Arc::new(owners.into_command_owner(
        fixture.original_source.as_ref().clone(),
        fixture.identity_a.clone(),
        Arc::clone(&original.ledger),
        Arc::clone(&original.baseline),
    )?);
    let mut all = Vec::new();
    for _ in 0..2 {
        let one: anyhow::Result<(HeldPredecessors, HeldPeers)> = async {
            let (connection, dataset_peer) = material_ports::commands_for_original(
                Arc::clone(&host),
                material.clone(),
                OriginalCellQ24MaterialEvidenceRoleV1::Dataset,
            )?;
            let dataset = match connection.into_original_dataset_readback(material) {
                Ok(dataset) => dataset,
                Err(error) => {
                    let cleanup = material_ports::finish(dataset_peer);
                    return Err(anyhow::Error::from(error)
                        .context(format!("original Dataset conversion cleanup: {cleanup:?}")));
                }
            };
            let dataset_receipt = match dataset.readback().await {
                Ok(receipt) => receipt,
                Err(error) => {
                    drop(dataset);
                    let cleanup = material_ports::finish(dataset_peer);
                    return Err(anyhow::Error::from(error)
                        .context(format!("original Dataset read cleanup: {cleanup:?}")));
                }
            };
            if dataset_receipt.snapshot() != &fixture.trainer_context.dataset
                || dataset_receipt.attestations() != original.material_evidence.as_slice()
            {
                drop(dataset);
                let cleanup = material_ports::finish(dataset_peer);
                anyhow::bail!(
                    "actual Dataset changed its complete original cut/signatures: {cleanup:?}"
                );
            }
            let trainer_setup = training_ports::recovered_peer(
                material.clone(),
                Some((
                    fixture.training.receipt().clone(),
                    fixture.training.attestation().clone(),
                )),
                Duration::from_secs(300),
            );
            let (trainer, channel) = match trainer_setup {
                Ok(pair) => pair,
                Err(error) => {
                    drop(dataset);
                    let cleanup = material_ports::finish(dataset_peer);
                    return Err(error.context(format!("original T channel cleanup: {cleanup:?}")));
                }
            };
            let trainer_peer = commands::serve(Arc::clone(&fixture.trainer), channel);
            let evaluator_setup = evaluator_host.fixture_original_readback_connection();
            let (evaluator, evaluator_peer) = match evaluator_setup {
                Ok(pair) => pair,
                Err(error) => {
                    drop(dataset);
                    drop(trainer);
                    let dataset_cleanup = material_ports::finish(dataset_peer);
                    let trainer_cleanup = trainer_peer
                        .join()
                        .map_err(|_| anyhow::anyhow!("actual T peer panicked"));
                    return Err(error.context(format!(
                        "original E setup cleanup: {dataset_cleanup:?}; {trainer_cleanup:?}"
                    )));
                }
            };
            let actual = HeldPredecessors {
                dataset,
                dataset_receipt,
                trainer,
                evaluator,
            };
            let peers = HeldPeers {
                dataset: dataset_peer,
                trainer: trainer_peer,
                evaluator: evaluator_peer,
            };
            Ok((actual, peers))
        }
        .await;
        match one {
            Ok(value) => all.push(value),
            Err(error) => {
                let mut errors = Vec::new();
                for (held, peers) in all {
                    drop(held);
                    collect_peer_cleanup(peers, &mut errors);
                }
                return Err(
                    error.context(format!("original duplicate-channel cleanup: {errors:?}"))
                );
            }
        }
    }
    Ok(all)
}

pub(super) fn collect_peer_cleanup(peers: HeldPeers, errors: &mut Vec<String>) {
    let dataset = material_ports::finish(peers.dataset);
    let trainer = peers
        .trainer
        .join()
        .map_err(|_| anyhow::anyhow!("original T peer panicked"))
        .and_then(|result| result.map_err(anyhow::Error::from));
    let evaluator = peers
        .evaluator
        .join()
        .map_err(|_| anyhow::anyhow!("original E peer panicked"))
        .and_then(|result| result);
    for result in [dataset, trainer, evaluator] {
        if let Err(error) = result {
            errors.push(error.to_string());
        }
    }
}
