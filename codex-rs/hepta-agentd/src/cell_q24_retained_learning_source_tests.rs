//! Real A, Ledger, database and source readers; Root profiles and issuer custody
//! are explicit component fixtures. These do not qualify a daemon/Root restart.

use super::*;
use crate::OriginalCellQ24RetainedLearningSourceV1;
use pretty_assertions::assert_eq;

async fn completed_prepared(
    f: &Fixture,
) -> anyhow::Result<(Arc<crate::CellQ24PreparedLearningV1>, codex_hepta_automation::AutomationStore)> {
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    f.producer.submit_original_terminal_outcome(outcome, &signed)?;
    let store = f.session.runtime.state.circuit_task_store()?;
    let trace = store.bounded_circuit_committed_trace(f.publication.input().scope.run_id.as_str())
        .await?.expect("actual original committed task");
    let intent = store.enqueue_circuit_learning(&trace,
        codex_hepta_contracts::Sha256Digest::parse(f.publication.input().objective_digest.to_string())
            .map_err(anyhow::Error::msg)?,
    ).await.map_err(|error| anyhow::anyhow!("{error:?}"))?;
    let mut preparation = f.preparation()?;
    preparation.request.operation_id = StableId::new(intent.operation_id)?;
    let prepared = Arc::new(f.producer.prepare_learning(
        preparation, Vec::new(), f.freeze_inputs()?,
    )?);
    Ok((prepared, store))
}

#[tokio::test]
async fn retained_source_binds_root_scope_and_consumer_without_relaxing_current_task_identity()
-> anyhow::Result<()> {
    let mut f = Fixture::new("retained-source-A", /*lifetime*/ 600, /*automatic*/ true).await?;
    let (prepared, store) = completed_prepared(&f).await?;
    let before = (f.task_bytes()?, f.learning_bytes()?);
    let mut next = f.session.runtime.identity.clone();
    next.spawn_generation += 1;
    let mut wrong = prepared.initial().clone();
    wrong.request.source_run_id = cell::id("other-original-source");
    let rejected: OriginalCellQ24RetainedLearningSourceV1 =
        f.producer.retained_learning_source(Arc::clone(&prepared), store.clone()).await?;
    assert!(rejected.register_original_scope(next.clone(), &wrong, prepared.scope()).is_err());
    let source = f.producer.retained_learning_source(Arc::clone(&prepared), store).await?;
    // Explicit scope fixture for this component test; production registration
    // is closed to the already assembled original Root/Q24 bootstrap.
    let source = source.register_original_scope(next.clone(), prepared.initial(), prepared.scope())?;
    let ready = source.observe_retained_learning(&next).await?;
    ready.require_retained_task(&source, &next, source.original_record(), source.original_trace()).await?;
    assert!(matches!(
        f.producer.observe_learning(&next, source.original_record(), source.original_trace()),
        crate::CircuitTaskLearningReadinessV1::Pending(crate::CircuitTaskLearningPendingV1::Refused(_))
    ));
    let mut wrong_record = source.original_record().clone();
    wrong_record.authentication.message_id = cell::id("changed-original-message");
    assert!(ready.require_retained_task(&source, &next, &wrong_record, source.original_trace()).await.is_err());
    assert!(source.observe_retained_learning(&f.session.runtime.identity).await.is_err());
    assert_eq!((f.task_bytes()?, f.learning_bytes()?), before);
    f.session.source.withdraw_for_dataset_test(source.source_run_id())?;
    assert!(source.observe_retained_learning(&next).await.is_err());
    assert_eq!(f.learning_bytes()?, before.1);
    f.session.stop().await
}

