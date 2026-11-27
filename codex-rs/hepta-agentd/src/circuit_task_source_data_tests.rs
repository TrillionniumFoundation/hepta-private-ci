//! Actual Source/Cell execution for canonical data tests. The model and signed
//! RunStart are controlled fixtures; the Ledger DTO is untrusted test data.
//! None of these tests establish a Root session, recipient or Dataset right.

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_neuron::CellDecisionReceiptV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;

pub(crate) async fn publication_data_fixture() -> anyhow::Result<(
    RootHistoricalTaskPublicationDataV1,
    RootHistoricalLedgerReadDataV1,
    CircuitTaskSourcePublicationV1,
    CellDecisionReceiptV1,
)> {
    let root = tempfile::tempdir()?;
    let identity = identity(root.path())?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let sources = vec![source("A", b"original data observation")];
    let owner = Source::create(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    let request = owner.build(&identity, &record("A"))?;
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence: fence.clone(),
        inputs: owner.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry()?,
            cell_owner(root.path(), &sources)?,
            cell::Model::new(/*latency*/ 20, /*lose_response*/ false),
            cell::Encoder,
        ),
    };
    let executed = driver
        .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
        .await?;
    let decision = executed
        .executions()
        .values()
        .next()
        .ok_or_else(|| anyhow::anyhow!("original Cell execution missing"))?
        .decision
        .clone();
    owner.publish_result(&identity, &record("A"), &executed)?;
    let publication = owner.read_publication(&identity, &record("A"))?;
    drop(driver);
    drop(owner);
    store.close().await;
    let mut original = HistoricalCircuitTaskSourceV1::open(
        File::open(root.path().join("source-journal"))?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources,
    )?;
    let observation = original.observe_run_publication(&cell::id("A"))?;
    let data =
        RootHistoricalTaskPublicationDataV1::from_original_observation(&observation, &decision)?;
    let mut ledger = crate::root_historical_ledger_data::tests::fixture_data()?;
    let input = publication.input();
    let mut target = serde_json::to_value(&ledger.target)?;
    target["scope"] = serde_json::json!({
        "agent_id": input.scope.agent_id.as_str(),
        "cell_id": input.scope.cell_id.as_str(),
        "run_id": input.scope.run_id.as_str(),
        "principal_digest": input.scope.principal_digest.into_array(),
    });
    target["source_frontier"] = serde_json::json!(input.source_frontier.into_array());
    ledger.target = serde_json::from_value(target)?;
    ledger.registered_identity = serde_json::to_string(&crate::HostAuthorityRegisteredIdentity {
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        fleet_root: identity.fleet_root.clone(),
        workspace: identity.workspace.clone(),
        resources: identity.resources.clone(),
    })?;
    ledger.trust.target = Digest32::from_array(ledger.target.digest()?).to_string();
    ledger.trust.task = Digest32::from_array(ledger.target.task_digest()).to_string();
    ledger.trust.objective = input.objective_digest.to_string();
    ledger.source.configuration = observation.binding_digest().to_string();
    ledger.source.publication = publication.publication_digest().to_string();
    ledger.source.completed_task = publication.history_digest().as_str().into();
    ledger.cut.source_publication = ledger.source.publication.clone();
    ledger.cut.cell_decision = Digest32::of_parts(&[
        b"hepta.root.original-ledger-cell-decision.v1\0",
        &crate::circuit_cell_output::encode_receipt(&decision)?,
        &serde_json::to_vec(&(
            &decision.representation.drive_q24,
            &decision.representation.prediction_q24,
        ))?,
    ])
    .to_string();
    data.validate_against(&ledger)?;
    Ok((data, ledger, publication, decision))
}

#[tokio::test]
async fn original_task_data_preserves_complete_actual_publication_and_cell() -> anyhow::Result<()> {
    let (data, ledger, publication, decision) = publication_data_fixture().await?;
    let bytes = serde_json::to_vec(&data)?;
    let decoded: RootHistoricalTaskPublicationDataV1 = serde_json::from_slice(&bytes)?;
    assert_eq!(decoded, data);
    assert_eq!(decoded.validate_against(&ledger)?, (publication, decision));
    Ok(())
}

#[tokio::test]
async fn original_task_data_rejects_spliced_canonical_request_result_and_cell_cut()
-> anyhow::Result<()> {
    let (data, ledger, _, _) = publication_data_fixture().await?;
    for field in ["source_configuration", "publication", "request", "result"] {
        let mut changed = serde_json::to_value(&data)?;
        changed[field] = if ["request", "result"].contains(&field) {
            serde_json::json!(STANDARD.encode(b"different original bytes"))
        } else {
            serde_json::json!(Digest32::of_bytes(b"different original binding").to_string())
        };
        let changed: RootHistoricalTaskPublicationDataV1 = serde_json::from_value(changed)?;
        assert!(changed.validate_against(&ledger).is_err());
    }
    let mut changed = ledger;
    changed.cut.cell_decision = Digest32::of_bytes(b"different original Cell").to_string();
    assert!(data.validate_against(&changed).is_err());
    Ok(())
}

#[tokio::test]
async fn original_task_data_refuses_authority_fields_missing_bytes_and_noncanonical_base64()
-> anyhow::Result<()> {
    let (data, ledger, _, _) = publication_data_fixture().await?;
    for field in ["grant", "root", "completed", "retired", "current", "path"] {
        let mut changed = serde_json::to_value(&data)?;
        changed[field] = serde_json::json!(true);
        assert!(serde_json::from_value::<RootHistoricalTaskPublicationDataV1>(changed).is_err());
    }
    for field in ["request", "result", "publication", "source_configuration"] {
        let mut changed = serde_json::to_value(&data)?;
        changed
            .as_object_mut()
            .ok_or_else(|| anyhow::anyhow!("data object"))?
            .remove(field);
        assert!(serde_json::from_value::<RootHistoricalTaskPublicationDataV1>(changed).is_err());
    }
    let mut changed = serde_json::to_value(&data)?;
    let original = changed["result"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("result bytes"))?;
    changed["result"] = serde_json::json!(format!("{original}\n"));
    let changed: RootHistoricalTaskPublicationDataV1 = serde_json::from_value(changed)?;
    assert!(changed.validate_against(&ledger).is_err());
    Ok(())
}
