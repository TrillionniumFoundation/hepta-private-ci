//! Real original Source/Cell journals and the original Driver produce these
//! publications. Controlled RunStart authentication and inference qualify the
//! representation/current-source boundary only, not Root IPC or authorization.

use std::sync::atomic::{AtomicUsize, Ordering};
use codex_hepta_automation::AutomationStore;
use codex_hepta_neuron::{CellJournalPartitionV1, CellOwnerJournalV1};
use super::*;
use crate::{AgentdCircuitCellOwnerV1, AgentdCircuitTaskInvocationProviderV1, CircuitCellRegistryV1};
use crate::circuit_cell::tests::{configuration, support as cell};
use crate::circuit_task::CircuitTaskModeV1;
use crate::circuit_task::driver::CircuitTaskDriverV1;
use crate::circuit_task::source::{DurableCircuitTaskSourceV1, tests as original};

type Source = DurableCircuitTaskSourceV1<FileAnchorWitnessStore>;

struct Fixture {
    directory: tempfile::TempDir,
    identity: AgentdIdentity,
    source: Source,
    publication: CircuitTaskSourcePublicationV1,
    calls: Arc<AtomicUsize>,
}

impl Fixture {
    fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        ["source-journal", "source-witness", "cell-journal", "cell-witness"]
            .into_iter().map(|name| Ok(std::fs::read(self.directory.path().join(name))?))
            .collect()
    }
}

async fn completed_source() -> anyhow::Result<Fixture> {
    let directory = tempfile::tempdir()?;
    let identity = original::identity(directory.path())?;
    let fence = original::fence(&identity)?;
    let input = original::source("A", b"actual Material source fixture");
    let (definition, bindings) = configuration();
    let registry = CircuitCellRegistryV1::new(definition, bindings)?;
    let source = Source::create(
        original::opened(directory.path(), "source-journal")?,
        original::witness(directory.path(), "source-witness")?,
        &identity, &fence, &registry, vec![input.clone()],
    )?;
    let cell_owner = CellOwnerJournalV1::open(
        original::opened(directory.path(), "cell-journal")?,
        original::witness(directory.path(), "cell-witness")?,
        vec![CellJournalPartitionV1 { scope: input.scope.clone(),
            definition: cell::definition(), source_frontier: input.source_frontier, writer_epoch: 1 }],
        /*max_records*/ 64,
    )?;
    let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = Arc::clone(&model.calls);
    let store = AutomationStore::open(&identity.layout).await?;
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(), fence, inputs: source.clone(),
        cells: AgentdCircuitCellOwnerV1::new(registry, cell_owner, model, cell::Encoder),
    };
    let body: anyhow::Result<CircuitTaskSourcePublicationV1> = async {
        let record = original::record("A");
        let request = source.build(&identity, &record)?;
        let receipt = driver.execute(&request, CircuitTaskModeV1::Drive, || Ok(original::time())).await?;
        source.publish_result(&identity, &record, &receipt)?;
        let publication = source.read_publication(&identity, &record)?;
        anyhow::ensure!(publication.history_digest() == receipt.trace().history_digest(),
            "the source retains the actual original Driver history");
        Ok(publication)
    }.await;
    drop(driver);
    // Result failures still close the original store. Outer future cancellation
    // is not represented as a completed join by these mechanism tests.
    store.close().await;
    Ok(Fixture { directory, identity, source, publication: body?, calls })
}

#[tokio::test]
async fn material_source_payload_retains_complete_original_publication() -> anyhow::Result<()> {
    let fixture = completed_source().await?;
    let before = fixture.bytes()?;
    let view = fixture.source.readback();
    let payload = view.encode_original_material_publication(&fixture.identity, &fixture.publication)?;
    let actual = decode_current_root_payload(&payload)?;
    anyhow::ensure!(actual == fixture.publication, "complete original publication equality");

    // Independently compare all three encoded records with the actual original
    // journal. This private decoder is not an authentication API.
    let mut reader = wire::Reader::new(&payload, b"HCMATPUB1")?;
    let binding = reader.digest()?;
    let request = reader.bytes()?;
    let input = reader.bytes()?;
    let result = reader.bytes()?;
    reader.end()?;
    {
        let mut owner = fixture.source.0.lock()
            .map_err(|_| anyhow::anyhow!("original Source fixture poisoned"))?;
        anyhow::ensure!(binding == owner.binding, "the original source binding is unchanged");
        anyhow::ensure!(request == owner.read("request", "A")?, "complete original request bytes");
        anyhow::ensure!(input == owner.read("input", "A")?, "complete original saved input bytes");
        anyhow::ensure!(result == owner.read("result", "A")?, "complete original result bytes");
    }
    anyhow::ensure!(fixture.bytes()? == before, "source encoding and decoding are read only");
    anyhow::ensure!(fixture.calls.load(Ordering::SeqCst) == 1, "source readback cannot repeat inference");
    Ok(())
}

#[tokio::test]
async fn material_source_encoding_refuses_rebound_publication() -> anyhow::Result<()> {
    let fixture = completed_source().await?;
    let view = fixture.source.readback();
    let original = view.encode_original_material_publication(&fixture.identity, &fixture.publication)?;
    let before = fixture.bytes()?;
    let mut changed = fixture.publication.clone();
    changed.publication_digest = cell::d("another original publication");
    anyhow::ensure!(view.encode_original_material_publication(&fixture.identity, &changed)
        == Err(Error::InvalidBinding), "a rebound publication digest cannot be exported");
    changed = fixture.publication.clone();
    changed.record.snapshot.run_id = cell::id("another-run");
    anyhow::ensure!(view.encode_original_material_publication(&fixture.identity, &changed)
        == Err(Error::InvalidBinding), "another run cannot select the original Source");
    anyhow::ensure!(view.encode_original_material_publication(&fixture.identity, &fixture.publication)?
        == original, "the unchanged current Source still exports exact original bytes");
    anyhow::ensure!(fixture.bytes()? == before, "refusal cannot change the original journals");
    anyhow::ensure!(fixture.calls.load(Ordering::SeqCst) == 1, "refusal cannot redispatch");
    Ok(())
}

#[tokio::test]
async fn material_source_encoding_refuses_withdrawn_original_for_all_views() -> anyhow::Result<()> {
    let fixture = completed_source().await?;
    let view = fixture.source.readback();
    let alias = view.clone();
    view.encode_original_material_publication(&fixture.identity, &fixture.publication)?;
    fixture.source.withdraw_source(&cell::id("A"))?;
    let withdrawn = fixture.bytes()?;
    for current in [&view, &alias] {
        anyhow::ensure!(current.encode_original_material_publication(&fixture.identity, &fixture.publication)
            == Err(Error::Unavailable), "a retained view cannot encode an actually withdrawn source");
        anyhow::ensure!(current.read_run_publication(&fixture.identity, &cell::id("A"))
            == Err(Error::Unavailable), "the original readback still enforces withdrawal");
    }
    anyhow::ensure!(fixture.bytes()? == withdrawn, "refused reads preserve the actual withdrawal");
    anyhow::ensure!(fixture.calls.load(Ordering::SeqCst) == 1, "withdrawal cannot repeat inference");
    Ok(())
}

#[path = "circuit_task_source_prefreeze_tests.rs"]
mod prefreeze;
