//! Actual ordinary ObjectiveStart -> durable source -> guarded sparse Cell ->
//! native Q24 -> published result, then a different input in a fresh session.
//! This is engineering integration with test AuthBus/FinalUse issuer keys and
//! CURRENT FileCAS custody, not an original Root deployment or quality claim.

use pretty_assertions::assert_eq;

use super::*;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::neuron_generation_current::test_support::Fixture as VersionFixture;
use crate::neuron_generation_current::test_support::RECORDS;

#[path = "circuit_q24_task_cold_recovery_tests.rs"]
mod cold_recovery;
#[path = "circuit_q24_task_test_support.rs"]
mod support;
#[path = "circuit_q24_task_trained_ingress_tests.rs"]
mod trained;

use support::Q;

async fn execute(
    session: &support::Session,
    request_id: u64,
) -> anyhow::Result<CircuitTaskSourcePublicationV1> {
    let response = session
        .runtime
        .state
        .response(
            request_id,
            1,
            AgentdMethod::ObjectiveStart {
                request: session.request.clone(),
            },
        )
        .await?;
    let AgentdPayload::ObjectiveRun(admission) = response.payload else {
        anyhow::bail!("ordinary ingress did not return its admission")
    };
    assert_eq!(admission.disposition, "circuit_succeeded");
    Ok(session.source.read_run_publication(
        &session.runtime.identity,
        &StableId::new(&session.request.body.run_id)?,
    )?)
}

