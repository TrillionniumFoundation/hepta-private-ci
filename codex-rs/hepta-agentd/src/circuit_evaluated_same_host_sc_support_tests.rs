//! Same-owner S/C mechanism fixture. Every successful receipt comes from the
//! original Material/T/E/S/C owners and existing enrolled fixture keys.
//! The original same-process transports are explicit; this is not a public
//! three-UID admission, Fresh Root run, or evidence of useful independent B.

use super::*;
use anyhow::Context as _;

use crate::OriginalCircuitCompletionReadinessClientV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptSourcesV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitNextUseCommandClientV1;
use crate::OriginalCircuitNextUseCommandContextV1;
use crate::OriginalCircuitNextUseCommandErrorV1;
use crate::OriginalCircuitNextUseCommandOwnerV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitPublishedEvidenceReadbackV1;
use crate::OriginalCircuitPublishedLocalReadV1;
use crate::OriginalCircuitSelectionCommandErrorV1;
use crate::OriginalCircuitSelectionCommandOwnerV1;
use crate::OriginalCircuitSelectionLocalReadbackV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::learning_iteration_evidence_client::next_use_command_test_support as completion_commands;

type Selector = OriginalCircuitSelectionReceiptOwnerV1<FileAnchorWitnessStore>;
type SelectorHost = OriginalCircuitSelectionCommandOwnerV1<FileAnchorWitnessStore>;
type Observer = OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>;
type ObserverHost = OriginalCircuitNextUseCommandOwnerV1<FileAnchorWitnessStore>;
type CompletionPeer = std::thread::JoinHandle<Result<u64, OriginalCircuitNextUseCommandErrorV1>>;

enum OriginalConnectionSets {
    One,
    Two,
}

enum OriginalSelectionState {
    Completed,
    Missing,
}

pub(super) struct SameHostCase {
    pub(super) fixture: Option<Box<PublicationFixture>>,
    task: Option<support::Session>,
    held: Option<HeldPredecessors>,
    peers: Option<HeldPeers>,
    alternate_held: Option<HeldPredecessors>,
    alternate_peers: Option<HeldPeers>,
    alternate_version: Option<Arc<Version>>,
    pub(super) alternate_shared: Option<OriginalCircuitPublishedEvidenceReadbackV1>,
    pub(super) dataset: Option<OriginalCellQ24MaterialCommandReceiptV1>,
    version: Option<Arc<Version>>,
    shared: Option<OriginalCircuitPublishedEvidenceReadbackV1>,
    selector_home: Option<tempfile::TempDir>,
    selector: Option<Selector>,
    selector_host: Option<Arc<SelectorHost>>,
    selection: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
    pub(super) local_s: Option<OriginalCircuitSelectionLocalReadbackV1>,
    pub(super) local_c: Option<OriginalCircuitPublishedLocalReadV1>,
    pub(super) readiness: Option<OriginalCircuitCompletionReadinessClientV1>,
    observer_home: Option<tempfile::TempDir>,
    observer_host: Option<Arc<ObserverHost>>,
    pub(super) completion: Option<OriginalCircuitNextUseCommandClientV1>,
    completion_peer: Option<CompletionPeer>,
}

impl SameHostCase {
    pub(super) async fn completed_selection() -> anyhow::Result<Self> {
        Self::initialize(
            OriginalSelectionState::Completed,
            OriginalConnectionSets::One,
        )
        .await
    }

    pub(super) async fn missing_selection() -> anyhow::Result<Self> {
        Self::initialize(OriginalSelectionState::Missing, OriginalConnectionSets::One).await
    }

    pub(super) async fn with_distinct_original_connections() -> anyhow::Result<Self> {
        Self::initialize(
            OriginalSelectionState::Completed,
            OriginalConnectionSets::Two,
        )
        .await
    }

    async fn initialize(
        selection: OriginalSelectionState,
        connections: OriginalConnectionSets,
    ) -> anyhow::Result<Self> {
        let fixture = Box::new(Box::pin(PublicationFixture::ready()).await?);
        let mut case = Self {
            fixture: Some(fixture),
            task: None,
            held: None,
            peers: None,
            dataset: None,
            alternate_held: None,
            alternate_peers: None,
            alternate_version: None,
            alternate_shared: None,
            version: None,
            shared: None,
            selector_home: None,
            selector: None,
            selector_host: None,
            selection: None,
            local_s: None,
            local_c: None,
            readiness: None,
            observer_home: None,
            observer_host: None,
            completion: None,
            completion_peer: None,
        };
        let initialized = Box::pin(case.initialize_originals(selection, connections)).await;
        if let Err(error) = initialized {
            let cleanup = case.finish().await;
            return Err(error.context(format!("same-owner S/C setup cleanup: {cleanup:?}")));
        }
        Ok(case)
    }

