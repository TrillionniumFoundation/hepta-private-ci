//! Original TaskSource/Circuit persistence with existing controlled fixtures.
//! Q24 bytes are real; this fixture does not qualify task inference or adoption.

use std::fs;
use std::fs::File;
use std::path::Path;

use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellJournalPartitionV1;
use codex_hepta_neuron::CellOwnerJournalV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentdCircuitCellOwnerV1;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::AgentdIdentity;
use crate::CellQ24ModelFilesV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitTaskSourceInputV1;
use crate::DurableCircuitTaskSourceV1;
use crate::LoadedCellQ24ModelV1;
use crate::circuit_cell::tests::configuration;
use crate::circuit_cell::tests::support as cell;
use crate::circuit_task::CircuitTaskModeV1;
use crate::circuit_task::driver::CircuitTaskDriverV1;
use crate::circuit_task::source_test_support::fence;
use crate::circuit_task::source_test_support::identity;
use crate::circuit_task::source_test_support::opened;
use crate::circuit_task::source_test_support::record;
use crate::circuit_task::source_test_support::source;
use crate::circuit_task::source_test_support::time;
use crate::circuit_task::source_test_support::witness;

pub(crate) type Source = DurableCircuitTaskSourceV1<FileAnchorWitnessStore>;

fn definition(bundle: Digest32) -> codex_hepta_neuron::CellDefinitionV1 {
    let mut definition = cell::definition();
    definition.bundle_digest = bundle;
    definition
}

fn registry(bundle: Digest32) -> anyhow::Result<CircuitCellRegistryV1> {
    let (mut circuit, mut bindings) = configuration();
    bindings[0].cell = definition(bundle);
    circuit.parameter_bundle_digest =
        Sha256Digest::parse(bundle.to_string()).map_err(anyhow::Error::msg)?;
    circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
    Ok(CircuitCellRegistryV1::new(circuit, bindings)?)
}

fn cell_owner(
    root: &Path,
    inputs: &[CircuitTaskSourceInputV1],
    bundle: Digest32,
) -> anyhow::Result<CellOwnerJournalV1<FileAnchorWitnessStore>> {
    Ok(CellOwnerJournalV1::open(
        opened(root, "cell-journal")?,
        witness(root, "cell-witness")?,
        inputs
            .iter()
            .map(|input| CellJournalPartitionV1 {
                scope: input.scope.clone(),
                definition: definition(bundle),
                source_frontier: input.source_frontier,
                writer_epoch: 1,
            })
            .collect(),
        /*max_records*/ 64,
    )?)
}

pub(crate) fn model(
    root: &Path,
) -> anyhow::Result<(LoadedCellQ24ModelV1, CellCompatibilityBundleV1)> {
    let q = crate::cell_composed_q24::codec::Q;
    let matrix = |rows: u16, values: &[i64]| {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend_from_slice(&rows.to_le_bytes());
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    };
    let file = |name: &str, bytes: Vec<u8>| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    let model = LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base", matrix(/*rows*/ 2, &[q, 0, 0, q]))?,
        encoder: file("encoder", matrix(/*rows*/ 2, &[q, 0, 0, q]))?,
        heads: file("heads", matrix(/*rows*/ 2, &[q, 0, -q, 0]))?,
        organ_adapter: None,
        cell_adapter: None,
    })?;
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: cell::id("original-q24-dataset-baseline"),
        generation: Generation::new(1)?,
        components: model.components().clone(),
        rollback_predecessor: None,
        training_lineage: None,
    };
    Ok((model, bundle))
}

/// Three real pages of heads; labels still come only from the independent
/// terminal Outcome in the Material fixture, never from model inference.
pub(crate) fn candidate_page_model(
    root: &Path,
) -> anyhow::Result<(LoadedCellQ24ModelV1, CellCompatibilityBundleV1)> {
    let q = crate::cell_composed_q24::codec::Q;
    let matrix = |rows: u16, columns: u16, values: &[i64]| {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend_from_slice(&rows.to_le_bytes());
        bytes.extend_from_slice(&columns.to_le_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    };
    let file = |name: &str, bytes: Vec<u8>| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    let base: Vec<i64> = (0..64)
        .flat_map(|row| if row % 2 == 0 { [q, 0] } else { [0, q] })
        .collect();
    let mut heads = vec![0; 8 * 64];
    for row in 0..8 {
        heads[row * 64] = if row < 4 { q } else { -q };
    }
    let model = LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base", matrix(/*rows*/ 64, /*columns*/ 2, &base))?,
        encoder: file("encoder", matrix(/*rows*/ 2, /*columns*/ 2, &[q, 0, 0, q]))?,
        heads: file("heads", matrix(/*rows*/ 8, /*columns*/ 64, &heads))?,
        organ_adapter: None,
        cell_adapter: None,
    })?;
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: cell::id("original-q24-page-baseline"),
        generation: Generation::new(1)?,
        components: model.components().clone(),
        rollback_predecessor: None,
        training_lineage: None,
    };
    Ok((model, bundle))
}

pub(crate) fn observation(values: [i64; 2]) -> Vec<u8> {
    let mut bytes = b"HQ24I001".to_vec();
    bytes.extend_from_slice(&2_u16.to_le_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

pub(crate) async fn completed(
    root: &Path,
    bundle: &CellCompatibilityBundleV1,
    run: &StableId,
    observation: &[u8],
) -> anyhow::Result<(AgentdIdentity, Source)> {
    let identity = identity(root)?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let sources = vec![source(run.as_str(), observation)];
    let bundle_digest = bundle.digest()?;
    let owner = Source::create(
        opened(root, "source-journal")?,
        witness(root, "source-witness")?,
        &identity,
        &fence,
        &registry(bundle_digest)?,
        sources.clone(),
    )?;
    let request = owner.build(&identity, &record(run.as_str()))?;
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence,
        inputs: owner.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry(bundle_digest)?,
            cell_owner(root, &sources, bundle_digest)?,
            cell::Model::new(/*latency*/ 20, /*lose_response*/ false),
            cell::Encoder,
        ),
    };
    let receipt = driver
        .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
        .await?;
    owner.publish_result(&identity, &record(run.as_str()), &receipt)?;
    drop(driver);
    store.close().await;
    Ok((identity, owner))
}
