//! Actual cold Version/T/B/S/C mechanisms. Original fixture credentials and
//! same-process transports are explicit; these are not Fresh Root or public
//! cross-UID qualification. No successful response or opaque S is fabricated.

use super::*;
use anyhow::Context as _;
use std::os::unix::fs::OpenOptionsExt as _;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptSourcesV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitPublishedEvidenceReadbackV1;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use crate::OriginalCircuitSelectionCommandOwnerV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::circuit_feature_current::OriginalCircuitCompletionReadinessClientV1;
use crate::circuit_feature_current::original_evaluated_readiness_fixture as readiness;
use crate::circuit_feature_current::original_learning_read_fixture as reads;

type Selector = OriginalCircuitSelectionReceiptOwnerV1<FileAnchorWitnessStore>;
type Server = tokio::task::JoinHandle<Result<u64, VersionError>>;

struct NextUseCase {
    fixture: Option<Box<PublicationFixture>>,
    task: Option<support::Session>,
    held: Option<HeldPredecessors>,
    dataset_receipt: Option<OriginalCellQ24MaterialCommandReceiptV1>,
    peers: Option<HeldPeers>,
    version: Option<Arc<Version>>,
    shared: Option<OriginalCircuitPublishedEvidenceReadbackV1>,
    selector_home: Option<tempfile::TempDir>,
    selector: Option<Selector>,
    selector_host: Option<Arc<OriginalCircuitSelectionCommandOwnerV1<FileAnchorWitnessStore>>>,
    selector_server: Option<Server>,
    selection: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
    readiness: Option<OriginalCircuitCompletionReadinessClientV1>,
    live: Option<OriginalCircuitLearningReadClientV1>,
    servers: Vec<Server>,
}

impl NextUseCase {
    async fn ready() -> anyhow::Result<Self> {
        let fixture = Box::new(Box::pin(PublicationFixture::ready()).await?);
        let mut case = Self {
            fixture: Some(fixture),
            task: None,
            held: None,
            dataset_receipt: None,
            peers: None,
            version: None,
            shared: None,
            selector_home: None,
            selector: None,
            selector_host: None,
            selector_server: None,
            selection: None,
            readiness: None,
            live: None,
            servers: Vec::new(),
        };
        if let Err(error) = Box::pin(case.initialize()).await {
            let cleanup = case.finish().await;
            return Err(error.context(format!("original NextUse setup cleanup: {cleanup:?}")));
        }
        Ok(case)
    }

