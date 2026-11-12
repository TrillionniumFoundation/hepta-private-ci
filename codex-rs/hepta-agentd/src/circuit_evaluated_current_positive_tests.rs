//! Original retained CURRENT readbacks after actual native Candidate training
//! and independent NoUpdate Evaluation. Existing same-process transports and
//! explicit test issuers remain fixtures. Readback-origin proof is not a Root
//! or daemon restart, and this test performs no ordinary C execution.

use std::sync::Arc;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as read_transport;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_retained_current_reads_fresh_and_cold_original_owners() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let context = f.context()?;
    assert_eq!(context.snapshot(), f.evaluation.snapshot());
    assert_eq!(&context.snapshot().receipts[2], f.training.receipt());
    assert_eq!(
        f.evaluation.training_attestation(),
        f.training.attestation()
    );
    assert!(context.snapshot().training_no_update_v2().is_none());
    assert!(matches!(
        f.training.receipt().observation,
        LearningIterationObservationV1::Training { .. }
    ));
    assert!(matches!(
        f.evaluation.receipt().observation,
        LearningIterationObservationV1::Evaluation {
            disposition: LearningEvaluationDispositionV1::NoUpdate,
            ..
        }
    ));
    assert_ne!(f.bundle.digest()?, f.host.original.candidate.digest()?);
    let source_before = f.host.original.predecessor_bytes()?;
    let b_before = f.host.upstream_files()?;
    let evaluation_before = f.host.original_files()?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    let (trainer, evaluator, peers) = f.clients()?;
    let prepared = Box::pin(prepare_original_circuit_evaluated_retention_v1(
        context,
        trainer,
        evaluator,
        f.inputs()?,
    ))
    .await?;
    assert_eq!(
        prepared.final_use_binding().destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let signed = f.host.original.version.sign(prepared.final_use_binding())?;
    let (task, trainer, evaluator) = prepared
        .publish_and_retain_original_evidence(signed)
        .await?;
    assert_ne!(f.source_a.scope.run_id, task.source().scope.run_id);
    let mut c = f.start_c(task).await?;
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let baseline = f.bundle.digest()?;
    let publication_before = f.publication_bytes()?;
    let c_paths = [
        "q24-source.journal",
        "q24-source.witness",
        "q24-cell.journal",
        "q24-cell.witness",
    ]
    .map(|name| c.runtime.identity.home_root.join(name));
    let c_before = c_paths
        .iter()
        .map(std::fs::read)
        .collect::<std::io::Result<Vec<_>>>()?;
    let mut previous_read = None;
    for readback in [false, true] {
        let context = || {
            if readback {
                f.readback_context()
            } else {
                f.context()
            }
        };
        let owner = Arc::new(
            OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
                c.cell.clone(),
                c.source.as_ref().clone(),
                c.runtime.identity.clone(),
                context()?,
            )?,
        );
        let (client, server) = read_transport::evaluated_client(context()?)?;
        let peer = read_transport::serve(owner, server);
        let first = client.read_current().await?;
        assert!(matches!(
            first.observation(),
            LearningIterationObservationV1::Selection { candidate_bundle, .. }
                if *candidate_bundle == baseline
        ));
        assert_eq!(client.read_current().await?, first);
        if let Some(previous) = previous_read.replace(first.clone()) {
            assert_eq!(previous, first);
        }
        drop(client);
        assert_eq!(peer.join().expect("original CURRENT read peer")?, 2);
    }
    assert_eq!(trainer.readback().await?, f.training);
    assert_eq!(evaluator.readback().await?, f.evaluation);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [5, 5]);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    assert_eq!(f.publication_bytes()?, publication_before);
    assert_eq!(
        c_paths
            .iter()
            .map(std::fs::read)
            .collect::<std::io::Result<Vec<_>>>()?,
        c_before
    );
    assert_eq!(f.host.original.predecessor_bytes()?, source_before);
    assert_eq!(f.host.upstream_files()?, b_before);
    assert_eq!(f.host.original_files()?, evaluation_before);
    c.stop().await?;
    drop(c);
    f.finish().await
}
