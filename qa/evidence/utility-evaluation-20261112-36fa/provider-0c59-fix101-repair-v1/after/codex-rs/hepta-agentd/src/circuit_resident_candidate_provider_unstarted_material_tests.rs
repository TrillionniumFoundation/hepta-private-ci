//! Material-only mechanism fixture for a later public cross-UID Trainer.
//! This returns after the same real A/Decision/Outcome/Material construction,
//! before any Trainer custody or cfg(test) Material transport is created.
//! Its VersionFixture still uses the original test Current store: this is not
//! a replacement for production RootAuthorityDirectory or Root authorization.

use super::*;

/// Own the still-live original A, its one ledger writer and actual Material
/// owner without also constructing a Trainer in this process. Only the caller
/// can start original public transports whose actual connected streams are
/// bound by another process; no endpoint or authority is fabricated here.
pub(in super::super) struct UnstartedMaterialProvider {
    pub(in super::super) material_owner: Arc<MaterialOwner>,
    pub(in super::super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(in super::super) original_trust: codex_hepta_learning_ledger::LearningEvidenceTrustV1,
    pub(in super::super) original_material_inputs: material::OriginalMaterialConstructorInputs,
    pub(in super::super) original_decision: material::OriginalDecisionEvidence,
    pub(in super::super) original_outcome: material::OriginalOutcomeEvidence,
    pub(in super::super) baseline: Arc<LoadedCellQ24ModelV1>,
    pub(in super::super) bundle: CellCompatibilityBundleV1,
    pub(in super::super) definition: CellDefinitionV1,
    pub(in super::super) ledger: Arc<Mutex<LedgerWriter>>,
    pub(in super::super) credentials: material::Credentials,
    pub(in super::super) previous: CircuitTaskSourcePublicationV1,
    pub(in super::super) source_a: crate::CircuitTaskSourceInputV1,
    pub(in super::super) config_a: codex_hepta_neuron::CellGenerationConfigV2,
    pub(in super::super) a: Option<support::Session>,
    pub(in super::super) c: Option<support::Admission>,
    pub(in super::super) source_c: crate::CircuitTaskSourceInputV1,
    pub(in super::super) version: VersionFixture,
    pub(in super::super) root: PathBuf,
    pub(super) source_paths: [PathBuf; 2],
    pub(super) optimizer: crate::CellQ24SgdRuleV1,
    // This owner has no Trainer or transport. Retain its actual A and ledger
    // files until all consumers of the original Material owner have closed.
    pub(super) _directory: tempfile::TempDir,
}

impl UnstartedMaterialProvider {
    pub(in super::super) async fn new_with_original_work_deadline(
        admission: ProviderAdmission,
        evaluation_profile: Digest32,
        work_deadline: material::OriginalMaterialWorkDeadline,
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
        let (mut ledger, credentials, original_trust) = material::ledger_at_with_original_trust(
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

        // Result errors explicitly stop and join the same A. This entry
        // creates no Trainer, internal Material peer, or duplicate writer.
        let built = async {
            let previous = execute(&a, 1).await?;
            // Match the original Source input projection, retaining the operation
            // identity already authenticated by the opaque publication.
            let expected_input = codex_hepta_neuron::CellStepInputV1 {
                operation_id: previous.input().operation_id.clone(),
                scope: source_a.scope.clone(),
                source_frontier: source_a.source_frontier,
                objective_digest: source_a.objective_digest,
                ndu_snapshot_digest: source_a.ndu_snapshot_digest,
                monotonic_micros: source_a.monotonic_micros,
                deadline_micros: source_a.deadline_micros,
                observation: source_a.observation.clone(),
                candidates: source_a.candidates.clone(),
            };
            anyhow::ensure!(previous.input() == &expected_input, "actual A uses this original input");
            anyhow::ensure!(previous.original_record().snapshot.run_id == run);
            let before_training = read_receipt(&a, &definition, &previous)?;
            anyhow::ensure!(before_training.representation.prediction_q24[0] == Q,
                            "the actual baseline's original A prediction");
            let original_decision = material::decision_with_original_evidence(
                &mut ledger, &credentials, &previous,
            )?;
            // The existing fixture fixes 2Q independently of all future model
            // outputs. It is the positive Candidate input, not an inferred label.
            let original_outcome = material::terminal_outcome_with_original_evidence(
                &mut ledger, &credentials, &previous,
            )?;
            // Fix the already enrolled Observer now. The future actual C owner
            // must use this same signer/key (the original fixture seed is 43).
            // SourceInput has no independent observer-identity getter.
            let next_use_observer = credentials.observer.principal.principal_id.clone();
            let (material, optimizer, original_material_inputs) = material::unstarted_material_with_original_work_deadline(
                &root, &mut ledger, &credentials, a.source.as_ref(), &a.runtime.identity,
                &baseline, &bundle, &previous, evaluation_profile,
                next_use_observer.clone(), work_deadline,
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

            Ok::<_, anyhow::Error>((material, material_owner, optimizer, ledger, previous,
                original_material_inputs, original_decision, original_outcome))
        }.await;

        let (material, material_owner, optimizer, ledger, previous, original_material_inputs,
            original_decision, original_outcome) = match built {
            Ok(original) => original,
            Err(error) => {
                let a_cleanup = a.stop().await;
                return Err(error.context(format!(
                    "same-A Material-only setup cleanup: A={a_cleanup:?}",
                )));
            }
        };
        let source_paths = [
            a.runtime.identity.home_root.join("q24-source.journal"),
            a.runtime.identity.home_root.join("q24-source.witness"),
        ];
        Ok(Self {
            material_owner, material, original_trust, original_material_inputs,
            original_decision, original_outcome,
            baseline, bundle, definition, ledger,
            credentials, previous, source_a, config_a, a: Some(a), c: Some(c),
            source_c, version, root, source_paths, optimizer,
            _directory: directory,
        })
    }

    pub(in super::super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = [
            "positive-ledger", "positive-ledger-witness",
            "positive-experience", "positive-experience-witness",
            "positive-dataset", "positive-dataset-witness",
            "base", "encoder", "heads",
        ].into_iter().map(|name| fs::read(self.root.join(name)).map_err(anyhow::Error::from))
            .collect::<anyhow::Result<Vec<_>>>()?;
        for path in &self.source_paths {
            bytes.push(fs::read(path)?);
        }
        Ok(bytes)
    }

    /// Public service tasks must be stopped and joined by the caller before
    /// this owner is released. This method joins the original A task; it does
    /// not claim to have joined a future caller's transport or Trainer task.
    pub(in super::super) async fn finish(mut self) -> anyhow::Result<()> {
        let a_cleanup = match self.a.as_mut() {
            Some(a) => a.stop().await,
            None => Ok(()),
        };
        let material_clones = Arc::strong_count(&self.material_owner);
        let Self { material_owner, a, c, version, _directory, .. } = self;
        drop(material_owner);
        drop(a);
        drop(c);
        drop(version);
        drop(_directory);
        a_cleanup.context("same original A stop/join")?;
        anyhow::ensure!(material_clones == 1, "external original Material services still held");
        Ok(())
    }
}