#[tokio::test]
async fn retained_source_uses_original_outbox_after_current_advances_and_new_task_runs()
-> anyhow::Result<()> {
    let mut f = Fixture::new("retained-source-before-C", /*lifetime*/ 600, /*automatic*/ true).await?;
    let (prepared, store) = completed_prepared(&f).await?;
    let source = f.producer.retained_learning_source(Arc::clone(&prepared), store.clone()).await?;
    let original_bytes = f.learning_bytes()?;
    let definition = f.session.retirement.definition().clone();
    let completion = f.session.retirement.drain_completed_task(
        &f.session.cell, f.session.source.as_ref(), &f.session.runtime.identity,
    )?;
    f.session.stop().await?;
    // Keep A's actual filesystem and database, but release its real Cell and
    // GenV2 writers. A retained reader must not prevent the successor opening.
    let _old_runtime = std::mem::replace(&mut f.session.runtime._temp, tempfile::tempdir()?);
    let old_source = Arc::clone(&f.session.source);
    let Fixture { session, root, ledger: _, producer, config: _, signers: _,
        publication, baseline, bundle, _version: version, trust: _ } = f;
    drop(session);
    drop(producer);
    let old_generation = (version.bytes("target-journal")?, version.bytes("target-witness")?);
    let c = support::admission("retained-source-actual-C").await?;
    let source_c = support::source(&c, [Q / 4, Q])?;
    let config_c = support::configuration(
        &baseline, &bundle, &definition, &source_c, /*generation*/ 2,
    )?;
    let transition = crate::prepare_agentd_generation_cold_same_model_task_v1(
        version.reopen_current()?, version.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: version.file("target-journal")?,
            witness: version.witness("target-witness", &version.target_config)?,
            config: version.target_config.clone(), max_records: RECORDS,
        },
        version.selection()?,
        version.named_target_create("retained-C-journal", "retained-C-witness", config_c)?,
        AgentdGenerationUpdateRequestV1 { operation_id: "retained-source-next-C".into() },
    )?;
    let signed = version.sign(transition.final_use_binding())?;
    let published_c = transition.publish(&signed)?.into_circuit_feature_task(
        definition, source_c, completion,
    )?;
    let mut c = support::start(c, published_c, baseline, bundle).await?;
    let c_store = c.runtime.state.circuit_task_store()?;
    assert!(c_store.bounded_circuit_committed_trace(publication.input().scope.run_id.as_str())
        .await?.is_none());
    let registered = source.register_original_scope(
        c.runtime.identity.clone(), prepared.initial(), prepared.scope(),
    )?;
    c.runtime.state.attach_original_retained_learning_source(Arc::clone(&registered))?;
    c.runtime.state.objective_runtime.get().expect("actual C Objective owner")
        .reconcile_learning_outbox(&c_store, Some(registered.source_run_id()), &c.runtime.state).await?;
    c.runtime.state.require_circuit_learning_source(&prepared.initial().request).await?;
    assert!(c_store.circuit_learning_delivery(registered.source_run_id().as_str()).await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?.is_none());
    let original_row = store.circuit_learning_delivery(registered.source_run_id().as_str()).await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?.expect("same original source outbox");
    assert_eq!(original_row.intent.completed_task_receipt, *publication.history_digest());
    let c_publication = execute(&c, /*request_id*/ 1).await?;
    assert_ne!(c_publication.original_record().snapshot.run_id, publication.original_record().snapshot.run_id);
    let ready = registered.observe_retained_learning(&c.runtime.identity).await?;
    assert!(ready.require_retained_task(
        &registered, &c.runtime.identity, c_publication.original_record(), registered.original_trace(),
    ).await.is_err());
    assert_eq!((version.bytes("target-journal")?, version.bytes("target-witness")?), old_generation);
    let current_bytes = ["ledger", "ledger.witness", "signatures", "signatures.witness"]
        .map(|name| fs::read(root.path().join(name))).into_iter().collect::<Result<Vec<_>, _>>()?;
    assert_eq!(current_bytes, original_bytes);
    old_source.withdraw_for_dataset_test(registered.source_run_id())?;
    assert!(registered.observe_retained_learning(&c.runtime.identity).await.is_err());
    c.stop().await
}

#[tokio::test]
async fn retained_source_refuses_other_database_and_stays_fenced_after_original_replacement()
-> anyhow::Result<()> {
    let mut f = Fixture::new("retained-source-db", /*lifetime*/ 600, /*automatic*/ true).await?;
    let (prepared, store) = completed_prepared(&f).await?;
    let other = support::admission("retained-source-wrong-db").await?;
    let other_store = codex_hepta_automation::AutomationStore::open(&other.runtime.identity.layout).await?;
    assert!(f.producer.retained_learning_source(Arc::clone(&prepared), other_store).await.is_err());
    let source = f.producer.retained_learning_source(Arc::clone(&prepared), store.clone()).await?;
    let source = source.register_original_scope(
        f.session.runtime.identity.clone(), prepared.initial(), prepared.scope(),
    )?;
    let before = f.learning_bytes()?;
    let backup = store.path().with_extension("retained-original");
    fs::rename(store.path(), &backup)?;
    assert!(source.observe_retained_learning(&f.session.runtime.identity).await.is_err());
    fs::rename(&backup, store.path())?;
    assert!(source.observe_retained_learning(&f.session.runtime.identity).await.is_err());
    assert_eq!(f.learning_bytes()?, before);
    f.session.stop().await
}