    async fn initialize_originals(
        &mut self,
        selection_state: OriginalSelectionState,
        connections: OriginalConnectionSets,
    ) -> anyhow::Result<()> {
        let (held, peers) = match connections {
            OriginalConnectionSets::One => Box::pin(held_predecessors(self.fixture()?)).await?,
            OriginalConnectionSets::Two => {
                let mut sets = Box::pin(connections::two_original_sets(self.fixture()?)).await?;
                let (held, peers) = sets
                    .pop()
                    .context("second actual original connection set")?;
                self.alternate_held = Some(held);
                self.alternate_peers = Some(peers);
                sets.pop().context("first actual original connection set")?
            }
        };
        let dataset = held.dataset_receipt.clone();
        self.dataset = Some(dataset.clone());
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
        let selector = self.create_selector(&home)?;
        self.selector_home = Some(home);
        self.selector = Some(selector);
        if matches!(selection_state, OriginalSelectionState::Completed) {
            // This uses real current owner reads and the original S journal.
            // It never supplies a success DTO as a transport response.
            let fixture = self.fixture.as_deref().context("original fixture")?;
            let task = self.task.as_ref().context("original C Session")?;
            let selector = self.selector.as_mut().context("original S custody")?;
            let (trainer, evaluator, peers) = fixture.clients()?;
            let selected = selector
                .attest_original_evaluated_selection(
                    OriginalCircuitEvaluatedSelectionReceiptSourcesV1 {
                        snapshot: fixture.evaluation.snapshot(),
                        cell: &task.cell,
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
                .map_err(|_| anyhow::anyhow!("original S Trainer peer panicked"))
                .and_then(|result| result.map_err(anyhow::Error::from));
            let evaluator_done = peers
                .evaluator
                .join()
                .map_err(|_| anyhow::anyhow!("original S Evaluator peer panicked"))
                .and_then(|result| result);
            trainer_done?;
            evaluator_done?;
            self.selection = Some(selected?);
        }

        let alternate_recovery =
            self.alternate_held
                .as_ref()
                .map(|_| OriginalCircuitRetainedVersionRecoveryV1 {
                    training: recovery.training.clone(),
                    attestations: recovery.attestations.clone(),
                    intent_digest: recovery.intent_digest,
                    cell: recovery.cell.clone(),
                    source: Arc::clone(&recovery.source),
                    identity: recovery.identity.clone(),
                    current: Arc::clone(&recovery.current),
                    artifacts: Arc::clone(&recovery.artifacts),
                    artifact_checkpoint: crate::OriginalCircuitRetainedArtifactCheckpointV1 {
                        operation_id: recovery.artifact_checkpoint.operation_id.clone(),
                        intent_digest: recovery.artifact_checkpoint.intent_digest,
                    },
                    artifact_selection: recovery.artifact_selection.clone(),
                    artifact_verifier: recovery.artifact_verifier.clone(),
                });
        let held = self
            .held
            .take()
            .context("one original predecessor connection set")?;
        let host = cold_version(self.fixture()?, held, recovery)?;
        self.version = Some(Arc::clone(&host));
        let shared = Version::share_original_evaluated_readbacks(Arc::clone(&host)).await?;
        self.shared = Some(shared.clone());
        if let Some(recovery) = alternate_recovery {
            let held = self
                .alternate_held
                .take()
                .context("second actual original predecessor set")?;
            let other = cold_version(self.fixture()?, held, recovery)?;
            self.alternate_version = Some(Arc::clone(&other));
            self.alternate_shared = Some(Version::share_original_evaluated_readbacks(other).await?);
        }
        let local = Version::open_original_evaluated_selection_local_read(
            host,
            Duration::from_millis(500),
            Duration::from_secs(300),
        )
        .await?;
        let live = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_selection(
            local,
            self.fixture()?.context()?,
        )?;
        let selector = self.selector.take().context("one original S owner")?;
        self.selector_host = Some(Arc::new(
            Selector::into_evaluated_local_shared_command_owner(selector, live, shared)?,
        ));
        Ok(())
    }

    pub(super) fn fixture(&self) -> anyhow::Result<&PublicationFixture> {
        self.fixture.as_deref().context("same original fixture")
    }

    pub(super) fn task(&self) -> anyhow::Result<&support::Session> {
        self.task.as_ref().context("same actual C Session")
    }

    pub(super) fn host(&self) -> anyhow::Result<Arc<Version>> {
        Ok(Arc::clone(
            self.version.as_ref().context("same original Version")?,
        ))
    }

    pub(super) fn selector_host(&self) -> anyhow::Result<Arc<SelectorHost>> {
        Ok(Arc::clone(
            self.selector_host
                .as_ref()
                .context("same original S command owner")?,
        ))
    }

    pub(super) fn selection(&self) -> anyhow::Result<OriginalCircuitEvaluatedSelectionReceiptV1> {
        Ok(self
            .selection
            .as_ref()
            .context("actually completed original S")?
            .clone())
    }

    pub(super) fn shared(&self) -> anyhow::Result<OriginalCircuitPublishedEvidenceReadbackV1> {
        Ok(self
            .shared
            .as_ref()
            .context("same sealed original T/E")?
            .clone())
    }

    pub(super) async fn export_selection(&mut self, lifetime: Duration) -> anyhow::Result<()> {
        self.local_s = Some(
            SelectorHost::open_original_evaluated_local_readback(
                self.selector_host()?,
                Duration::from_millis(500),
                lifetime,
            )
            .await?,
        );
        Ok(())
    }

    pub(super) fn create_selector(&self, home: &tempfile::TempDir) -> anyhow::Result<Selector> {
        Ok(Selector::create_evaluated(
            opened(home.path(), "selector.journal", /*create*/ true)?,
            receipt_witness(
                home,
                "selector.witness",
                self.fixture()?,
                WitnessOrigin::New,
            )?,
            OriginalCircuitEvaluatedSelectionReceiptConfigV1 {
                context: self.fixture()?.context()?,
                signer: self.fixture()?.host.original.credentials.selector.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            SigningKey::from_bytes(&[46; 32]),
        )?)
    }

    pub(super) async fn install_completion(&mut self) -> anyhow::Result<()> {
        let selected = self.selection()?;
        let local = Version::open_original_evaluated_next_use_local_read(
            self.host()?,
            selected.clone(),
            Duration::from_millis(500),
            Duration::from_secs(300),
        )
        .await?;
        self.local_c = Some(local.clone());
        let live = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_next_use(
            local,
            selected.clone(),
        )?;
        self.readiness = Some(
            OriginalCircuitCompletionReadinessClientV1::bind_original_evaluated_local_read(
                &live,
                &self.fixture()?.host.original.command_config,
                self.dataset.as_ref().context("actual original D")?,
                &selected,
            )?,
        );
        let home = tempfile::tempdir()?;
        let observer = Observer::create_evaluated(
            opened(home.path(), "observer.journal", /*create*/ true)?,
            receipt_witness(
                &home,
                "observer.witness",
                self.fixture()?,
                WitnessOrigin::New,
            )?,
            OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
                selection: selected,
                signer: self.fixture()?.host.original.credentials.observer.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            SigningKey::from_bytes(&[43; 32]),
        )?;
        self.observer_home = Some(home);
        self.install_observer(observer, live, CompletionOrigin::Fresh)?;
        Ok(())
    }

    fn install_observer(
        &mut self,
        observer: Observer,
        live: OriginalCircuitLearningReadClientV1,
        origin: CompletionOrigin,
    ) -> anyhow::Result<()> {
        let host = Arc::new(Observer::into_evaluated_local_shared_command_owner(
            observer,
            live,
            self.shared()?,
            self.local_s
                .as_ref()
                .context("same completed S local capability")?
                .clone(),
        )?);
        self.observer_host = Some(Arc::clone(&host));
        let context = OriginalCircuitNextUseCommandContextV1::from_original_evaluated_selection(
            &self.selection()?,
        )?;
        let (client, channel) = completion_commands::client(
            context,
            matches!(origin, CompletionOrigin::Recovered),
            /*retained*/ None,
        )?;
        self.completion = Some(client);
        self.completion_peer = Some(completion_commands::serve(host, channel));
        Ok(())
    }

    pub(super) async fn recover_completed_observer(&mut self) -> anyhow::Result<()> {
        self.close_completion()?;
        drop(self.observer_host.take());
        let selected = self.selection()?;
        let home = self
            .observer_home
            .as_ref()
            .context("same original C Observer files")?;
        let observer = Observer::recover_evaluated(
            opened(home.path(), "observer.journal", /*create*/ false)?,
            receipt_witness(
                home,
                "observer.witness",
                self.fixture()?,
                WitnessOrigin::Existing,
            )?,
            OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
                selection: selected.clone(),
                signer: self.fixture()?.host.original.credentials.observer.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            SigningKey::from_bytes(&[43; 32]),
        )?;
        let live = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_next_use(
            self.local_c
                .as_ref()
                .context("same original local C backend")?
                .clone(),
            selected,
        )?;
        self.install_observer(observer, live, CompletionOrigin::Recovered)
    }

    pub(super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let f = self.fixture()?;
        let mut bytes = f.publication_bytes()?;
        bytes.extend(f.host.original.predecessor_bytes()?);
        bytes.extend(f.host.upstream_files()?);
        bytes.extend(f.host.original_files()?);
        for (home, names) in [
            (
                self.selector_home.as_ref(),
                ["selector.journal", "selector.witness"],
            ),
            (
                self.observer_home.as_ref(),
                ["observer.journal", "observer.witness"],
            ),
        ] {
            if let Some(home) = home {
                for name in names {
                    bytes.push(std::fs::read(home.path().join(name))?);
                }
            }
        }
        Ok(bytes)
    }

    fn close_completion(&mut self) -> anyhow::Result<()> {
        drop(self.completion.take());
        if let Some(peer) = self.completion_peer.take() {
            peer.join()
                .map_err(|_| anyhow::anyhow!("actual Observer peer panicked"))??;
        }
        Ok(())
    }

    pub(super) async fn finish(mut self) -> anyhow::Result<()> {
        let mut errors = Vec::new();
        if let Err(error) = self.close_completion() {
            errors.push(error.to_string());
        }
        drop(self.observer_host.take());
        drop(self.readiness.take());
        drop(self.local_c.take());
        drop(self.local_s.take());
        drop(self.selector_host.take());
        drop(self.shared.take());
        drop(self.alternate_shared.take());
        drop(self.version.take());
        drop(self.alternate_version.take());
        drop(self.held.take());
        drop(self.alternate_held.take());
        drop(self.selector.take());
        for peers in [self.peers.take(), self.alternate_peers.take()]
            .into_iter()
            .flatten()
        {
            connections::collect_peer_cleanup(peers, &mut errors);
        }
        if let Some(mut task) = self.task.take()
            && let Err(error) = task.stop().await
        {
            errors.push(error.to_string());
        }
        if let Some(fixture) = self.fixture.take()
            && let Err(error) = (*fixture).finish().await
        {
            errors.push(error.to_string());
        }
        anyhow::ensure!(errors.is_empty(), "same-owner S/C cleanup: {errors:?}");
        Ok(())
    }
}

enum WitnessOrigin {
    New,
    Existing,
}

fn receipt_witness(
    home: &tempfile::TempDir,
    name: &str,
    fixture: &PublicationFixture,
    origin: WitnessOrigin,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(home.path(), name, matches!(origin, WitnessOrigin::New))?,
        codex_hepta_neuron::JournalScope {
            scope_digest: fixture.host.config.scope.binding(),
            objective_digest: fixture.host.config.signing.verifier.objective_digest(),
        },
        codex_hepta_types::Generation::new(1)?,
        16,
    )?)
}

enum CompletionOrigin {
    Fresh,
    Recovered,
}

pub(super) async fn finish_case(
    result: anyhow::Result<()>,
    case: SameHostCase,
) -> anyhow::Result<()> {
    let cleanup = case.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup)) => Err(error.context(format!("original cleanup: {cleanup:#}"))),
    }
}

#[path = "circuit_evaluated_same_host_sc_connections_tests.rs"]
mod connections;

#[path = "circuit_evaluated_same_host_sc_tests.rs"]
mod tests;
