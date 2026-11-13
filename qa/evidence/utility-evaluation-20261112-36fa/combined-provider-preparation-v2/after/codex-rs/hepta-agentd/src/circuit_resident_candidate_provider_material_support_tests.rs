//! Same-A material and an unstarted Fresh Trainer for provider mechanism tests.
//! Credentials, independent terminal label and future C admission are fixtures.
//! No Material Execute, Training, Evaluation or Model work is performed here.
//! PreparedBPanel must be created from ProviderAdmission before passing its
//! frozen evaluation_profile into UnstartedProvider::new.

use super::*;
use anyhow::Context as _;
use std::time::Duration;

use crate::OriginalCellQ24MaterialCommandOwnerV1;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialReceiptFilesV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24TrainingBootstrapConfigV1;
use crate::OriginalCellQ24TrainingBootstrapCustodyV1;
use crate::OriginalCellQ24TrainingBootstrapOwnerV1;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;

pub(super) type Trainer =
    OriginalCellQ24TrainingBootstrapOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type MaterialOwner = OriginalCellQ24MaterialCommandOwnerV1<
    FileAnchorWitnessStore, FileAnchorWitnessStore, FileAnchorWitnessStore,
>;

/// Preview is not RunStart authority. The same A Admission is later signed by
/// support::start and actually executed through the normal ObjectiveStart path.
pub(super) struct ProviderAdmission {
    a: support::Admission,
    c: support::Admission,
    pub(super) objective: Digest32,
    pub(super) trust_time: u64,
    pub(super) source_c: crate::CircuitTaskSourceInputV1,
}

impl ProviderAdmission {
    pub(super) async fn new() -> anyhow::Result<Self> {
        let a = support::admission("resident-provider-original-A").await?;
        let preview = support::source(&a, [Q, Q / 4])?;
        let c = support::admission("resident-provider-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        anyhow::ensure!(source_c.scope.run_id != preview.scope.run_id,
                        "A and the pre-held future C are different original runs");
        anyhow::ensure!(source_c.observation != preview.observation,
                        "C has its own original input");
        anyhow::ensure!(source_c.objective_digest == preview.objective_digest,
                        "same external objective across the two original admissions");
        Ok(Self {
            a, c, objective: preview.objective_digest, trust_time: now()?, source_c,
        })
    }
}

/// Own every original internal Material server. Partial construction and Drop
/// reap all these threads; neither path silently detaches a JoinHandle.
struct MaterialPeers {
    threads: Vec<material_ports::Peer>,
}

impl MaterialPeers {
    fn new() -> Self {
        Self { threads: Vec::new() }
    }

    fn push(&mut self, peer: material_ports::Peer) {
        self.threads.push(peer);
    }

    fn finish(mut self) -> anyhow::Result<Vec<u64>> {
        let mut counts = Vec::new();
        let mut errors = Vec::new();
        for peer in self.threads.drain(..) {
            match material_ports::finish(peer) {
                Ok(count) => counts.push(count),
                Err(error) => errors.push(format!("{error:#}")),
            }
        }
        anyhow::ensure!(errors.is_empty(), "original Material peer cleanup: {errors:?}");
        Ok(counts)
    }
}

impl Drop for MaterialPeers {
    fn drop(&mut self) {
        for peer in self.threads.drain(..) {
            if let Err(error) = material_ports::finish(peer) {
                // Drop cannot return a result. Explicit finish is the tested
                // success path; this error is not converted into success.
                eprintln!("original Material peer cleanup during Drop: {error:#}");
            }
        }
    }
}

/// All files, owners and previews refer to the same actually completed A.
/// Declaration order closes the owned Trainer before its internal peers.
/// External service clones must be stopped and dropped before finish.
pub(super) struct UnstartedProvider {
    pub(super) trainer: Arc<Trainer>,
    pub(super) material_owner: Arc<MaterialOwner>,
    pub(super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) baseline: Arc<LoadedCellQ24ModelV1>,
    pub(super) bundle: CellCompatibilityBundleV1,
    pub(super) definition: CellDefinitionV1,
    pub(super) ledger: Arc<Mutex<LedgerWriter>>,
    pub(super) credentials: material::Credentials,
    pub(super) previous: CircuitTaskSourcePublicationV1,
    pub(super) source_a: crate::CircuitTaskSourceInputV1,
    pub(super) config_a: codex_hepta_neuron::CellGenerationConfigV2,
    pub(super) a: Option<support::Session>,
    pub(super) c: Option<support::Admission>,
    pub(super) source_c: crate::CircuitTaskSourceInputV1,
    pub(super) version: VersionFixture,
    pub(super) root: PathBuf,
    material_peers: MaterialPeers,
    source_paths: [PathBuf; 2],
    // Retain actual files until original Trainer clients and peers are closed.
    _directory: tempfile::TempDir,
}

