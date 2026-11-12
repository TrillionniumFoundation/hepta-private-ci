//! Real original Material/Trainer handlers with explicit same-UID test custody.
//! No Root gate, independent B/retention result or adoption grant is fabricated.
use super::*;
use crate::LearningIterationRuntimeErrorV1 as StageError;
use crate::LearningIterationStageOwnerPortsV1;
use crate::OriginalCellEvaluationPanelRegistrationV1 as Registration;
use crate::OriginalCellEvaluationPanelTaskV1 as Task;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as MaterialRole;
use crate::learning_iteration_evidence_client as stages;
use crate::learning_iteration_evidence_client::material::bootstrap_ports as material_ports;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::time::Instant;

fn protocol(rule: &str) -> anyhow::Result<Registration> {
    Ok(Registration::new(
        Task {
            plan_id: StableId::new("original-primary-B")?,
            task_digest: Digest32::of_bytes(b"original-primary-B-task"),
            cohort_rule_digest: Digest32::of_bytes(rule.as_bytes()),
        },
        vec![Task {
            plan_id: StableId::new("original-retention-R")?,
            task_digest: Digest32::of_bytes(b"original-retention-R-task"),
            cohort_rule_digest: Digest32::of_bytes(b"original-retention-fold-and-unit-rule"),
        }],
    )?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn candidate_stage_reads_actual_candidate_from_same_three_original_owners()
-> anyhow::Result<()> {
    // Canonical B/retention registration is fixed before the actual A source,
    // original freeze signature, batch, optimizer rule and Training scope.
    let registered = protocol("original-primary-fold-and-unit-rule")?;
    let fixture = MaterialCommandFixture::candidate_pages_for_evaluation_profile(
        registered.evaluation_profile(),
    )
    .await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let end = Instant::now() + Duration::from_secs(300);
    let (candidate_connection, candidate_peer) = page_peer(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Recovered,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let (training_connection, training_server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Duration::from_secs(300),
    )?;
    let (experience, e_peer) = material_ports::commands(&fixture, MaterialRole::Experience)?;
    let (dataset, d_peer) = material_ports::commands(&fixture, MaterialRole::Dataset)?;
    let cut = complete_material(&fixture).await?;
    let trainer = training_connection.bind_original_dataset(cut.clone())?;
    let training = trainer
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(cut.snapshot().clone())?;
    coordinator.record(
        training.receipt().clone(),
        training.receipt().observed_unix_seconds,
    )?;
    let snapshot = coordinator.snapshot().clone();
    assert_eq!(snapshot.receipts.len(), 3);
    assert!(coordinator.candidate().is_some());
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Evaluation)
    );
    let originals = (fixture.bytes()?, fixture.training_bytes()?);
    let common =
        stages::recovered_candidate_clients(fixture.config.clone(), experience, dataset, trainer)?;
    let adapter = stages::fixture_from_original_clients(
        common,
        registered,
        fixture.training_baseline(),
        candidate_connection,
        end,
    )?;
    adapter.validate_recovery(&snapshot).await?;
    // Three actual body pages and the separate original Finish read.
    assert_eq!(candidate_peer.frames.load(Ordering::Acquire), 4);
    // An independent request must perform all original reads again. The
    // previous operation's private proof never becomes a reusable cache.
    adapter.validate_recovery(&snapshot).await?;
    let signature = adapter
        .receipt_attestation(&snapshot, training.receipt(), command_now()?)
        .await?;
    assert_eq!(signature, *training.attestation());
    assert_eq!(candidate_peer.frames.load(Ordering::Acquire), 8);
    assert_eq!((fixture.bytes()?, fixture.training_bytes()?), originals);
    // Recovery remains readonly even with an actual Candidate and ready bytes.
    assert!(matches!(
        adapter
            .execute_stage(&snapshot, LearningIterationStageV1::Evaluation)
            .await,
        Err(StageError::WrongScope)
    ));
    assert_eq!(candidate_peer.frames.load(Ordering::Acquire), 8);
    drop(adapter);
    assert_eq!(candidate_peer.finish()?, 8);
    assert_eq!(material_ports::finish(e_peer)?, 4);
    assert_eq!(material_ports::finish(d_peer)?, 4);
    assert_eq!(
        training_server
            .join()
            .expect("original Trainer command peer")?,
        6
    );
    drop(owner);
    let counts = finish_material(peers)?;
    assert_eq!(counts[0], 1);
    assert!(counts[1] > 0 && counts[2] > 0 && counts[3] > 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn candidate_stage_cancelled_operation_cannot_reuse_original_prefix()
-> anyhow::Result<()> {
    let registered = protocol("original-primary-fold-and-unit-rule")?;
    let fixture = MaterialCommandFixture::candidate_pages_for_evaluation_profile(
        registered.evaluation_profile(),
    ).await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let reached = Arc::new(tokio::sync::Notify::new());
    let (release, released) = std::sync::mpsc::channel();
    let (candidate_connection, candidate_peer) = page_peer(
        Arc::clone(&owner), fixture.config.clone(), Origin::Recovered,
        /*expected*/ None, Fault::Original,
        Some(ResponseGate { reached: Arc::clone(&reached), release: released }),
        Duration::from_secs(300),
    )?;
    let (training_connection, training_server) = prebound(
        Arc::clone(&owner), fixture.config.clone(), Origin::Fresh,
        /*expected*/ None, Duration::from_secs(300),
    )?;
    let (experience, e_peer) = material_ports::commands(&fixture, MaterialRole::Experience)?;
    let (dataset, d_peer) = material_ports::commands(&fixture, MaterialRole::Dataset)?;
    let cut = complete_material(&fixture).await?;
    let trainer = training_connection.bind_original_dataset(cut.clone())?;
    let training = trainer.execute_training(Arc::new(AtomicBool::new(false))).await?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(cut.snapshot().clone())?;
    coordinator.record(training.receipt().clone(), training.receipt().observed_unix_seconds)?;
    let snapshot = coordinator.snapshot().clone();
    let originals = (fixture.bytes()?, fixture.training_bytes()?);
    let common = stages::recovered_candidate_clients(
        fixture.config.clone(), experience, dataset, trainer,
    )?;
    let adapter = Arc::new(stages::fixture_from_original_clients(
        common, registered, fixture.training_baseline(), candidate_connection,
        Instant::now() + Duration::from_secs(300),
    )?);
    let pending = tokio::spawn({
        let adapter = Arc::clone(&adapter);
        let snapshot = snapshot.clone();
        async move { adapter.validate_recovery(&snapshot).await }
    });
    tokio::time::timeout(Duration::from_secs(30), reached.notified()).await?;
    // Abort only this await. The actual original read may still finish and its
    // bytes must remain unchanged; the same adapter must never reuse it.
    pending.abort();
    match pending.await {
        Err(error) => assert!(error.is_cancelled()),
        Ok(_) => anyhow::bail!("original Candidate operation was not cancelled"),
    }
    assert!(matches!(adapter.validate_recovery(&snapshot).await, Err(StageError::CommitUncertain)));
    release.send(())?;
    drop(adapter);
    // The admitted Begin may return; cancellation prevents every later Page/Finish.
    assert_eq!(candidate_peer.finish()?, 1);
    assert_eq!(material_ports::finish(e_peer)?, 1);
    assert_eq!(material_ports::finish(d_peer)?, 1);
    assert_eq!(training_server.join().expect("original Trainer command peer")?, 2);
    assert_eq!((fixture.bytes()?, fixture.training_bytes()?), originals);
    drop(owner);
    let counts = finish_material(peers)?;
    assert_eq!(counts[0], 1);
    assert!(counts[1] > 0 && counts[2] > 0 && counts[3] > 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn candidate_stage_rejects_rebound_profile_and_absent_root_gate_without_dispatch()
-> anyhow::Result<()> {
    let registered = protocol("original-primary-fold-and-unit-rule")?;
    let fixture = MaterialCommandFixture::candidate_pages_for_evaluation_profile(
        registered.evaluation_profile(),
    )
    .await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let originals = (fixture.bytes()?, fixture.training_bytes()?);
    for changed in [true, false] {
        let end = Instant::now() + Duration::from_secs(300);
        let (candidate_connection, candidate_peer) = page_peer(
            Arc::clone(&owner),
            fixture.config.clone(),
            Origin::Fresh,
            /*expected*/ None,
            Fault::Original,
            /*gate*/ None,
            Duration::from_secs(300),
        )?;
        let (experience, e_peer) = material_ports::commands(&fixture, MaterialRole::Experience)?;
        let (dataset, d_peer) = material_ports::commands(&fixture, MaterialRole::Dataset)?;
        let common = stages::fresh_material_only(fixture.config.clone(), experience, dataset)?;
        let selected = if changed {
            protocol("different-fold-before-training")?
        } else {
            registered.clone()
        };
        let adapter = stages::fixture_from_original_clients(
            common,
            selected,
            fixture.training_baseline(),
            candidate_connection,
            end,
        );
        if changed {
            assert!(matches!(adapter, Err(StageError::WrongScope)));
        } else {
            let adapter = adapter?;
            assert!(matches!(
                adapter
                    .execute_stage(
                        &fixture.config.initial,
                        LearningIterationStageV1::Experience,
                    )
                    .await,
                Err(StageError::OwnerUnavailable("fresh resident continuation"))
            ));
            drop(adapter);
        }
        assert_eq!(candidate_peer.finish()?, 0);
        assert_eq!(material_ports::finish(e_peer)?, 0);
        assert_eq!(material_ports::finish(d_peer)?, 0);
        assert_eq!((fixture.bytes()?, fixture.training_bytes()?), originals);
    }
    drop(owner);
    assert_eq!(finish_material(peers)?, [0; 4]);
    Ok(())
}
