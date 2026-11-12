//! Existing actual A/T/Ineligible B and original S/C owners over the command
//! codecs. Only same-process transport admission and enrolled keys are fixture
//! inputs; no response, opaque cut, ordinary deployment or new grant is made.

use super::*;
use anyhow::Context as _;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadErrorV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::OriginalCircuitNextUseCommandContextV1 as CContext;
use crate::OriginalCircuitNextUseCommandErrorV1 as CError;
use crate::OriginalCircuitSelectionCommandContextV1 as SContext;
use crate::OriginalCircuitSelectionCommandErrorV1 as SError;
use crate::circuit_feature_current::original_learning_read_fixture as reads;
use crate::learning_iteration_evidence_client::next_use_command_test_support as c_commands;
use crate::learning_iteration_evidence_client::selection_command_test_support as s_commands;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

fn published_reader(
    c: &support::Session,
    context: ReadContext,
) -> anyhow::Result<(
    OriginalCircuitLearningReadClientV1,
    std::thread::JoinHandle<Result<u64, OriginalCircuitLearningReadErrorV1>>,
)> {
    let owner = Arc::new(OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
        c.cell.clone(), c.source.as_ref().clone(), c.runtime.identity.clone(), context.clone(),
    )?);
    let (client, channel) = reads::evaluated_client(context)?;
    Ok((client, reads::serve(owner, channel)))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_s_c_commands_keep_original_owners_full_cuts_and_cold_read_only()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, s_predecessor_peers) = Box::pin(published(&mut f)).await?;
    let (s_live, s_live_peer) = published_reader(&c, ReadContext::for_original_selection(f.readback_context()?)?)?;
    let s_files = SelectorFiles::new()?;
    let selector = s_files.owner(&f, OpenReceipt::Fresh)?;
    let empty_s = s_files.bytes()?;
    let s_context = SContext::from_original_evaluation(
        f.host.config.scope.clone(), f.host.config.signing.verifier.clone(), &f.training, &f.evaluation,
    )?;
    // The actual changed Candidate T cannot enter the legacy three-cut path.
    assert!(matches!(SContext::from_original_training(
        f.trainer_context.dataset.clone(), f.host.config.scope.clone(),
        f.host.config.signing.verifier.clone(), &f.training,
    ), Err(SError::Binding("strict original TrainingNoUpdate command profile"))));
    let s_host = Arc::new(selector.into_evaluated_command_owner(s_live, trainer, evaluator)?);
    s_commands::reject_wrong_context(&s_host)?;
    let (s_client, s_channel) = s_commands::client(s_context.clone(), false, None)?;
    let s_peer = s_commands::serve(Arc::clone(&s_host), s_channel);
    let selected = s_client.execute_selection().await?;
    assert_eq!(selected.snapshot().receipts.len(), 5);
    assert_eq!(&selected.snapshot().receipts[..4], &f.evaluation.snapshot().receipts);
    assert_eq!(selected.training_attestation(), f.training.attestation());
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let committed_s = s_files.bytes()?;
    assert_ne!(committed_s, empty_s);
    assert_eq!(s_client.readback().await?, selected);
    assert!(matches!(s_client.execute_selection().await, Err(SError::ReadbackRequired)));
    assert_eq!(s_files.bytes()?, committed_s);
    // The original authenticated command receipt alone carries the opaque S.
    let sealed_s = selected.evaluated_receipt()?;
    assert_eq!(sealed_s.snapshot(), selected.snapshot());
    assert_eq!(sealed_s.attestation(), selected.attestation());
    assert!(matches!(CContext::from_original_selection(
        f.host.config.scope.clone(), f.host.config.signing.verifier.clone(), &selected,
    ), Err(CError::Binding("strict original TrainingNoUpdate C profile"))));

    let publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    let (c_trainer, c_evaluator, c_predecessor_peers) = f.clients()?;
    let (s_evidence, s_evidence_channel) = s_commands::evidence_client(&s_context)?;
    let s_evidence_peer = s_commands::serve_evidence(Arc::clone(&s_host), s_evidence_channel);
    let (c_live, c_live_peer) = published_reader(&c, ReadContext::for_original_next_use(sealed_s.clone())?)?;
    let c_files = SelectorFiles::new()?;
    let original_observer = observer(&c_files, &f, &sealed_s, OpenReceipt::Fresh)?;
    let empty_c = c_files.bytes()?;
    let c_host = Arc::new(original_observer.into_evaluated_command_owner(c_live, c_trainer, c_evaluator, s_evidence)?);
    c_commands::reject_wrong_context(&c_host)?;
    let c_context = CContext::from_original_evaluated_selection(&sealed_s)?;
    let (c_client, c_channel) = c_commands::client(c_context, false, None)?;
    let c_peer = c_commands::serve(Arc::clone(&c_host), c_channel);
    let completed = c_client.attest_completed_task().await?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(&completed.snapshot().receipts[..5], &selected.snapshot().receipts);
    assert_eq!(completed.training_attestation(), f.training.attestation());
    assert_eq!(completed.selection_attestation(), selected.attestation());
    assert!(matches!(&completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if *retained_bundle == f.bundle.digest()?));
    let committed_c = c_files.bytes()?;
    assert_ne!(committed_c, empty_c);
    assert_eq!(c_client.readback().await?, completed);
    assert!(matches!(c_client.attest_completed_task().await, Err(CError::ReadbackRequired)));
    assert_eq!(c_files.bytes()?, committed_c);
    drop(c_client);
    assert_eq!(c_peer.join().expect("original evaluated C command")?, 2);
    drop(c_host);
    assert!(c_live_peer.join().expect("same original C current reader")? > 0);
    assert!(s_evidence_peer.join().expect("same original S evidence")? > 0);
    assert!(c_predecessor_peers.finish()?.iter().all(|count| *count > 0));

    // Reopen only the same initialized original C journal. The fresh-shaped
    // fixture request deliberately probes the recovered server's once bit;
    // its opaque context has already been attenuated to read-only.
    let cold_s = sealed_s.clone().into_original_receipt_readback();
    let recovered_observer = observer(&c_files, &f, &sealed_s, OpenReceipt::Readback)?;
    let (cold_trainer, cold_evaluator, cold_predecessor_peers) = f.clients()?;
    let (cold_s_evidence, cold_s_channel) = s_commands::evidence_client(&s_context)?;
    let cold_s_peer = s_commands::serve_evidence(Arc::clone(&s_host), cold_s_channel);
    let (cold_live, cold_live_peer) = published_reader(&c, ReadContext::for_original_next_use(cold_s.clone())?)?;
    let cold_host = Arc::new(recovered_observer.into_evaluated_command_owner(cold_live, cold_trainer, cold_evaluator, cold_s_evidence)?);
    let (cold_client, cold_channel) = c_commands::client(CContext::from_original_evaluated_selection(&cold_s)?, false, None)?;
    let cold_peer = c_commands::serve(Arc::clone(&cold_host), cold_channel);
    assert!(matches!(cold_client.attest_completed_task().await, Err(CError::ReadbackRequired)));
    let read = cold_client.readback().await?;
    assert_eq!(read, completed);
    assert!(matches!(read.evaluated_selection().context("same cold S")?
        .original_context().require_new_original_receipt(now()?),
        Err(PublicationError::Binding("recovered evaluated retention is read-only"))));
    assert_eq!(c_files.bytes()?, committed_c);
    assert_eq!(s_files.bytes()?, committed_s);
    drop(cold_client);
    assert_eq!(cold_peer.join().expect("cold original C command")?, 2);
    drop(cold_host);
    assert!(cold_live_peer.join().expect("cold original task reader")? > 0);
    assert!(cold_s_peer.join().expect("cold original S evidence")? > 0);
    assert!(cold_predecessor_peers.finish()?.iter().all(|count| *count > 0));
    drop(s_client);
    assert_eq!(s_peer.join().expect("original evaluated S command")?, 2);
    drop(s_host);
    assert!(s_live_peer.join().expect("same original published task")? > 0);
    assert!(s_predecessor_peers.finish()?.iter().all(|count| *count > 0));
    c.stop().await?;
    drop(c);
    f.finish().await
}
