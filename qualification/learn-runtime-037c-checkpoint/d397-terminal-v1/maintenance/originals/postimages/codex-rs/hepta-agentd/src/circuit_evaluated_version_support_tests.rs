//! Same-A native D/T/B and actual baseline C. Keys, same-process transport and
//! B member measurement peers remain explicit fixtures, not ordinary proof.
use super::super::version_material::OriginalDataset;
use super::super::version_material::original_dataset;
use super::*;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use crate::OriginalCircuitRetainedVersionHostV1 as VersionHost;
use crate::circuit_feature_current::evaluated_readiness_fixture as readiness;
use pretty_assertions::assert_eq;
use std::time::Duration;

type ReadOwner = OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

fn task_reader(
    c: &support::Session,
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
) -> anyhow::Result<Arc<ReadOwner>> {
    Ok(Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        ReadContext::for_original_next_use(selection)?,
    )?))
}

fn c_bytes(c: &support::Session) -> anyhow::Result<Vec<Vec<u8>>> {
    [
        "q24-source.journal",
        "q24-source.witness",
        "q24-cell.journal",
        "q24-cell.witness",
    ]
    .into_iter()
    .map(|name| Ok(std::fs::read(c.runtime.identity.home_root.join(name))?))
    .collect()
}

async fn published_and_selected(
    f: &mut PublicationFixture,
) -> anyhow::Result<(
    support::Session,
    SelectorFiles,
    OriginalCircuitEvaluatedSelectionReceiptV1,
)> {
    let (c, trainer, evaluator, peers) = Box::pin(published(f)).await?;
    let files = SelectorFiles::new()?;
    let mut selector = files.owner(f, OpenReceipt::Fresh)?;
    let selected = selector
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    assert_eq!(
        &selected.snapshot().receipts[..4],
        &f.evaluation.snapshot().receipts
    );
    assert_eq!(selected.snapshot().receipts.len(), 5);
    drop(selector);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [6, 6]);
    Ok((c, files, selected))
}

fn initial_version_connections(
    f: &PublicationFixture,
    material: &crate::OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingCommandConnectionV1,
    crate::OriginalCellEvaluationCommandConnectionV1,
    Peers,
)> {
    let (trainer, trainer_peer) = commands::original_version_training_readback_connection(
        material.clone(),
        Arc::clone(&f.trainer),
    )?;
    let (evaluator, evaluator_peer) = f
        .host
        .host
        .as_ref()
        .expect("original B host")
        .fixture_original_version_connection()?;
    Ok((
        trainer,
        evaluator,
        Peers {
            trainer: trainer_peer,
            evaluator: evaluator_peer,
        },
    ))
}

fn finish_dataset(original: OriginalDataset) -> anyhow::Result<()> {
    drop(original.readback);
    assert_eq!(
        original.peer.join().expect("same original Dataset peer")?,
        1
    );
    Ok(())
}

#[path = "circuit_evaluated_version_capacity_tests.rs"]
mod capacity;
#[path = "circuit_evaluated_completion_readiness_tests.rs"]
mod completion;
#[path = "circuit_evaluated_version_issuer_tests.rs"]
mod issuer;
#[path = "circuit_evaluated_version_recovery_tests.rs"]
mod recovery;