fn read_receipt(
    session: &support::Session,
    definition: &CellDefinitionV1,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<CellDecisionReceiptV1> {
    let input = publication.input();
    let receipt = session
        .cell
        .lookup(
            &input.scope,
            &input.operation_id,
            canonical_cell_step_request_digest_v1(definition, input)?,
        )?
        .expect("actual committed Cell decision");
    assert_eq!(
        crate::circuit_cell_output::encode_output(&receipt)?,
        publication.output()
    );
    assert!(receipt.cost.resident_bytes > 0 && receipt.cost.transient_allocation_bytes > 0);
    assert_eq!(receipt.cost.consumed_input_bytes, input.observation.len());
    assert_eq!(receipt.cost.truncated_input_bytes, 0);
    Ok(receipt)
}

fn owner_bytes(session: &support::Session) -> anyhow::Result<Vec<Vec<u8>>> {
    [
        "q24-source.journal",
        "q24-source.witness",
        "q24-cell.journal",
        "q24-cell.witness",
        "q24-control.journal",
    ]
    .iter()
    .map(|name| Ok(fs::read(session.runtime.identity.home_root.join(name))?))
    .collect()
}

#[tokio::test]
async fn q24_ordinary_signed_tasks_consume_real_current_model_and_fresh_input_after_drain()
-> anyhow::Result<()> {
    let model_root = tempfile::tempdir()?;
    let (model, bundle, definition) = support::model(model_root.path())?;
    let parent_heads = fs::read(model_root.path().join("heads"))?;
    let a = support::admission("ordinary-q24-A").await?;
    let source_a = support::source(&a, [Q, Q / 4])?;
    let config_a = support::configuration(
        &model,
        &bundle,
        &definition,
        &source_a,
        /*generation*/ 1,
    )?;
    let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
    let published_a = support::publish_initial(&version, definition.clone(), source_a.clone())?;
    let mut a = support::start(a, published_a, Arc::clone(&model), bundle.clone()).await?;
    assert!(a.cell.snapshot(&source_a.scope)?.checkpoint.is_none());
    let publication_a = execute(&a, /*request_id*/ 1).await?;
    let receipt_a = read_receipt(&a, &definition, &publication_a)?;
    assert_eq!(receipt_a.representation.drive_q24, vec![Q, Q / 4, 0, 0, 0]);
    assert_eq!(
        receipt_a.representation.prediction_q24,
        receipt_a.representation.drive_q24
    );
    assert_eq!(receipt_a.selected_candidate, cell::id("a"));
    assert_eq!(publication_a.input().observation, source_a.observation);
    assert_eq!(
        publication_a.original_record().snapshot.objective_digest,
        source_a.objective_digest
    );
    let snapshot_a = a.cell.snapshot(&source_a.scope)?;
    assert_eq!(snapshot_a.revision, 1);
    assert!(snapshot_a.checkpoint.is_some());

    // Exact signed retry consumes the original private receipt and saved costs.
    let durable_a = owner_bytes(&a)?;
    assert_eq!(execute(&a, /*request_id*/ 2).await?, publication_a);
    assert_eq!(read_receipt(&a, &definition, &publication_a)?, receipt_a);
    assert_eq!(owner_bytes(&a)?, durable_a);
    let mut alias = a.request.clone();
    alias.body.runtime_body_digest = cell::d("changed signed body").to_string();
    assert!(
        a.runtime
            .state
            .response(3, 1, AgentdMethod::ObjectiveStart { request: alias })
            .await
            .is_err()
    );
    assert_eq!(owner_bytes(&a)?, durable_a);
    let completion_a =
        a.retirement
            .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
    a.stop().await?;
    drop(a); // Release actual source, Cell, control and original GenV2 locks.
    let old_owner = (
        version.bytes("target-journal")?,
        version.bytes("target-witness")?,
    );

    let c = support::admission("ordinary-q24-C").await?;
    let source_c = support::source(&c, [Q / 4, Q])?;
    let config_c = support::configuration(
        &model,
        &bundle,
        &definition,
        &source_c,
        /*generation*/ 2,
    )?;
    assert_eq!(config_a.manifest, config_c.manifest);
    assert_ne!(source_a.scope.run_id, source_c.scope.run_id);
    assert_ne!(source_a.observation, source_c.observation);
    let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
        version.reopen_current()?,
        version.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: version.file("target-journal")?,
            witness: version.witness("target-witness", &config_a)?,
            config: config_a.clone(),
            max_records: RECORDS,
        },
        version.selection()?,
        version.named_target_create("fresh-C-journal", "fresh-C-witness", config_c)?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "ordinary-q24-fresh-C".into(),
        },
    )?;
    let signed = version.sign(prepared.final_use_binding())?;
    let published_c = prepared.publish(&signed)?.into_circuit_feature_task(
        definition.clone(),
        source_c.clone(),
        completion_a,
    )?;
    let mut c = support::start(c, published_c, Arc::clone(&model), bundle.clone()).await?;
    let empty = c.cell.snapshot(&source_c.scope)?;
    assert_eq!(empty.revision, 0);
    assert!(empty.checkpoint.is_none());
    assert_eq!(empty.writer_epoch, 2);
    assert!(c.cell.snapshot(&publication_a.input().scope).is_err());
    let publication_c = execute(&c, /*request_id*/ 1).await?;
    let receipt_c = read_receipt(&c, &definition, &publication_c)?;
    assert_eq!(receipt_c.representation.drive_q24, vec![Q / 4, Q, 0, 0, 0]);
    assert_eq!(
        receipt_c.representation.prediction_q24,
        receipt_c.representation.drive_q24
    );
    assert_eq!(receipt_c.selected_candidate, cell::id("b"));
    assert_eq!(receipt_c.bundle_digest, receipt_a.bundle_digest);
    assert_ne!(receipt_c.scope.run_id, receipt_a.scope.run_id);
    assert_ne!(receipt_c.operation_digest, receipt_a.operation_digest);
    assert_ne!(receipt_c.checkpoint_after, receipt_a.checkpoint_after);
    assert_eq!(execute(&c, /*request_id*/ 2).await?, publication_c);
    assert_eq!(
        (
            version.bytes("target-journal")?,
            version.bytes("target-witness")?
        ),
        old_owner
    );
    assert_eq!(fs::read(model_root.path().join("heads"))?, parent_heads);
    let _completion_c =
        c.retirement
            .drain_completed_task(&c.cell, c.source.as_ref(), &c.runtime.identity)?;
    c.stop().await?;
    Ok(())
}

#[path = "circuit_q24_next_use_observer_tests.rs"]
mod next_use_observer;

#[path = "circuit_model_selection_owner_published_tests.rs"]
mod model_selection_owner;