    async fn initialize(&mut self) -> anyhow::Result<()> {
        let (held, peers) = Box::pin(held_predecessors(self.fixture()?)).await?;
        let dataset = held.dataset_receipt.clone();
        self.dataset_receipt = Some(dataset.clone());
        self.held = Some(held);
        self.peers = Some(peers);
        let (task, recovery) = Box::pin(publish_for_recovery(
            self.fixture
                .as_deref_mut()
                .context("same original fixture")?,
            &dataset,
        ))
        .await?;
        self.task = Some(task);

        let home = tempfile::tempdir()?;
        let open = |name: &str| -> anyhow::Result<std::fs::File> {
            Ok(std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(home.path().join(name))?)
        };
        let f = self.fixture()?;
        let witness = FileAnchorWitnessStore::open(
            open("selector.witness")?,
            codex_hepta_neuron::JournalScope {
                scope_digest: f.host.config.scope.binding(),
                objective_digest: f.host.config.signing.verifier.objective_digest(),
            },
            codex_hepta_types::Generation::new(1)?,
            16,
        )?;
        let mut selector = Selector::create_evaluated(
            open("selector.journal")?,
            witness,
            OriginalCircuitEvaluatedSelectionReceiptConfigV1 {
                context: f.context()?,
                signer: f.host.original.credentials.selector.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            SigningKey::from_bytes(&[46; 32]),
        )?;
        let (trainer, evaluator, peers) = f.clients()?;
        let selected = selector
            .attest_original_evaluated_selection(
                OriginalCircuitEvaluatedSelectionReceiptSourcesV1 {
                    snapshot: f.evaluation.snapshot(),
                    cell: &self.task()?.cell,
                    trainer: &trainer,
                    evaluator: &evaluator,
                },
            )
            .await;
        drop(trainer);
        drop(evaluator);
        let trainer_done = peers
            .trainer
            .join()
            .map_err(|_| anyhow::anyhow!("actual S Trainer peer panicked"));
        let evaluator_done = peers
            .evaluator
            .join()
            .map_err(|_| anyhow::anyhow!("actual S Evaluator peer panicked"));
        trainer_done??;
        evaluator_done??;
        self.selection = Some(selected?);
        self.selector = Some(selector);
        self.selector_home = Some(home);

        let held = self
            .held
            .take()
            .context("one original predecessor connection set")?;
        let host = cold_version(self.fixture()?, held, recovery)?;
        self.version = Some(Arc::clone(&host));
        // Exercise the new services after the original T/E clients have been
        // consumed into the sealed shared bundle. No replacement T/E is opened.
        self.shared = Some(Version::share_original_evaluated_readbacks(Arc::clone(&host)).await?);
        let context = ReadContext::for_original_selection(self.fixture()?.readback_context()?)?;
        let (live, channel) = reads::evaluated_client(context)?;
        self.selector_server = Some(tokio::spawn(
            Version::fixture_serve_original_selection_channel(Arc::clone(&host), channel),
        ));
        let selector = self
            .selector
            .take()
            .context("one original Selector receipt owner")?;
        let shared = self
            .shared
            .as_ref()
            .context("same sealed original T/E")?
            .clone();
        let selector_host = Arc::new(selector.into_evaluated_shared_command_owner(live, shared)?);
        self.selector_host = Some(Arc::clone(&selector_host));
        let before = self.original_bytes()?;
        let current =
            OriginalCircuitSelectionCommandOwnerV1::read_original_evaluated_receipt(selector_host)
                .await?;
        let original = self.selection.as_ref().context("original completed S")?;
        anyhow::ensure!(
            (current.snapshot(), current.receipt(), current.attestation())
                == (
                    original.snapshot(),
                    original.receipt(),
                    original.attestation()
                ),
            "same-host delivery preserves the entire actual S and signatures"
        );
        anyhow::ensure!(
            self.original_bytes()? == before,
            "the same original S local readback cannot execute or resign"
        );
        self.selection = Some(current);
        Ok(())
    }

    fn fixture(&self) -> anyhow::Result<&PublicationFixture> {
        self.fixture.as_deref().context("same original fixture")
    }

    fn task(&self) -> anyhow::Result<&support::Session> {
        self.task.as_ref().context("same actual published C")
    }

    fn host(&self) -> anyhow::Result<Arc<Version>> {
        Ok(Arc::clone(
            self.version.as_ref().context("same published Version")?,
        ))
    }

    fn selection(&self) -> anyhow::Result<OriginalCircuitEvaluatedSelectionReceiptV1> {
        Ok(self
            .selection
            .as_ref()
            .context("actual original S")?
            .clone())
    }

    fn context(&self) -> anyhow::Result<ReadContext> {
        Ok(ReadContext::for_original_next_use(self.selection()?)?)
    }

    fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let f = self.fixture()?;
        let mut bytes = f.publication_bytes()?;
        bytes.extend(f.host.original.predecessor_bytes()?);
        bytes.extend(f.host.upstream_files()?);
        bytes.extend(f.host.original_files()?);
        let home = self.selector_home.as_ref().context("original S files")?;
        bytes.push(std::fs::read(home.path().join("selector.journal"))?);
        bytes.push(std::fs::read(home.path().join("selector.witness"))?);
        Ok(bytes)
    }

