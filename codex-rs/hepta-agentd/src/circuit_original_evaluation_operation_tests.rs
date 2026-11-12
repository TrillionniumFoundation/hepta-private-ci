//! Actual socket reads and original B/retention journals, with explicit fixture
//! credentials and Product declarations. Both panels remain Ineligible; these
//! are operation mechanisms, not ordinary adoption or daemon restart evidence.
use std::sync::Arc;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::learning_iteration_evidence_client::fixture_original_receipt_sequence_until_close;

fn install(
    fixture: &mut HostFixture,
    signatures: Vec<codex_hepta_learning_ledger::SignedLearningEvidenceV1>,
) -> anyhow::Result<std::thread::JoinHandle<anyhow::Result<usize>>> {
    let (trainer, peer) = fixture_original_receipt_sequence_until_close(
        fixture.original.initial.clone(),
        fixture.config.training.receipts[2].clone(),
        fixture.config.signing.verifier.clone(),
        signatures,
    )?;
    Arc::get_mut(fixture.host.as_mut().expect("original host"))
        .expect("no external original host reference")
        .fixture_shared_training_operation(Arc::new(trainer))?;
    Ok(peer)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_operation_reads_two_trainers_per_call_and_whole_export()
-> anyhow::Result<()> {
    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let signature = fixture.original.config.training_evidence.clone();
    let trainer = install(&mut fixture, vec![signature])?;
    let upstream = fixture.upstream_files()?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    let evaluation = client.execute_evaluation().await?;
    assert_eq!(client.readback().await?, evaluation);
    assert_eq!(finish(client, peer)?, 2);
    let completed = fixture.original_files()?;
    let (material, peer) = fixture
        .host
        .as_ref()
        .unwrap()
        .fixture_model_material_commands(Some(evaluation.clone()), "original", /*pause*/ None)?;
    let exported = material.fixture_read_current_at(fixture.at).await?;
    assert_eq!(exported.original_evaluation(), &evaluation);
    exported.fixture_original_material_preimages(fixture.at)?;
    let operation = material.fixture_begin_model_read_at(fixture.at).await?;
    assert_eq!(operation.material().binding(), exported.binding());
    assert!(matches!(material.read_current().await, Err(CommandError::Unavailable)));
    let staged = operation.fixture_finish_at(fixture.at).await?;
    assert_eq!(staged.binding(), exported.binding());
    assert_eq!(staged.original_evaluation(), &evaluation);
    drop(material);
    assert_eq!(
        peer.join().expect("original material peer")?,
        2 * (exported.fixture_original_material_pages() as u64 + 1)
    );
    assert_eq!(fixture.upstream_files()?, upstream);
    assert_eq!(fixture.original_files()?, completed);
    // The original retention Outcome remains an actual independent read.
    fixture.retention_b.withdraw_target()?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ true, Some(evaluation), "original",
    )?;
    assert!(client.readback().await.is_err());
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.original_files()?, completed);
    // Two independent successful E commands: 2 + 2. Each complete or staged
    // material transfer is one actual T-before/T-after operation: 2 + 2.
    // Withdrawal fails after its T-before. No overlap obtains another channel.
    assert_eq!(fixture.finish().await?, [2, 2]);
    assert_eq!(trainer.join().expect("original shared Trainer")?, 9);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_operation_rejects_equal_evidence_on_another_connection()
-> anyhow::Result<()> {
    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    Arc::get_mut(fixture.host.as_mut().unwrap())
        .unwrap()
        .fixture_distinct_operation_member()?;
    let empty = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    assert!(client.execute_evaluation().await.is_err());
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.original_files()?, empty);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert_eq!(fixture.finish().await?, [3, 2]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_operation_changed_tail_preserves_effect_and_fences_retry()
-> anyhow::Result<()> {
    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let signature = fixture.original.config.training_evidence.clone();
    let renewed = fixture.original.evaluation.renewed_qualification_training()?;
    assert_ne!(signature, renewed);
    let trainer = install(&mut fixture, vec![signature, renewed])?;
    let empty = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    assert!(client.execute_evaluation().await.is_err());
    assert_eq!(finish(client, peer)?, 1);
    let completed = fixture.original_files()?;
    assert_ne!(completed, empty, "the real E effect precedes the failed T-after");
    let (client, peer) = fixture.commands(
        /*readback_only*/ true, /*expected*/ None, "original",
    )?;
    assert!(matches!(client.readback().await, Err(CommandError::CommitUncertain)));
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.original_files()?, completed);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert_eq!(fixture.finish().await?, [2, 2]);
    assert_eq!(trainer.join().expect("original changed Trainer")?, 2);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_staged_material_drop_and_withdrawal_never_restore_channel()
-> anyhow::Result<()> {
    for fault in ["drop", "withdraw", "changed-tail"] {
        let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
        let signature = fixture.original.config.training_evidence.clone();
        let signatures = if fault == "changed-tail" {
            let renewed = fixture.original.evaluation.renewed_qualification_training()?;
            assert_ne!(signature, renewed);
            vec![signature.clone(), signature.clone(), signature, renewed]
        } else { vec![signature] };
        let trainer = install(&mut fixture, signatures)?;
        let (client, peer) = fixture.commands(
            /*readback_only*/ false, /*expected*/ None, "original",
        )?;
        let evaluation = client.execute_evaluation().await?;
        assert_eq!(finish(client, peer)?, 1);
        let completed = fixture.original_files()?;
        let (material, peer) = fixture
            .host
            .as_ref()
            .unwrap()
            .fixture_model_material_commands(Some(evaluation), "original", /*pause*/ None)?;
        let operation = material.fixture_begin_model_read_at(fixture.at).await?;
        let pages = operation.material().fixture_original_material_pages() as u64;
        if fault == "drop" {
            drop(operation);
        } else {
            if fault == "withdraw" { fixture.retention_b.withdraw_target()?; }
            assert!(operation.fixture_finish_at(fixture.at).await.is_err());
        }
        assert!(matches!(material.read_current().await, Err(CommandError::Unavailable)));
        drop(material);
        let served = peer.join().expect("original staged material peer");
        assert!(pages > 0);
        assert!(served.is_err(), "unfinished/failed transfer keeps the original owner fenced");
        let (probe, peer) = fixture.commands(
            /*readback_only*/ true, /*expected*/ None, "original",
        )?;
        assert!(matches!(probe.readback().await, Err(CommandError::CommitUncertain)));
        assert_eq!(finish(probe, peer)?, 1);
        assert_eq!(fixture.original_files()?, completed);
        assert_eq!(fixture.finish().await?, [2, 2]);
        assert_eq!(trainer.join().expect("original staged Trainer")?, if fault == "changed-tail" { 4 } else { 3 });
    }
    Ok(())
}
