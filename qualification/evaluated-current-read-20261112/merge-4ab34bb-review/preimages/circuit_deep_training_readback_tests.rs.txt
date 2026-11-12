//! Deep SourceBound Training -> original S -> ordinary C readback mechanisms.
//! All facts use the same actual A. Credentials, independent terminal Outcome
//! and version/FinalUse admission are test custody, not a deployed ordinary loop.
use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::OriginalCircuitNextUseCommandContextV1;
use crate::OriginalCircuitNextUseCommandErrorV1;
use crate::OriginalCircuitSelectionCommandContextV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::OriginalCircuitSelectionRemoteSourcesV1;
use crate::learning_iteration_evidence_client::next_use_command_test_support as next_command;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports as trainer_ports;
use crate::learning_iteration_evidence_client::original_readback_test_ports as selector_ports;
use crate::learning_iteration_evidence_client::selection_command_test_support as selection_command;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "circuit_deep_training_readback_support_tests.rs"]
mod original;
use original::DeepFixture;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources()
-> anyhow::Result<()> {
    let started = std::time::Instant::now();
    let mut f = DeepFixture::ready().await?;
    let original_bytes = f.original_bytes()?;
    let context = OriginalCircuitSelectionCommandContextV1::from_original_training(
        f.dataset.snapshot().clone(),
        f.material.scope.clone(),
        f.material.verifier.clone(),
        &f.training,
    )?;
    let original::InitialTrainer {
        connection: trainer,
        server: trainer_s,
    } = f.trainer_for_s.take().expect("initial original T for S");
    let (published, published_s) = f.published(f.training_cut.clone(), /*selection*/ None)?;
    let selector = Arc::new(f.selector()?.into_command_owner_from_original_readbacks(
        published,
        trainer,
        f.dataset.clone(),
        f.training.clone(),
    )?);
    let (client, channel) = selection_command::client(
        context, /*readback_only*/ false, /*retained*/ None,
    )?;
    let server = selection_command::serve(Arc::clone(&selector), channel);
    let selected = client.execute_selection().await?;
    assert_eq!(selected.training_attestation(), f.training.attestation());
    assert_eq!(selected.snapshot().receipts.len(), 4);
    drop(client);
    assert_eq!(
        server
            .join()
            .map_err(|_| anyhow::anyhow!("actual S command"))??,
        1
    );
    let selector_bytes = f.receipt_bytes("selector")?;

    let original::InitialSelector {
        connection: selector_read,
        channel,
    } = f.selector_for_c.take().expect("initial original S for C");
    let selector_c = selector_ports::serve(Arc::clone(&selector), channel);
    let original::InitialTrainer {
        connection: trainer,
        server: trainer_c,
    } = f.trainer_for_c.take().expect("initial original T for C");
    let observer_config = f.observer_config(&selected);
    let (published, published_c) = f.published(
        selected.snapshot().clone(),
        Some(selected.attestation().clone()),
    )?;
    let observer = Arc::new(
        f.observer(&observer_config, /*create*/ true)?
            .into_command_owner_from_original_readbacks(
                published,
                trainer,
                selector_read,
                f.dataset.clone(),
                f.training.clone(),
                selected.clone(),
            )?,
    );
    // The Observer does not execute C. This different request/session/input
    // runs through the ordinary feature task and consumes the retained model.
    let completed_c = execute(&f.session, /*request_id*/ 1).await?;
    let decision = read_receipt(&f.session, &f.definition, &completed_c)?;
    assert_ne!(
        completed_c.input().scope.run_id,
        f.previous.input().scope.run_id
    );
    assert_ne!(
        completed_c.input().observation,
        f.previous.input().observation
    );
    assert_eq!(
        decision.bundle_digest,
        f.material.initial.request.selected_bundle.digest()?
    );
    let context = OriginalCircuitNextUseCommandContextV1::from_original_selection(
        f.material.scope.clone(),
        f.material.verifier.clone(),
        &selected,
    )?;
    let (client, channel) = next_command::client(
        context.clone(),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let server = next_command::serve(Arc::clone(&observer), channel);
    let saved = client.attest_completed_task().await?;
    assert_eq!(saved.snapshot().receipts.len(), 5);
    let observer_bytes = f.receipt_bytes("observer")?;
    assert_eq!(client.readback().await?, saved);
    assert_eq!(f.original_bytes()?, original_bytes);
    assert_eq!(f.receipt_bytes("selector")?, selector_bytes);
    assert_eq!(f.receipt_bytes("observer")?, observer_bytes);
    drop(client);
    assert_eq!(
        server
            .join()
            .map_err(|_| anyhow::anyhow!("actual C command"))??,
        2
    );
    drop(observer);
    assert_eq!(
        published_c
            .join()
            .map_err(|_| anyhow::anyhow!("actual C publication"))??,
        5
    );
    assert_eq!(
        selector_c
            .join()
            .map_err(|_| anyhow::anyhow!("actual S readback for C"))??,
        4
    );
    assert_eq!(
        trainer_c
            .join()
            .map_err(|_| anyhow::anyhow!("actual T readback for C"))??,
        4
    );

    // Reopen only the same Observer files/witness. Its incoming T/S channels
    // were already bound before Dataset/T, and cannot receive a fresh lifetime.
    let original::InitialSelector {
        connection: selector_read,
        channel,
    } = f.selector_for_cold_c.take().expect("initial S for cold C");
    let selector_cold = selector_ports::serve(Arc::clone(&selector), channel);
    let original::InitialTrainer {
        connection: trainer,
        server: trainer_cold,
    } = f.trainer_for_cold_c.take().expect("initial T for cold C");
    let (published, published_cold) = f.published(
        selected.snapshot().clone(),
        Some(selected.attestation().clone()),
    )?;
    let recovered = Arc::new(
        f.observer(&observer_config, /*create*/ false)?
            .into_command_owner_from_original_readbacks(
                published,
                trainer,
                selector_read,
                f.dataset.clone(),
                f.training.clone(),
                selected,
            )?,
    );
    let (client, channel) =
        next_command::client(context, /*readback_only*/ true, Some(saved.clone()))?;
    let server = next_command::serve(Arc::clone(&recovered), channel);
    assert_eq!(client.readback().await?, saved);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(f.original_bytes()?, original_bytes);
    assert_eq!(f.receipt_bytes("selector")?, selector_bytes);
    assert_eq!(f.receipt_bytes("observer")?, observer_bytes);
    drop(client);
    assert_eq!(
        server
            .join()
            .map_err(|_| anyhow::anyhow!("cold original C command"))??,
        1
    );
    drop(recovered);
    assert_eq!(
        published_cold
            .join()
            .map_err(|_| anyhow::anyhow!("cold C publication"))??,
        2
    );
    assert_eq!(
        selector_cold
            .join()
            .map_err(|_| anyhow::anyhow!("cold original S"))??,
        2
    );
    assert_eq!(
        trainer_cold
            .join()
            .map_err(|_| anyhow::anyhow!("cold original T"))??,
        2
    );
    drop(selector);
    assert_eq!(
        published_s
            .join()
            .map_err(|_| anyhow::anyhow!("original S publication"))??,
        15
    );
    assert_eq!(
        trainer_s
            .join()
            .map_err(|_| anyhow::anyhow!("original S Trainer"))??,
        14
    );
    let counts = f.finish().await?;
    assert_eq!(counts[0], 1, "the original Dataset bootstrap is read once");
    assert_eq!(
        counts[1], counts[2],
        "same original Source/Experience sessions"
    );
    assert_eq!(
        counts[2], counts[3],
        "same original Experience/Dataset sessions"
    );
    // The twenty real T readbacks each bracket native/Generator CURRENT with
    // two live captures; each capture reads every original Material peer twice.
    // Bootstrap/fit may add reads. Do not replace the actual lower bound with
    // a cached receipt, accept a timeout, or pin an incidental exact total.
    assert!(counts[1] >= 80);
    assert!(counts[1..].iter().all(|count| *count < 128));
    eprintln!(
        "HEPTA_DEEP_S_C_READONLY elapsed_ms={} training_reads=20 selector_reads=6 c_commands=3",
        started.elapsed().as_millis()
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn q24_deep_original_post_commit_training_change_fences_selector_without_resigning()
-> anyhow::Result<()> {
    let mut f = DeepFixture::ready().await?;
    let original_bytes = f.original_bytes()?;
    let (initial, channel) = f
        .trainer_fault
        .take()
        .expect("original pre-D fault channel");
    let faulty_peer = trainer_ports::renew_second_actual_read(
        Arc::clone(&f.trainer),
        channel,
        f.training.clone(),
    );
    let faulty = initial.bind_original_training(f.dataset.clone(), f.training.clone())?;
    let (published, published_peer) =
        f.published(f.training_cut.clone(), /*selection*/ None)?;
    let mut selector = f.selector()?;
    let before = f.receipt_bytes("selector")?;
    let result = selector
        .attest_original_remote_selection(OriginalCircuitSelectionRemoteSourcesV1 {
            snapshot: &f.training_cut,
            live: &published,
            trainer: &faulty,
        })
        .await;
    assert!(matches!(
        result,
        Err(OriginalCircuitSelectionReceiptErrorV1::Connection(_))
    ));
    drop(faulty);
    assert_eq!(
        faulty_peer
            .join()
            .map_err(|_| anyhow::anyhow!("actual post-commit renewal"))??,
        2
    );
    let committed = f.receipt_bytes("selector")?;
    assert_ne!(
        committed, before,
        "original effect precedes the rejected post-read"
    );
    assert_eq!(f.original_bytes()?, original_bytes);

    // A different, already prebound valid predecessor cannot un-fence the hot
    // receipt owner. Both reads fail before any request on this valid channel.
    let original::InitialTrainer { connection, server } =
        f.trainer_for_s.take().expect("original valid T");
    let valid = connection.bind_original_training(f.dataset.clone(), f.training.clone())?;
    assert!(matches!(
        selector
            .readback_remote(OriginalCircuitSelectionRemoteSourcesV1 {
                snapshot: &f.training_cut,
                live: &published,
                trainer: &valid,
            })
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert!(matches!(
        selector
            .attest_original_remote_selection(OriginalCircuitSelectionRemoteSourcesV1 {
                snapshot: &f.training_cut,
                live: &published,
                trainer: &valid,
            })
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(f.receipt_bytes("selector")?, committed);
    drop(selector);

    // Explicit cold recovery can only read the physically completed original
    // signature. It neither repeats the claim nor renews the result's window.
    let mut recovered = OriginalCircuitSelectionReceiptOwnerV1::recover(
        opened(&f.root, "deep-selector", /*create*/ false)?,
        original_witness(
            &f.root,
            "deep-selector-witness",
            &f.material.scope,
            f.material.initial.request.envelope.objective_digest,
            /*create*/ false,
        )?,
        f.selector_config.clone(),
        SigningKey::from_bytes(&[46; 32]),
    )?;
    let saved = recovered
        .readback_remote(OriginalCircuitSelectionRemoteSourcesV1 {
            snapshot: &f.training_cut,
            live: &published,
            trainer: &valid,
        })
        .await?;
    assert_eq!(saved.0.actor_id, f.training_cut.owners.selector);
    assert_eq!(saved.0.observed_unix_seconds, saved.1.issued_at);
    assert_eq!(f.receipt_bytes("selector")?, committed);
    assert_eq!(f.original_bytes()?, original_bytes);
    drop(recovered);
    drop(valid);
    assert_eq!(
        server
            .join()
            .map_err(|_| anyhow::anyhow!("only two cold original T reads"))??,
        2
    );
    drop(published);
    assert_eq!(
        published_peer
            .join()
            .map_err(|_| anyhow::anyhow!("original S publication after fence"))??,
        5
    );
    f.finish().await?;
    Ok(())
}
