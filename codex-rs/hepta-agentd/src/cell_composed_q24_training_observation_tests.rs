//! Native optimizer, control, CURRENT, nonce and witness mechanics. Original
//! source/role custody and signatures remain explicit fixtures; these are not
//! ordinary-task daemon/Root acceptance or independent quality qualification.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use pretty_assertions::assert_eq;

use super::*;

#[test]
fn q24_anchored_training_observation_preserves_actual_result_and_refuses_rebound_prefix()
-> anyhow::Result<()> {
    for target in [Q, 2 * Q] {
        let root = tempfile::tempdir()?;
        let baseline = Arc::new(load(root.path(), 1)?);
        let selected = bundle(&baseline, None)?;
        let data = batch(target)?;
        let rule = CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let (plan, prefix) = plan(
            Arc::clone(&baseline),
            &selected,
            &data,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            rule,
            "none",
        )?;
        let original_heads = fs::read(root.path().join("heads"))?;
        let mut owner = CellQ24TrainingOwnerV1::create(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data.clone(),
            rule,
        )?;
        let empty = fs::read(root.path().join("job"))?;
        assert!(matches!(
            owner.read_learning_observation(&prefix),
            Err(OwnerError::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing
            ))
        ));
        assert_eq!(fs::read(root.path().join("job"))?, empty);
        let result = owner.fit_or_readback(&AtomicBool::new(false))?;
        let identity = result_identity(&result)?;
        let observed = owner.read_learning_observation(&prefix)?;
        assert_eq!(observed.iteration_head(), prefix.head_digest);
        let frozen = FrozenLearningScopeV2::freeze(
            &prefix.request,
            &prefix.owners,
            LearningUpdateScopeV2::Cell,
            identity.2.update_rule,
        )?;
        assert_eq!(observed.scope_binding(), frozen.binding());
        assert!(!observed.evidence_digest().is_zero());
        match observed.observation() {
            LearningIterationObservationV1::Training {
                candidate,
                steps,
                milliseconds,
                artifact_bytes,
            } => {
                assert_eq!(
                    (candidate.digest()?, *steps, *milliseconds, *artifact_bytes),
                    (
                        identity.0,
                        identity.2.optimizer_steps,
                        identity.2.elapsed_microseconds.div_ceil(1_000).max(1),
                        identity.1.len() as u64
                    )
                );
                assert_eq!(target, 2 * Q);
            }
            LearningIterationObservationV1::TrainingNoUpdateV2(outcome) => {
                assert_eq!(
                    (
                        outcome.retained_bundle,
                        outcome.dataset,
                        outcome.update_rule,
                        outcome.steps,
                        outcome.milliseconds,
                        outcome.reason
                    ),
                    (
                        selected.digest()?,
                        d("dataset"),
                        identity.2.update_rule,
                        identity.2.optimizer_steps,
                        identity.2.elapsed_microseconds.div_ceil(1_000).max(1),
                        LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged
                    )
                );
                assert_eq!(target, Q);
            }
            _ => anyhow::bail!("owner manufactured another role's outcome"),
        }
        let saved = fs::read(root.path().join("job"))?;
        for change in ["source", "weights", "dataset", "budget"] {
            let mut rebound = prefix.clone();
            match change {
                "source" => rebound.request.source_run_id = StableId::new("different-source")?,
                "weights" => {
                    rebound.request.selected_bundle.components.heads = d("different-heads")
                }
                "dataset" => rebound.receipts[1].evidence_digest = d("different-dataset-owner"),
                "budget" => rebound.request.budget.maximum_training_steps += 1,
                _ => anyhow::bail!("unknown mutation"),
            }
            assert!(matches!(
                owner.read_learning_observation(&rebound),
                Err(OwnerError::Binding(_))
            ));
            assert_eq!(fs::read(root.path().join("job"))?, saved);
        }
        drop(owner);
        let plan = original_plan(baseline, &prefix, &data, rule)?;
        let mut owner = CellQ24TrainingOwnerV1::recover(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data,
            rule,
        )?;
        assert_eq!(owner.read_learning_observation(&prefix)?, observed);
        assert_eq!(fs::read(root.path().join("job"))?, saved);
        assert_eq!(fs::read(root.path().join("heads"))?, original_heads);
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix)?;
        let mut receipt = learning_test_receipt(&coordinator, observed.observation().clone());
        receipt.evidence_digest = observed.evidence_digest();
        coordinator.record(receipt, 20)?;
        frozen.validate_snapshot(coordinator.snapshot())?;
        assert_eq!(
            coordinator.next_stage(),
            Some(if target == Q {
                LearningIterationStageV1::Selection
            } else {
                LearningIterationStageV1::Evaluation
            })
        );
        assert_eq!(coordinator.candidate().is_none(), target == Q);
    }
    Ok(())
}