impl UnstartedProvider {
    pub(super) async fn new(
        admission: ProviderAdmission,
        evaluation_profile: Digest32,
    ) -> anyhow::Result<Self> {
        let ProviderAdmission {
            mut a, c, objective, trust_time, source_c,
        } = admission;
        anyhow::ensure!(!evaluation_profile.is_zero(), "pre-registered B evaluation profile");
        anyhow::ensure!(now()? >= trust_time, "original fixture clock did not regress");
        let preview = support::source(&a, [Q, Q / 4])?;
        anyhow::ensure!(preview.objective_digest == objective, "same original A objective");
        anyhow::ensure!(support::source(&c, [Q / 4, Q])? == source_c,
                        "the pre-held C request has not been replaced");
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let (baseline, bundle, definition) = support::model(&root)?;
        let (mut ledger, credentials) = material::ledger_at(
            &root, objective, trust_time, d("resident-provider-original-ledger"),
        )?;
        let run = crate::circuit_credit::circuit_learning_run_id_v1(
            &ledger, &a.runtime.identity.agent_id, &id("positive-original-episode"),
        )?;
        // Bind the actual run before the existing fixture issuer signs the
        // complete body; no completed input or frozen receipt is rewritten.
        a.request.body.run_id = run.to_string();
        let source_a = support::source(&a, [Q, Q / 4])?;
        anyhow::ensure!(source_a.objective_digest == objective);
        anyhow::ensure!(source_a.scope.run_id == run);
        anyhow::ensure!(source_a.scope.run_id != source_c.scope.run_id);
        let config_a = support::configuration(
            &baseline, &bundle, &definition, &source_a, 1,
        )?;
        let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
        let published = support::publish_initial(&version, definition.clone(), source_a.clone())?;
        let mut a = support::start(a, published, Arc::clone(&baseline), bundle.clone()).await?;
        let mut peers = MaterialPeers::new();

        // On any Result error, the block drops its partially built clients
        // before the outer cleanup stops A and joins all already started peers.
        let built = async {
            let previous = execute(&a, 1).await?;
            anyhow::ensure!(previous.input() == &source_a, "actual A uses this original input");
            anyhow::ensure!(previous.original_record().snapshot.run_id == run);
            let before_training = read_receipt(&a, &definition, &previous)?;
            anyhow::ensure!(before_training.representation.prediction_q24[0] == Q,
                            "the actual baseline's original A prediction");
            material::decision(&mut ledger, &credentials, &previous)?;
            // The existing fixture fixes 2Q independently of all future model
            // outputs. It is the positive Candidate input, not an inferred label.
            material::terminal_outcome(&mut ledger, &credentials, &previous)?;
            // Fix the already enrolled Observer now. The future actual C owner
            // must use this same signer/key (the original fixture seed is 43).
            // SourceInput has no independent observer-identity getter.
            let next_use_observer = credentials.observer.principal.principal_id.clone();
            let (material, optimizer) = material::unstarted_material_with_profile(
                &root, &mut ledger, &credentials, a.source.as_ref(), &a.runtime.identity,
                &baseline, &bundle, &previous, evaluation_profile,
                next_use_observer.clone(),
            )?;
            anyhow::ensure!(material.initial.receipts.is_empty(),
                            "no Material/Training/Evaluation/Model receipt prefilled");
            anyhow::ensure!(material.initial.request.evaluation_profile == evaluation_profile);
            anyhow::ensure!(material.initial.owners.next_use_observer == next_use_observer);
            anyhow::ensure!(material.initial.request.source_run_id == source_a.scope.run_id);
            anyhow::ensure!(material.initial.request.envelope.objective_digest == objective);
            let ledger = Arc::new(Mutex::new(ledger));
            let pair = OriginalCellQ24MaterialReceiptOwnersV1::create(
                OriginalCellQ24MaterialReceiptFilesV1 {
                    experience: opened(&root, "positive-experience", true)?,
                    experience_witness: original_witness(
                        &root, "positive-experience-witness", &material.scope, objective, true,
                    )?,
                    dataset: opened(&root, "positive-dataset", true)?,
                    dataset_witness: original_witness(
                        &root, "positive-dataset-witness", &material.scope, objective, true,
                    )?,
                },
                material.clone(),
                SigningKey::from_bytes(&[44; 32]),
                SigningKey::from_bytes(&[45; 32]),
            )?;
            let material_owner = Arc::new(pair.into_command_owner(
                a.source.as_ref().clone(), a.runtime.identity.clone(),
                Arc::clone(&ledger), Arc::clone(&baseline),
            )?);

            // Open the real custody files before starting the original
            // 500-ms evidence transports; no deadline is changed or renewed.
            let native_file = opened(&root, "positive-native-training", true)?;
            let native_witness = original_witness(
                &root, "positive-native-witness", &material.scope, objective, true,
            )?;
            let receipt_file = opened(&root, "positive-training-receipt", true)?;
            let receipt_witness = original_witness(
                &root, "positive-training-receipt-witness", &material.scope,
                objective, true,
            )?;
            // All four internal connections precede Material completion and
            // use the actual original handlers. Public peer admission is a
            // separate mechanism; these are the existing same-UID test ports.
            let (dataset, peer) = material_ports::commands_for_original(
                Arc::clone(&material_owner), material.clone(), Role::Dataset,
            )?;
            peers.push(peer);
            let dataset = dataset.into_original_dataset_readback(&material)?;
            let (source, peer) = material_ports::source_for_original(
                Arc::clone(&material_owner), &material, Arc::clone(&baseline),
                Duration::from_secs(300),
            )?;
            peers.push(peer);
            let (experience, peer) = material_ports::evidence_for_original(
                Arc::clone(&material_owner), &material, Role::Experience,
            )?;
            peers.push(peer);
            let (dataset_evidence, peer) = material_ports::evidence_for_original(
                Arc::clone(&material_owner), &material, Role::Dataset,
            )?;
            peers.push(peer);
            let trainer = Arc::new(Trainer::from_original_custody(
                OriginalCellQ24TrainingBootstrapCustodyV1 {
                    native_file,
                    native_witness,
                    receipt_file,
                    receipt_witness,
                    generator_key: SigningKey::from_bytes(&[41; 32]),
                    baseline: Arc::clone(&baseline),
                    material_source: source,
                    experience,
                    dataset: dataset_evidence,
                },
                OriginalCellQ24TrainingBootstrapConfigV1 {
                    material: material.clone(), optimizer,
                    generator: credentials.generator.clone(),
                    maximum_signature_lifetime_seconds: 300,
                },
                dataset,
                Arc::new(AtomicBool::new(false)),
            )?);
            anyhow::ensure!(peers.threads.len() == 4,
                            "all four original internal Material peers retained");
            Ok::<_, anyhow::Error>((material, material_owner, trainer, ledger, previous))
        }.await;

        let (material, material_owner, trainer, ledger, previous) = match built {
            Ok(original) => original,
            Err(error) => {
                let a_cleanup = a.stop().await;
                let peer_cleanup = peers.finish();
                return Err(error.context(format!(
                    "same-A setup cleanup: A={a_cleanup:?}, original Material peers={peer_cleanup:?}",
                )));
            }
        };
        let source_paths = [
            a.runtime.identity.home_root.join("q24-source.journal"),
            a.runtime.identity.home_root.join("q24-source.witness"),
        ];
        Ok(Self {
            trainer, material_owner, material, baseline, bundle, definition, ledger,
            credentials, previous, source_a, config_a, a: Some(a), c: Some(c),
            source_c, version, root, material_peers: peers, source_paths,
            _directory: directory,
        })
    }

