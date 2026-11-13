//! Version export admission over actual original T/E and publication owners.
//! PublicationFixture is an existing completed mechanism fixture, not the new
//! Fresh Root ten-owner path. All role credentials and B measurements remain
//! test inputs. Corruptions edit only untrusted cold expected metadata.

use super::*;
use crate::OriginalCircuitPublishedEvidenceReadbackV1 as Shared;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use anyhow::Context as _;

struct ExportCase {
    fixture: Option<Box<PublicationFixture>>,
    task: Option<support::Session>,
    held: Option<HeldPredecessors>,
    peers: Option<HeldPeers>,
    version: Option<Arc<Version>>,
}

impl ExportCase {
    async fn ready(corrupt_signature: Option<usize>) -> anyhow::Result<Self> {
        let fixture = Box::new(Box::pin(PublicationFixture::ready()).await?);
        let mut case = Self {
            fixture: Some(fixture),
            task: None,
            held: None,
            peers: None,
            version: None,
        };
        if let Err(error) = Box::pin(case.initialize(corrupt_signature)).await {
            let cleanup = case.finish().await;
            return Err(error.context(format!("original export setup cleanup: {cleanup:?}")));
        }
        Ok(case)
    }

    async fn initialize(&mut self, corrupt_signature: Option<usize>) -> anyhow::Result<()> {
        let fixture = self
            .fixture
            .as_deref()
            .context("same original publication fixture")?;
        let (held, peers) = Box::pin(held_predecessors(fixture)).await?;
        let dataset = held.dataset_receipt.clone();
        self.held = Some(held);
        self.peers = Some(peers);
        let (task, mut recovery) = Box::pin(publish_for_recovery(
            self.fixture
                .as_deref_mut()
                .context("same original fixture")?,
            &dataset,
        ))
        .await?;
        self.task = Some(task);
        if let Some(index) = corrupt_signature {
            anyhow::ensure!(
                matches!(index, 2 | 3),
                "only original T or E expected signature"
            );
            let signature = recovery
                .attestations
                .get_mut(index)
                .context("complete original cold signature vector")?;
            let byte = signature
                .signature
                .first_mut()
                .context("nonempty original signature")?;
            *byte ^= 1;
        }
        self.version = Some(cold_version(
            self.fixture.as_deref().context("same original fixture")?,
            self.held
                .take()
                .context("one original predecessor connection set")?,
            recovery,
        )?);
        Ok(())
    }

    fn host(&self) -> anyhow::Result<Arc<Version>> {
        Ok(Arc::clone(
            self.version.as_ref().context("actual cold Version")?,
        ))
    }

    fn fixture(&self) -> anyhow::Result<&PublicationFixture> {
        self.fixture.as_deref().context("same original fixture")
    }

    fn fixture_mut(&mut self) -> anyhow::Result<&mut PublicationFixture> {
        self.fixture.as_deref_mut().context("same original fixture")
    }

    fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let f = self.fixture()?;
        let mut bytes = f.publication_bytes()?;
        bytes.extend(f.host.original.predecessor_bytes()?);
        bytes.extend(f.host.upstream_files()?);
        bytes.extend(f.host.original_files()?);
        Ok(bytes)
    }

    fn cell_has_no_additional_transition(&self) -> anyhow::Result<bool> {
        Ok(self
            .task
            .as_ref()
            .context("same actual published C")?
            .cell
            .snapshot(&self.fixture()?.source_c.scope)?
            .revision
            == 0)
    }

    async fn finish(mut self) -> anyhow::Result<()> {
        // Aliases are scoped inside the result future and drop before cleanup.
        // Close clients first; join every peer even when another peer failed.
        drop(self.version.take());
        drop(self.held.take());
        let mut failures = Vec::new();
        if let Some(peers) = self.peers.take() {
            let dataset = material_ports::finish(peers.dataset);
            let trainer = peers
                .trainer
                .join()
                .map_err(|_| anyhow::anyhow!("original T readback peer panicked"))
                .and_then(|value| value.map_err(anyhow::Error::from));
            let evaluator = peers
                .evaluator
                .join()
                .map_err(|_| anyhow::anyhow!("original E readback peer panicked"))
                .and_then(|value| value);
            for result in [dataset, trainer, evaluator] {
                if let Err(error) = result {
                    failures.push(error.to_string());
                }
            }
        }
        if let Some(mut task) = self.task.take() {
            if let Err(error) = task.stop().await {
                failures.push(error.to_string());
            }
            drop(task);
        }
        if let Some(fixture) = self.fixture.take()
            && let Err(error) = (*fixture).finish().await
        {
            failures.push(error.to_string());
        }
        anyhow::ensure!(
            failures.is_empty(),
            "all original export peers joined: {failures:?}"
        );
        Ok(())
    }
}

async fn finish_case(result: anyhow::Result<()>, case: ExportCase) -> anyhow::Result<()> {
    let cleanup = case.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup)) => Err(error.context(format!("original cleanup: {cleanup:#}"))),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn published_shared_export_requires_actual_cold_admission_and_retains_same_clients()