#[test]
fn q24_actual_trainer_no_update_requires_published_retained_task_and_committed_distinct_input_after_reopen()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), 1)?);
    let selected = bundle(&baseline, None)?;
    let original_heads = fs::read(root.path().join("heads"))?;
    let old_config = configured(&baseline, &selected)?;
    let mut next_config = old_config.clone();
    next_config
        .initial
        .scope
        .run_id
        .push_str("-retained-fresh-task");
    next_config.initial.generation += 1;
    next_config.initial.writer_epoch += 1;
    next_config.task_digest = d("different-input-retained-task").into_array();
    let f = Fixture::new_with_target(old_config, next_config)?;
    let mut old_control = control(
        &root.path().join("control-a"),
        baseline.shared_worker(&selected, f.old_config.manifest.clone(), Arc::new(|| 11))?,
        &f.old_config,
    )?;
    let mut old = f.old_journal()?;
    let mut source = request(&old, &f.old_config, "actual-source-a")?;
    source.input = input();
    old.admit(source.clone(), 10)?;
    old.commit(
        execute_and_read(&mut old_control, &f.old_config.manifest, &source)?,
        11,
    )?;
    let completed = old
        .receipt_for_intent(&source.intent()?)?
        .ok_or_else(|| anyhow::anyhow!("source receipt"))?;
    assert_eq!(completed.disposition, CellGenerationDispositionV2::Stopped);
    let chunk = old
        .pending_output()?
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("source output"))?;
    assert_eq!(chunk.bytes, output(3 * Q / 2));
    let dataset = Digest32::of_parts(&[b"q24-test-original-source", &source.input, &chunk.bytes]);
    let data = CellQ24TrainingBatchV1::new(
        dataset,
        vec![CellQ24TrainingSampleV1 {
            input: vec![Q / 2, Q / 2],
            target: i64::from_le_bytes(chunk.bytes[10..18].try_into()?),
        }],
    )?;
    old.acknowledge(
        chunk,
        d("delivered-source-a").into_array(),
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: f.old_config.task_digest,
            source_digest: f.old_config.manifest.source_digest,
        })?,
    )?;
    old.drain()?;
    let terminal = old.observe_generation()?;
    assert!(terminal.is_terminal());
    let completed_task_receipt = Digest32::from_array(terminal.digest()?);
    old_control.shutdown()?;
    drop(old_control);

    // Fixture role owners bind the actual committed A receipt and exact batch.
    let fixture = learning_test_decision(&f, selected.clone(), "none")?;
    let mut learning = fixture.snapshot().request.clone();
    learning.completed_task_receipt = completed_task_receipt;
    learning.envelope.expiry_unix_seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs()
        + 60;
    learning.budget.maximum_training_steps = 2;
    learning.budget.maximum_training_milliseconds = 10_000;
    let episode = learning.completed_task_receipt;
    let mut coordinator =
        LearningIterationCoordinatorV1::new(learning, fixture.snapshot().owners.clone())?;
    for observation in [
        LearningIterationObservationV1::Experience {
            episode_digest: episode,
            completed_task_receipt: episode,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: dataset,
            episode_digest: episode,
            withdrawal_frontier: d("fixture-withdrawals"),
            rows: data.rows(),
            bytes: data.encoded().len() as u64,
        },
    ] {
        coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
    }
    let prefix = coordinator.snapshot().clone();
    let rule = CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    let plan = original_plan(Arc::clone(&baseline), &prefix, &data, rule)?;
    let mut trainer = CellQ24TrainingOwnerV1::create(
        opened(root.path(), "job")?,
        witness(root.path())?,
        plan,
        data.clone(),
        rule,
    )?;
    assert!(matches!(
        trainer.fit_or_readback(&AtomicBool::new(false))?,
        CellQ24TrainingOutcomeV1::NoUpdate { .. }
    ));
    let training = trainer.read_learning_observation(&prefix)?;
    let mut receipt = learning_test_receipt(&coordinator, training.observation().clone());
    receipt.evidence_digest = training.evidence_digest();
    coordinator.record(receipt, 20)?;
    assert!(coordinator.candidate().is_none());
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Selection)
    );
    let operation_id = crate::learning_retained_task_operation_id_v1(&coordinator)?.to_string();
    let prepared = crate::prepare_agentd_generation_same_model_task_v1(
        f.current.clone(),
        f.authorities()?,
        old,
        f.selection()?,
        f.target_create()?,
        crate::AgentdGenerationUpdateRequestV1 {
            operation_id: operation_id.clone(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = f.sign(prepared.final_use_binding())?;
    f.lose_publication_ack();
    assert!(prepared.publish(&signed).is_err());
    let recovery = || -> anyhow::Result<_> {
        Ok(crate::recover_agentd_generation_update_v1(
            f.reopen_current()?,
            f.authorities()?,
            f.selection()?,
            f.target_reopen()?,
            crate::AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation_id.clone(),
                intent_digest,
            },
        )?)
    };
    let mut ready = recovery()?;
    let selected_observation = ready.read_learning_selection(&coordinator)?;
    coordinator.record(
        learning_test_receipt(&coordinator, selected_observation),
        20,
    )?;
    let mut next = request(&ready.journal, &f.target_config, "actual-fresh-c")?;
    next.input = b"HQ24I001".to_vec();
    next.input.extend_from_slice(&2_u16.to_le_bytes());
    for value in [Q / 4, Q / 8] {
        next.input.extend_from_slice(&value.to_le_bytes());
    }
    assert_ne!(next.input, source.input);
    let intent = next.intent()?;
    assert!(ready.read_learning_next_use(&coordinator, &intent).is_err());
    drop(trainer);
    drop(baseline);
    let reopened_model = Arc::new(private_head::reopen(root.path())?);
    let mut next_control = control(
        &root.path().join("control-c"),
        reopened_model.shared_worker(
            &selected,
            f.target_config.manifest.clone(),
            Arc::new(|| 11),
        )?,
        &f.target_config,
    )?;
    ready.journal.admit(next.clone(), 10)?;
    assert!(ready.read_learning_next_use(&coordinator, &intent).is_err());
    ready.journal.commit(
        execute_and_read(&mut next_control, &f.target_config.manifest, &next)?,
        11,
    )?;
    let actual_output = &ready.journal.pending_output()?.unwrap().bytes;
    let values = actual_output[10..]
        .chunks_exact(8)
        .map(|value| value.try_into().map(i64::from_le_bytes))
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(values, vec![Q / 2, 3 * Q / 8, -Q / 2, -3 * Q / 8]);
    let used = ready.read_learning_next_use(&coordinator, &intent)?;
    assert!(
        matches!(used, LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == selected.digest()?)
    );
    let saved = (
        f.bytes("current.json")?,
        f.bytes("target-journal")?,
        f.bytes("target-witness")?,
        f.bytes("final-use/authority.claims")?,
        fs::read(root.path().join("job"))?,
    );
    drop(ready);
    next_control.shutdown()?;
    drop(next_control);
    drop(reopened_model);
    let cold_model = Arc::new(private_head::reopen(root.path())?);
    let plan = original_plan(cold_model, &prefix, &data, rule)?;
    let mut trainer = CellQ24TrainingOwnerV1::recover(
        opened(root.path(), "job")?,
        witness(root.path())?,
        plan,
        data,
        rule,
    )?;
    assert_eq!(trainer.read_learning_observation(&prefix)?, training);
    let ready = recovery()?;
    assert_eq!(ready.read_learning_next_use(&coordinator, &intent)?, used);
    let mut substituted = intent;
    substituted.input_digest = source.intent()?.input_digest;
    assert!(
        ready
            .read_learning_next_use(&coordinator, &substituted)
            .is_err()
    );
    assert_eq!(
        (
            f.bytes("current.json")?,
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?,
            fs::read(root.path().join("job"))?
        ),
        saved
    );
    assert_eq!(fs::read(root.path().join("heads"))?, original_heads);
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    coordinator.record(learning_test_receipt(&coordinator, used), 20)?;
    assert_eq!(
        coordinator.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(coordinator.snapshot().receipts.len(), 5);
    assert!(coordinator.candidate().is_none());
    Ok(())
}