    pub(super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = [
            "positive-ledger", "positive-ledger-witness",
            "positive-experience", "positive-experience-witness",
            "positive-dataset", "positive-dataset-witness",
            "positive-native-training", "positive-native-witness",
            "positive-training-receipt", "positive-training-receipt-witness",
            "base", "encoder", "heads",
        ].into_iter().map(|name| fs::read(self.root.join(name)).map_err(anyhow::Error::from))
            .collect::<anyhow::Result<Vec<_>>>()?;
        // Taking A for publication must not silently remove Source files from
        // later conservation checks. Missing original files remain an error.
        for path in &self.source_paths {
            bytes.push(fs::read(path)?);
        }
        Ok(bytes)
    }

    /// All external service clones must be closed first. If the orchestrator
    /// took A, it also owns A.stop/join and must retain A's original home until
    /// all dependent owners close; this fixture does not claim that work for it.
    pub(super) async fn finish(mut self) -> anyhow::Result<[u64; 4]> {
        let a_cleanup = match self.a.as_mut() {
            Some(a) => a.stop().await,
            None => Ok(()),
        };
        let trainer_clones = Arc::strong_count(&self.trainer);
        let Self {
            trainer, material_owner, material_peers, a, c, version, _directory, ..
        } = self;
        drop(trainer);
        // Reap every internal peer even if a different original peer failed.
        let peer_cleanup = material_peers.finish();
        let material_clones = Arc::strong_count(&material_owner);
        drop(material_owner);
        drop(a);
        drop(c);
        drop(version);
        drop(_directory);
        a_cleanup.context("same original A stop/join")?;
        anyhow::ensure!(trainer_clones == 1, "external original Trainer services still held");
        anyhow::ensure!(material_clones == 1, "external original Material services still held");
        let counts = peer_cleanup?;
        counts.try_into().map_err(|counts: Vec<u64>| anyhow::anyhow!(
            "expected four original Material peer terminals, got {}", counts.len(),
        ))
    }
}
