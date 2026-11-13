//! Original files and Circuit execution. The parent's authentication/model
//! fixtures do not establish Root retirement or cross-incarnation authority.

use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use pretty_assertions::assert_eq;

use super::*;

struct NoWriteWitness(FileAnchorWitnessStore);

impl AnchorWitnessStore for NoWriteWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0.current()
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        panic!("historical reader attempted a witness mutation");
    }
}

#[tokio::test]
async fn history_reopens_original_publication_without_a_writer_or_runtime() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let identity = identity(root.path())?;
    let fence = fence(&identity)?;
    let store = AutomationStore::open(&identity.layout).await?;
    let sources = vec![source("A", b"original input"), source("C", b"unused input")];
    let owner = Source::create(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    let request = owner.build(&identity, &record("A"))?;
    let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = Arc::clone(&model.calls);
    let mut driver = CircuitTaskDriverV1 {
        store: store.clone(),
        fence: fence.clone(),
        inputs: owner.clone(),
        cells: AgentdCircuitCellOwnerV1::new(
            registry()?,
            cell_owner(root.path(), &sources)?,
            model,
            cell::Encoder,
        ),
    };
    let receipt = driver
        .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
        .await?;
    owner.publish_result(&identity, &record("A"), &receipt)?;
    let published = owner.read_publication(&identity, &record("A"))?;
    drop(driver);
    drop(owner);
    store.close().await;
    let original = [
        "source-journal",
        "source-witness",
        "cell-journal",
        "cell-witness",
    ]
    .into_iter()
    .map(|name| fs::read(root.path().join(name)))
    .collect::<std::io::Result<Vec<_>>>()?;
    let mut successor = identity.clone();
    successor.spawn_generation += 1;
    assert!(
        HistoricalCircuitTaskSourceV1::open(
            File::open(root.path().join("source-journal"))?,
            NoWriteWitness(witness(root.path(), "source-witness")?),
            &successor,
            &fence,
            &registry()?,
            sources.clone(),
        )
        .is_err()
    );
    let mut history = HistoricalCircuitTaskSourceV1::open(
        File::open(root.path().join("source-journal"))?,
        NoWriteWitness(witness(root.path(), "source-witness")?),
        &identity,
        &fence,
        &registry()?,
        sources,
    )?;
    assert_eq!(history.read_run_publication(&cell::id("A"))?, published);
    let observation = history.observe_run_publication(&cell::id("A"))?;
    assert_eq!(observation.publication(), &published);
    assert_eq!(observation.original_identity(), &identity);
    assert_eq!(observation.original_fence(), &fence);
    assert_eq!(
        history.read_run_publication(&cell::id("C")),
        Err(Error::ReconciliationRequired)
    );
    assert_eq!(history.read_run_publication(&cell::id("A"))?, published);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        [
            "source-journal",
            "source-witness",
            "cell-journal",
            "cell-witness"
        ]
        .into_iter()
        .map(|name| fs::read(root.path().join(name)))
        .collect::<std::io::Result<Vec<_>>>()?,
        original
    );
    let mut corrupt = original[0].clone();
    *corrupt
        .last_mut()
        .ok_or_else(|| anyhow::anyhow!("missing journal checksum"))? ^= 1;
    let mut fault = OpenOptions::new()
        .write(true)
        .open(root.path().join("source-journal"))?;
    fault.write_all(&corrupt)?;
    fault.sync_all()?;
    assert_eq!(
        history.read_run_publication(&cell::id("A")),
        Err(Error::CommitUncertain)
    );
    fault.seek(SeekFrom::Start(0))?;
    fault.write_all(&original[0])?;
    fault.sync_all()?;
    assert_eq!(
        history.read_run_publication(&cell::id("A")),
        Err(Error::CommitUncertain)
    );
    assert_eq!(fs::read(root.path().join("source-journal"))?, original[0]);
    Ok(())
}

#[test]
fn history_never_acknowledges_suffixes_or_completes_pending_stages() -> anyhow::Result<()> {
    for (fail_sequence, failure) in [2, 3].into_iter().flat_map(|sequence| {
        [WitnessFailure::BeforeWrite, WitnessFailure::AfterWrite]
            .into_iter()
            .map(move |failure| (sequence, failure))
    }) {
        let root = tempfile::tempdir()?;
        let identity = identity(root.path())?;
        let fence = fence(&identity)?;
        let sources = vec![source("A", b"original input")];
        let owner = DurableCircuitTaskSourceV1::create(
            opened(root.path(), "source-journal")?,
            LostAckWitness {
                original: witness(root.path(), "source-witness")?,
                fail_sequence: Arc::new(AtomicU64::new(fail_sequence)),
                failure,
            },
            &identity,
            &fence,
            &registry()?,
            sources.clone(),
        )?;
        assert!(owner.build(&identity, &record("A")).is_err());
        drop(owner);
        let original = ["source-journal", "source-witness"]
            .into_iter()
            .map(|name| fs::read(root.path().join(name)))
            .collect::<std::io::Result<Vec<_>>>()?;
        let history = HistoricalCircuitTaskSourceV1::open(
            File::open(root.path().join("source-journal"))?,
            NoWriteWitness(witness(root.path(), "source-witness")?),
            &identity,
            &fence,
            &registry()?,
            sources,
        );
        match failure {
            WitnessFailure::BeforeWrite => {
                assert_eq!(history.err(), Some(Error::ReconciliationRequired));
            }
            WitnessFailure::AfterWrite => {
                assert_eq!(
                    history?.read_run_publication(&cell::id("A")),
                    Err(Error::ReconciliationRequired)
                );
            }
        }
        assert_eq!(
            ["source-journal", "source-witness"]
                .into_iter()
                .map(|name| fs::read(root.path().join(name)))
                .collect::<std::io::Result<Vec<_>>>()?,
            original
        );
    }
    Ok(())
}

#[test]
fn history_refuses_original_withdrawal() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let identity = identity(root.path())?;
    let fence = fence(&identity)?;
    let sources = vec![source("A", b"withdrawn original")];
    let owner = Source::create(
        opened(root.path(), "source-journal")?,
        witness(root.path(), "source-witness")?,
        &identity,
        &fence,
        &registry()?,
        sources.clone(),
    )?;
    owner.withdraw_source(&cell::id("A"))?;
    drop(owner);
    let mut history = HistoricalCircuitTaskSourceV1::open(
        File::open(root.path().join("source-journal"))?,
        NoWriteWitness(witness(root.path(), "source-witness")?),
        &identity,
        &fence,
        &registry()?,
        sources,
    )?;
    assert_eq!(
        history.read_run_publication(&cell::id("A")),
        Err(Error::Unavailable)
    );
    Ok(())
}