-> anyhow::Result<()> {
    let case = Box::pin(ExportCase::ready(None)).await?;
    let result: anyhow::Result<()> = async {
        let host = case.host()?;
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "cold enum is not admitted"
        );
        let before = case.original_bytes()?;
        let first = Version::share_original_evaluated_readbacks(Arc::clone(&host)).await?;
        anyhow::ensure!(
            host.fixture_original_selection_reader_installed()?,
            "actual recovery admits the reader"
        );
        let second = Version::share_original_evaluated_readbacks(Arc::clone(&host)).await?;
        anyhow::ensure!(
            first.fixture_same_original_clients(&second),
            "same original two client allocations"
        );
        Shared::read_original_predecessors(&first).await?;
        anyhow::ensure!(
            matches!(
                Version::prepare_original_version_fixture(Arc::clone(&host)).await,
                Err(VersionError::ReadbackRequired)
            ),
            "cold export never restores Prepare"
        );
        anyhow::ensure!(
            matches!(
                Version::run_original_issuer_fixture(Arc::clone(&host)).await,
                Err(VersionError::ReadbackRequired)
            ),
            "cold export never restores FinalUse"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "readback leaves original journals unchanged"
        );
        anyhow::ensure!(
            case.cell_has_no_additional_transition()?,
            "no additional C Cell transition"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cold_published_enum_with_withdrawn_b_cannot_export_shared_clients() -> anyhow::Result<()> {
    let mut case = Box::pin(ExportCase::ready(None)).await?;
    let result: anyhow::Result<()> = async {
        let host = case.host()?;
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "initially unadmitted"
        );
        case.fixture_mut()?.host.retention_b.withdraw_target()?;
        let before = case.original_bytes()?;
        anyhow::ensure!(
            matches!(
                Version::share_original_evaluated_readbacks(Arc::clone(&host)).await,
                Err(VersionError::Evaluation(
                    crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                ))
            ),
            "actual E refuses the original withdrawn B"
        );
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "failed admission leaves no reader"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "failed read does not repair B or publish"
        );
        anyhow::ensure!(
            case.cell_has_no_additional_transition()?,
            "no additional C Cell transition"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cold_changed_artifact_current_cannot_export_shared_clients() -> anyhow::Result<()> {
    let mut case = Box::pin(ExportCase::ready(None)).await?;
    let result: anyhow::Result<()> = async {
        let host = case.host()?;
        case.fixture_mut()?
            .host
            .original
            .version
            .advance_artifact_current()?;
        let before = case.original_bytes()?;
        anyhow::ensure!(
            matches!(
                Version::share_original_evaluated_readbacks(Arc::clone(&host)).await,
                Err(VersionError::CommitUncertain)
            ),
            "actual Artifact CURRENT changed before reader admission"
        );
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "no reader from changed CURRENT"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "failed export has no publication repair"
        );
        anyhow::ensure!(
            case.cell_has_no_additional_transition()?,
            "no additional C Cell transition"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn repeated_shared_export_rechecks_current_original_b() -> anyhow::Result<()> {
    let mut case = Box::pin(ExportCase::ready(None)).await?;
    let result: anyhow::Result<()> = async {
        let host = case.host()?;
        let original = Version::share_original_evaluated_readbacks(Arc::clone(&host)).await?;
        anyhow::ensure!(
            host.fixture_original_selection_reader_installed()?,
            "first original admission"
        );
        case.fixture_mut()?.host.retention_b.withdraw_target()?;
        let before = case.original_bytes()?;
        anyhow::ensure!(
            Version::share_original_evaluated_readbacks(Arc::clone(&host))
                .await
                .is_err(),
            "an existing shared allocation is not cached current authority",
        );
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "failed current read removes new admission"
        );
        anyhow::ensure!(
            Shared::read_original_predecessors(&original).await.is_err(),
            "held alias rereads original owners"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "no replay or renewal after withdrawal"
        );
        anyhow::ensure!(
            case.cell_has_no_additional_transition()?,
            "no additional C Cell transition"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

async fn reject_changed_expected_signature(index: usize) -> anyhow::Result<()> {
    let case = Box::pin(ExportCase::ready(Some(index))).await?;
    let result: anyhow::Result<()> = async {
        let host = case.host()?;
        let before = case.original_bytes()?;
        anyhow::ensure!(
            matches!(
                Version::share_original_evaluated_readbacks(Arc::clone(&host)).await,
                Err(VersionError::Binding(
                    "same original complete cold E/D/T checkpoint"
                ))
            ),
            "the complete original signature, not only receipt fields, must match"
        );
        anyhow::ensure!(
            !host.fixture_original_selection_reader_installed()?,
            "wrong original signature cannot admit a reader"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "bad expected bytes cannot rewrite original evidence"
        );
        anyhow::ensure!(
            case.cell_has_no_additional_transition()?,
            "no additional C Cell transition"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cold_changed_expected_training_signature_cannot_export_shared_clients()
-> anyhow::Result<()> {
    reject_changed_expected_signature(2).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cold_changed_expected_evaluation_signature_cannot_export_shared_clients()
-> anyhow::Result<()> {
    reject_changed_expected_signature(3).await
}
