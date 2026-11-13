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
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

#[path = "circuit_resident_candidate_provider_unstarted_material_tests.rs"]
mod unstarted_material;
pub(super) use unstarted_material::UnstartedMaterialProvider;

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
        anyhow::ensure!(
            source_c.scope.run_id != preview.scope.run_id,
            "A and the pre-held future C are different original runs"
        );
        anyhow::ensure!(
            source_c.observation != preview.observation,
            "C has its own original input"
        );
        anyhow::ensure!(
            source_c.objective_digest == preview.objective_digest,
            "same external objective across the two original admissions"
        );
        Ok(Self {
            a,
            c,
            objective: preview.objective_digest,
            trust_time: now()?,
            source_c,
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
        Self {
            threads: Vec::new(),
        }
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
        anyhow::ensure!(
            errors.is_empty(),
            "original Material peer cleanup: {errors:?}"
        );
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
    pub(super) original_trust: codex_hepta_learning_ledger::LearningEvidenceTrustV1,
    pub(super) original_material_inputs: material::OriginalMaterialConstructorInputs,
    pub(super) original_decision: material::OriginalDecisionEvidence,
    pub(super) original_outcome: material::OriginalOutcomeEvidence,
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
        Self::new_with_original_work_deadline(
            admission,
            evaluation_profile,
            material::OriginalMaterialWorkDeadline::AtOriginalFreeze,
        )
        .await
    }

    pub(super) async fn new_with_original_work_deadline(
        admission: ProviderAdmission,
        evaluation_profile: Digest32,
        work_deadline: material::OriginalMaterialWorkDeadline,
    ) -> anyhow::Result<Self> {
        let mut original = UnstartedMaterialProvider::new_with_original_work_deadline(
            admission,
            evaluation_profile,
            work_deadline,
        )
        .await?;
        let mut peers = MaterialPeers::new();
        let built = (|| -> anyhow::Result<Arc<Trainer>> {
            let root = &original.root;
            let baseline = &original.baseline;
            let material = &original.material;
            let material_owner = &original.material_owner;
            let credentials = &original.credentials;
            let objective = original.material.initial.request.envelope.objective_digest;
            let optimizer = original.optimizer;
            // Open the real custody files before starting the original
            // 500-ms evidence transports; no deadline is changed or renewed.
            let native_file = opened(root, "positive-native-training", true)?;
            let native_witness = original_witness(
                root,
                "positive-native-witness",
                &material.scope,
                objective,
                true,
            )?;
            let receipt_file = opened(root, "positive-training-receipt", true)?;
            let receipt_witness = original_witness(
                root,
                "positive-training-receipt-witness",
                &material.scope,
                objective,
                true,
            )?;
            // All four internal connections precede Material completion and
            // use the actual original handlers. Public peer admission is a
            // separate mechanism; these are the existing same-UID test ports.
            let (dataset, peer) = material_ports::commands_for_original(
                Arc::clone(material_owner),
                (*material).clone(),
                Role::Dataset,
            )?;
            peers.push(peer);
            let dataset = dataset.into_original_dataset_readback(material)?;
            let (source, peer) = material_ports::source_for_original(
                Arc::clone(material_owner),
                material,
                Arc::clone(baseline),
                Duration::from_secs(300),
            )?;
            peers.push(peer);
            let (experience, peer) = material_ports::evidence_for_original(
                Arc::clone(material_owner),
                material,
                Role::Experience,
            )?;
            peers.push(peer);
            let (dataset_evidence, peer) = material_ports::evidence_for_original(
                Arc::clone(material_owner),
                material,
                Role::Dataset,
            )?;
            peers.push(peer);
            let trainer = Arc::new(Trainer::from_original_custody(
                OriginalCellQ24TrainingBootstrapCustodyV1 {
                    native_file,
                    native_witness,
                    receipt_file,
                    receipt_witness,
                    generator_key: SigningKey::from_bytes(&[41; 32]),
                    baseline: Arc::clone(baseline),
                    material_source: source,
                    experience,
                    dataset: dataset_evidence,
                },
                OriginalCellQ24TrainingBootstrapConfigV1 {
                    material: (*material).clone(),
                    optimizer,
                    generator: credentials.generator.clone(),
                    maximum_signature_lifetime_seconds: 300,
                },
                dataset,
                Arc::new(AtomicBool::new(false)),
            )?);
            anyhow::ensure!(
                peers.threads.len() == 4,
                "all four original internal Material peers retained"
            );
            Ok(trainer)
        })();
        let trainer = match built {
            Ok(trainer) => trainer,
            Err(error) => {
                let a_cleanup = match original.a.as_mut() {
                    Some(a) => a.stop().await,
                    None => Ok(()),
                };
                let peer_cleanup = peers.finish();
                return Err(error.context(format!(
                    "same-A setup cleanup: A={a_cleanup:?}, original Material peers={peer_cleanup:?}",
                )));
            }
        };
        let UnstartedMaterialProvider {
            material_owner,
            material,
            original_trust,
            original_material_inputs,
            original_decision,
            original_outcome,
            baseline,
            bundle,
            definition,
            ledger,
            credentials,
            previous,
            source_a,
            config_a,
            a,
            c,
            source_c,
            version,
            root,
            source_paths,
            _directory,
            optimizer: _,
        } = original;
        Ok(Self {
            trainer,
            material_owner,
            material,
            original_trust,
            original_material_inputs,
            original_decision,
            original_outcome,
            baseline,
            bundle,
            definition,
            ledger,
            credentials,
            previous,
            source_a,
            config_a,
            a,
            c,
            source_c,
            version,
            root,
            material_peers: peers,
            source_paths,
            _directory,
        })
    }

    pub(super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = [
            "positive-ledger",
            "positive-ledger-witness",
            "positive-experience",
            "positive-experience-witness",
            "positive-dataset",
            "positive-dataset-witness",
            "positive-native-training",
            "positive-native-witness",
            "positive-training-receipt",
            "positive-training-receipt-witness",
            "base",
            "encoder",
            "heads",
        ]
        .into_iter()
        .map(|name| fs::read(self.root.join(name)).map_err(anyhow::Error::from))
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
            trainer,
            material_owner,
            material_peers,
            a,
            c,
            version,
            _directory,
            ..
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
        anyhow::ensure!(
            trainer_clones == 1,
            "external original Trainer services still held"
        );
        anyhow::ensure!(
            material_clones == 1,
            "external original Material services still held"
        );
        let counts = peer_cleanup?;
        counts.try_into().map_err(|counts: Vec<u64>| {
            anyhow::anyhow!(
                "expected four original Material peer terminals, got {}",
                counts.len(),
            )
        })
    }
}