    fn start_readiness(&mut self) -> anyhow::Result<()> {
        let (client, channel) = readiness::client(self.context()?)?;
        let server = tokio::spawn(Version::fixture_serve_original_evaluated_next_use(
            self.host()?,
            self.selection()?,
            channel,
            true,
        ));
        self.readiness = Some(client);
        self.servers.push(server);
        Ok(())
    }

    fn start_readback(&mut self) -> anyhow::Result<()> {
        let (client, channel) = reads::evaluated_client(self.context()?)?;
        let server = tokio::spawn(Version::fixture_serve_original_evaluated_next_use(
            self.host()?,
            self.selection()?,
            channel,
            false,
        ));
        self.live = Some(client);
        self.servers.push(server);
        Ok(())
    }

    async fn finish(mut self) -> anyhow::Result<()> {
        // Close both consumers before awaiting the actual serving lanes. Do
        // not abort a blocking owner read or detach it to make teardown pass.
        drop(self.readiness.take());
        drop(self.live.take());
        let mut failures = Vec::new();
        for server in self.servers.drain(..) {
            match server.await {
                Ok(Ok(_)) => {}
                Ok(Err(error)) => failures.push(error.to_string()),
                Err(error) => failures.push(format!("actual C reader join: {error}")),
            }
        }
        drop(self.selector_host.take());
        if let Some(server) = self.selector_server.take() {
            match server.await {
                Ok(Ok(_)) => {}
                Ok(Err(error)) => failures.push(error.to_string()),
                Err(error) => failures.push(format!("original S reader join: {error}")),
            }
        }
        drop(self.shared.take());
        drop(self.version.take());
        drop(self.held.take());
        drop(self.selector.take());
        if let Some(peers) = self.peers.take() {
            let dataset = material_ports::finish(peers.dataset);
            let trainer = peers
                .trainer
                .join()
                .map_err(|_| anyhow::anyhow!("original T peer panicked"))
                .and_then(|value| value.map_err(anyhow::Error::from));
            let evaluator = peers
                .evaluator
                .join()
                .map_err(|_| anyhow::anyhow!("original E peer panicked"))
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
        if let Some(fixture) = self.fixture.take() {
            if let Err(error) = (*fixture).finish().await {
                failures.push(error.to_string());
            }
        }
        anyhow::ensure!(
            failures.is_empty(),
            "original NextUse cleanup: {failures:?}"
        );
        Ok(())
    }
}

async fn finish_case(result: anyhow::Result<()>, case: NextUseCase) -> anyhow::Result<()> {
    let cleanup = case.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup)) => Err(error.context(format!("original cleanup: {cleanup:#}"))),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_reads_same_c_after_real_completion() -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let before = case.original_bytes()?;
        case.start_readiness()?;
        anyhow::ensure!(
            case.readiness
                .as_ref()
                .context("readiness client")?
                .read_current()
                .await?
                .is_none(),
            "actual unexecuted C remains unresolved"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "readiness never dispatches C"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "readonly admission changes no original journal"
        );
        let publication = execute(case.task()?, 1).await?;
        let actual = read_receipt(case.task()?, &case.fixture()?.definition, &publication)?;
        anyhow::ensure!(
            actual.bundle_digest == case.fixture()?.bundle.digest()?,
            "C actually used the retained baseline"
        );
        let completed = case
            .readiness
            .as_ref()
            .context("same readiness client")?
            .read_current()
            .await?
            .context("actual original C completion")?;
        // The first real readiness response has completed admission. Starting
        // the second lane here does not queue concurrent original T/E reads.
        case.start_readback()?;
        let read = case
            .live
            .as_ref()
            .context("original C reader")?
            .read_current()
            .await?;
        anyhow::ensure!(
            read == completed,
            "both distinct purposes read the same original C"
        );
        anyhow::ensure!(
            matches!(read.observation(),
            LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
            if *retained_bundle == case.fixture()?.bundle.digest()?),
            "original next-use observation"
        );
        let host = case.host()?;
        anyhow::ensure!(
            matches!(
                Version::prepare_original_version_fixture(Arc::clone(&host)).await,
                Err(VersionError::ReadbackRequired)
            ),
            "read service cannot promote cold Prepare"
        );
        anyhow::ensure!(
            matches!(
                Version::run_original_issuer_fixture(host).await,
                Err(VersionError::ReadbackRequired)
            ),
            "read service cannot promote FinalUse"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rejects_another_actual_original_s_cut() -> anyhow::Result<()> {
    let first = Box::pin(NextUseCase::ready()).await?;
    let second = match Box::pin(NextUseCase::ready()).await {
        Ok(case) => case,
        Err(error) => return finish_case(Err(error), first).await,
    };
    let result: anyhow::Result<()> = async {
        let before = first.original_bytes()?;
        anyhow::ensure!(
            first
                .selection()?
                .original_context()
                .receipt_context_binding()
                != second
                    .selection()?
                    .original_context()
                    .receipt_context_binding(),
            "two actually completed original operations"
        );
        anyhow::ensure!(
            matches!(
                Version::fixture_require_original_evaluated_next_use(
                    first.host()?,
                    second.selection()?
                )
                .await,
                Err(VersionError::Binding(
                    "same original Version T/E and Selection cut"
                ))
            ),
            "an authentic foreign S is not this Version's full T/E pin"
        );
        anyhow::ensure!(
            first.original_bytes()? == before,
            "foreign S cannot publish or rewrite evidence"
        );
        anyhow::ensure!(
            first
                .task()?
                .cell
                .snapshot(&first.fixture()?.source_c.scope)?
                .revision
                == 0,
            "foreign S cannot start C"
        );
        Ok(())
    }
    .await;
    let result = finish_case(result, second).await;
    finish_case(result, first).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rechecks_actual_b_after_shared_export() -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        case.fixture
            .as_deref_mut()
            .context("original fixture")?
            .host
            .retention_b
            .withdraw_target()?;
        let before = case.original_bytes()?;
        anyhow::ensure!(
            matches!(
                Version::fixture_require_original_evaluated_next_use(
                    case.host()?,
                    case.selection()?
                )
                .await,
                Err(VersionError::Publication(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Evaluation(
                        crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                    )
                ))
            ),
            "actual B withdrawal cannot be satisfied by the retained shared bundle"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "readback refusal changes no original journals"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "unavailable B does not become NoUpdate or start C"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_refuses_four_cut_selection_requests() -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let before = case.original_bytes()?;
        let context = ReadContext::for_original_selection(case.fixture()?.readback_context()?)?;
        let (client, channel) = reads::evaluated_client(context)?;
        let server = tokio::spawn(Version::fixture_serve_original_evaluated_next_use(
            case.host()?,
            case.selection()?,
            channel,
            false,
        ));
        case.live = Some(client);
        case.servers.push(server);
        let client = case
            .live
            .as_ref()
            .context("actual four-cut Selection client")?;
        let first = client.read_current().await;
        let after = client.read_current().await;
        drop(case.live.take());
        let served = case
            .servers
            .pop()
            .context("original NextUse-only lane")?
            .await?;
        anyhow::ensure!(
            first.is_err(),
            "a valid original four-cut client is not five-cut NextUse"
        );
        anyhow::ensure!(
            matches!(after, Err(ReadError::Unavailable)),
            "wrong purpose consumes this channel"
        );
        anyhow::ensure!(
            served.is_err(),
            "server rejects the actual wrong-purpose request"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "wrong purpose changes no original journal"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "wrong purpose cannot start C"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

async fn deadline_case(already_expired: bool) -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let before = case.original_bytes()?;
        let observed = Arc::new(AtomicBool::new(false));
        let (client, channel) = readiness::client(case.context()?)?;
        let server = tokio::spawn(Version::fixture_evaluated_next_use_deadline_probe(
            case.host()?, case.selection()?, channel, already_expired, Arc::clone(&observed),
        ));
        case.readiness = Some(client);
        case.servers.push(server);
        let client = case.readiness.as_ref().context("same original readiness client")?;
        let first = client.read_current().await;
        let after = client.read_current().await;
        drop(case.readiness.take());
        let served = case.servers.pop().context("original deadline lane")?.await?;
        anyhow::ensure!(first.is_err(), "no expired original response is successful");
        anyhow::ensure!(matches!(after, Err(ReadError::Unavailable)), "failure consumes the same channel without retry");
        anyhow::ensure!(served.is_err(), "actual server preserves refusal");
        anyhow::ensure!(observed.load(Ordering::Acquire) == !already_expired,
            "pre-expiry refuses before IO; crossing case first produced the actual original response");
        anyhow::ensure!(case.original_bytes()? == before, "deadline failure cannot repair or publish");
        anyhow::ensure!(case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision == 0,
            "deadline failure cannot dispatch C");
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rejects_already_elapsed_absolute_end() -> anyhow::Result<()> {
    Box::pin(deadline_case(true)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rejects_original_response_crossing_absolute_end()
-> anyhow::Result<()> {
    Box::pin(deadline_case(false)).await
}

async fn b_withdrawal_after_admission_case(readiness: bool) -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        if readiness {
            case.start_readiness()?;
            anyhow::ensure!(
                case.readiness
                    .as_ref()
                    .context("original readiness lane")?
                    .read_current()
                    .await?
                    .is_none(),
                "actual first response admits pending C"
            );
        } else {
            let publication = execute(case.task()?, 1).await?;
            let actual = read_receipt(case.task()?, &case.fixture()?.definition, &publication)?;
            anyhow::ensure!(
                actual.bundle_digest == case.fixture()?.bundle.digest()?,
                "the original C completed with the retained baseline"
            );
            case.start_readback()?;
            let first = case
                .live
                .as_ref()
                .context("original next-use lane")?
                .read_current()
                .await?;
            anyhow::ensure!(
                matches!(
                    first.observation(),
                    LearningIterationObservationV1::RetainedModelNextUse { .. }
                ),
                "actual completed response proves this channel was already admitted"
            );
        }
        let revision = case
            .task()?
            .cell
            .snapshot(&case.fixture()?.source_c.scope)?
            .revision;
        case.fixture
            .as_deref_mut()
            .context("original B owner")?
            .host
            .retention_b
            .withdraw_target()?;
        let before = case.original_bytes()?;
        let (refused, fenced) = if readiness {
            let client = case
                .readiness
                .as_ref()
                .context("same admitted readiness lane")?;
            (
                client.read_current().await.map(|_| ()),
                client.read_current().await.map(|_| ()),
            )
        } else {
            let client = case.live.as_ref().context("same admitted next-use lane")?;
            (
                client.read_current().await.map(|_| ()),
                client.read_current().await.map(|_| ()),
            )
        };
        drop(case.readiness.take());
        drop(case.live.take());
        let served = case
            .servers
            .pop()
            .context("same original serving lane")?
            .await?;
        anyhow::ensure!(
            refused.is_err(),
            "later B withdrawal cannot reuse a successful admission"
        );
        anyhow::ensure!(
            matches!(fenced, Err(ReadError::Unavailable)),
            "the rejected original channel remains consumed without retry"
        );
        anyhow::ensure!(
            matches!(
                served,
                Err(VersionError::Publication(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Evaluation(
                        crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                    )
                ))
            ),
            "the concrete Version preserves the actual original B/E current-read failure"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "failed later reads cannot rewrite evidence or repair B"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == revision,
            "readonly failure neither starts C nor dispatches it again"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_readiness_rechecks_actual_b_after_channel_admission() -> anyhow::Result<()> {
    Box::pin(b_withdrawal_after_admission_case(true)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rechecks_actual_b_after_channel_admission() -> anyhow::Result<()> {
    Box::pin(b_withdrawal_after_admission_case(false)).await
}

#[path = "circuit_evaluated_version_local_readback_tests.rs"]
mod local_read;
