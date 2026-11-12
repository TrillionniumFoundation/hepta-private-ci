//! Actual original task mechanics under explicit test admission/model custody.
use super::*;

/// Actual Circuit/Cell/source persistence under explicit model and RunStart
/// fixture custody. Outcomes are supplied only by the separate ledger fixture.
pub(crate) async fn original_evaluation_source(
    root: &Path,
    bundle: Digest32,
    input: CircuitTaskSourceInputV1,
    record: codex_hepta_learning_ledger::RunStartRecordV1,
    selected_index: usize,
) -> anyhow::Result<(
    AgentdIdentity,
    Source,
    crate::CircuitTaskSourcePublicationV1,
)> {
    let identity = identity(root)?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let mut definition = definition(bundle);
    anyhow::ensure!(selected_index < definition.candidates.len());
    let selected_activation = definition.candidates[selected_index].activation_index;
    definition.candidates[selected_index].activation_index =
        definition.candidates[0].activation_index;
    definition.candidates[0].activation_index = selected_activation;
    let selected = definition.candidates[selected_index].candidate_id.clone();
    let (mut circuit, mut bindings) = configuration();
    bindings[0].cell = definition.clone();
    circuit.parameter_bundle_digest =
        Sha256Digest::parse(bundle.to_string()).map_err(anyhow::Error::msg)?;
    circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
    let registry = CircuitCellRegistryV1::new(circuit, bindings)?;
    let sources = vec![input];
    let owner = Source::create(
        opened(root, "source-journal")?,
        witness(root, "source-witness")?,
        &identity,
        &fence,
        &registry,
        sources.clone(),
    )?;
    let request = owner.build(&identity, &record)?;
    let cells = CellOwnerJournalV1::open(
        opened(root, "cell-journal")?,
        witness(root, "cell-witness")?,
        vec![CellJournalPartitionV1 {
            scope: sources[0].scope.clone(),
            definition,
            source_frontier: sources[0].source_frontier,
            writer_epoch: 1,
        }],
        /*max_records*/ 64,
    )?;
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence,
        inputs: owner.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry,
            cells,
            cell::Model::new(/*latency*/ 20, /*lose_response*/ false),
            cell::Encoder,
        ),
    };
    let receipt = driver
        .execute(&request, CircuitTaskModeV1::Drive, || {
            Ok(crate::CircuitCellTimeV1 {
                circuit_millis: record.admission.observed_at_unix_micros / 1_000 + 10,
                cell_micros: 20,
            })
        })
        .await?;
    owner.publish_result(&identity, &record, &receipt)?;
    let publication = owner.read_publication(&identity, &record)?;
    pretty_assertions::assert_eq!(publication.original_policy()?.selected(), &selected);
    drop(driver);
    store.close().await;
    Ok((identity, owner, publication))
}
