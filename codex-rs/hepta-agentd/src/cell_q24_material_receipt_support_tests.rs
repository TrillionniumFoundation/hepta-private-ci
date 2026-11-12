//! Explicit test credentials and terminal outcomes over real Source/Ledger
//! owners. This does not provide production custody or an ordinary Root session.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;

use super::*;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::circuit_credit::circuit_learning_run_id_v1;
use crate::circuit_task::cell_q24_dataset_source_test_support as source;
use crate::circuit_task::source_test_support::identity;

pub(super) type Owners =
    OriginalCellQ24MaterialReceiptOwnersV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

pub(super) fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

pub(super) fn id(label: &str) -> StableId {
    StableId::new(label).expect("explicit fixture stable id")
}

fn signer(name: &str, role: LearningEvidenceRoleV1, seed: u8, at: u64) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: d(&format!("explicit-{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: d("explicit-material-trust"),
            authority_epoch: 1,
            authenticated_at: at - 60,
            expires_at: at + 2_400,
        },
        controller_id: id(&format!("explicit-{name}-controller")),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

pub(super) fn sign(
    verifier: &LearningEvidenceVerifierV1,
    signer: &TrustedLearningSignerV1,
    seed: u8,
    payload: &[u8],
    at: u64,
) -> SignedLearningEvidenceV1 {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "explicit-evidence:{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: signer.principal.principal_id.clone(),
        role: signer.roles[0],
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 1,
        issued_at: at - 30,
        expires_at: at + 1_800,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    signed
}

pub(super) struct Fixture {
    root: PathBuf,
    pub(super) at: u64,
    pub(super) baseline: Arc<LoadedCellQ24ModelV1>,
    pub(super) identity: AgentdIdentity,
    pub(super) source: source::Source,
    pub(super) readback: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    pub(super) writer: LedgerWriter,
    pub(super) config: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) optimizer: CellQ24SgdRuleV1,
    pub(super) generator: TrustedLearningSignerV1,
    evaluator: TrustedLearningSignerV1,
    // Drop all live original handles before removing their fixture directory.
    _directory: tempfile::TempDir,
}

#[derive(Clone, Copy)]
enum MaterialFixtureProfile {
    NoUpdate,
    CandidatePages,
}

impl Fixture {
    pub(super) async fn new(expired_work: bool) -> anyhow::Result<Self> {
        Self::with_profile(expired_work, MaterialFixtureProfile::NoUpdate,
            d("explicit-independent-evaluation-profile")).await
    }

    async fn candidate_pages() -> anyhow::Result<Self> {
        Self::candidate_pages_for_evaluation_profile(d("explicit-independent-evaluation-profile")).await
    }

    async fn candidate_pages_for_evaluation_profile(evaluation_profile: Digest32) -> anyhow::Result<Self> {
        Self::with_profile(
            /*expired_work*/ false, MaterialFixtureProfile::CandidatePages, evaluation_profile,
        ).await
    }

    async fn with_profile(
        expired_work: bool,
        profile: MaterialFixtureProfile,
        evaluation_profile: Digest32,
    ) -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let at = binding::now()?;
        let (baseline, bundle) = match profile {
            MaterialFixtureProfile::NoUpdate => source::model(&root)?,
            MaterialFixtureProfile::CandidatePages => source::candidate_page_model(&root)?,
        };
        let baseline = Arc::new(baseline);
        let generator = signer("generator", LearningEvidenceRoleV1::Generator, 1, at);
        let observer = signer("outcome-observer", LearningEvidenceRoleV1::Observer, 2, at);
        let evaluator = signer("evaluator", LearningEvidenceRoleV1::Evaluator, 3, at);
        let experience_signer = signer("experience", LearningEvidenceRoleV1::Observer, 4, at);
        let dataset_signer = signer("dataset", LearningEvidenceRoleV1::Observer, 5, at);
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("explicit-material-trust-distribution"),
                generation: 1,
                effective_at: at - 40,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: d("explicit-material-trust"),
                    objective_digest: d("objective"),
                    authority_epoch: 1,
                    signers: vec![
                        generator.clone(),
                        observer.clone(),
                        evaluator.clone(),
                        experience_signer.clone(),
                        dataset_signer.clone(),
                    ],
                },
            },
            root_id: id("explicit-material-root"),
            issued_at: at - 45,
            expires_at: at + 3_000,
            signature: [0; 64],
        };
        let root_key = SigningKey::from_bytes(&[99; 32]);
        distribution.signature = root_key.sign(&distribution.signing_bytes()?).to_bytes();
        let trust = activate_learning_trust(
            &LearningTrustRootV1 {
                root_id: distribution.root_id.clone(),
                scope_digest: d("explicit-material-trust"),
                verifying_key: root_key.verifying_key().to_bytes(),
                valid_from: at - 60,
                expires_at: at + 3_600,
                revoked_at: None,
            },
            distribution,
            None,
            at,
        )?;
        let ledger = DurableLedger::create(
            opened(&root, "ledger", true)?,
            d("original-material-ledger"),
            32,
        )?;
        let witness = LedgerWitnessStore::create(
            opened(&root, "ledger-witness", true)?,
            d("original-material-ledger"),
        )?;
        let mut directory_options = OpenOptions::new();
        directory_options.read(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            directory_options
                .write(true)
                .custom_flags(0x0200_0000 | 0x0020_0000);
        }
        let directory_handle = directory_options.open(&root)?;
        let mut writer = LedgerWriter::from_durable(
            ledger,
            witness,
            trust,
            &directory_handle,
            &directory_handle,
        )?;
        let identity = identity(&root)?;
        let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
        let candidates = vec![id("action"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: run.clone(),
            episode_id: id("episode"),
            run_snapshot_digest: d("snapshot"),
            objective_digest: d("objective"),
            policy_digest: d("policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("set"),
                state_digest: d("state"),
                generator_id: generator.principal.principal_id.clone(),
                generator_code_digest: d("code"),
                grammar_digest: d("grammar"),
                hard_filter_digest: d("filter"),
                truncation_digest: d("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: d("explicit-decision-support"),
        };
        let signed_decision = sign(
            writer.verifier(),
            &generator,
            1,
            &decision_signing_payload_v2(&decision)?,
            at,
        );
        writer.append_decision(Digest32::ZERO, decision, &signed_decision, at)?;
        // This actual run identity is chosen and its Decision committed before
        // execution. The independent terminal label below is explicit fixture data.
        let (identity, source) = source::completed(
            &root,
            &bundle,
            &run,
            &source::observation([0, crate::cell_composed_q24::codec::Q / 4]),
        )
        .await?;
        let publication = source.read_run_publication(&identity, &run)?;
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("outcome-record"),
            outcome_id: id("outcome"),
            episode_id: id("episode"),
            observer: observer.principal,
            observed_at: Some(at - 10),
            value: Some(match profile {
                MaterialFixtureProfile::NoUpdate => FixedQ32::ZERO,
                MaterialFixtureProfile::CandidatePages => FixedQ32::from_raw(2_i64 << 32),
            }),
            unit_profile_digest: d("explicit-material-unit"),
            support_digest: d("explicit-terminal-outcome-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: at - 8,
                expected_delay_profile_digest: d("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(at - 5),
            },
        };
        let signed_outcome = sign(
            writer.verifier(),
            &signer("outcome-observer", LearningEvidenceRoleV1::Observer, 2, at),
            2,
            &outcome_signing_payload_v2(&outcome),
            at,
        );
        writer.append_outcome(writer.snapshot()?.head_digest, outcome, &signed_outcome, at)?;
        let initial = initial(
            &publication,
            &bundle,
            writer.verifier().trust_digest(),
            if expired_work { at - 1 } else { at + 900 },
            match profile {
                MaterialFixtureProfile::NoUpdate => 1_024,
                MaterialFixtureProfile::CandidatePages => 4_108,
            },
            evaluation_profile,
        )?;
        let rule = CellQ24DatasetRuleV1 {
            head: CellQ24PrivateHeadV1::Prediction { index: 0 },
            unit_profile_digest: d("explicit-material-unit"),
        };
        let freeze_plan = DatasetFreezePlanV2 {
            snapshot_id: id("explicit-material-snapshot"),
            objective_digest: initial.request.envelope.objective_digest,
            inclusion_policy_digest: rule.inclusion_policy_digest(&initial)?,
        };
        let freeze_evidence = sign(
            writer.verifier(),
            &evaluator,
            3,
            &dataset_freeze_signing_payload_v2(&writer.snapshot()?, &freeze_plan)?,
            at,
        );
        let readback = source.readback();
        let mut reader = CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer);
        let material = if expired_work {
            // Test-only setup of a historical completion. Public new-work
            // methods below must still refuse this expired request.
            reader.read_current_for_original_receipt(
                &initial,
                &baseline,
                rule,
                freeze_plan.clone(),
                &freeze_evidence,
            )?
        } else {
            reader.read_current(
                &initial,
                &baseline,
                rule,
                freeze_plan.clone(),
                &freeze_evidence,
            )?
        };
        let optimizer = CellQ24SgdRuleV1 {
            epochs: 1,
            learning_rate_q24: match profile {
                MaterialFixtureProfile::NoUpdate => 1,
                MaterialFixtureProfile::CandidatePages => 1 << 20,
            },
        };
        let update_rule = crate::cell_q24_single_head_update_rule_v1(
            &bundle,
            rule.head,
            optimizer.digest(material.batch())?,
        )?;
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            LearningUpdateScopeV2::Cell,
            update_rule,
        )?;
        let config = OriginalCellQ24MaterialReceiptConfigV1 {
            initial,
            scope,
            rule,
            freeze_plan,
            freeze_evidence,
            experience_signer,
            dataset_signer,
            verifier: writer.verifier().clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        Ok(Self {
            _directory: directory,
            root,
            at,
            baseline,
            identity,
            source,
            readback,
            writer,
            config,
            optimizer,
            generator,
            evaluator,
        })
    }

    pub(super) fn sources<'a>(
        &'a mut self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> OriginalCellQ24MaterialReceiptSourcesV1<'a, FileAnchorWitnessStore> {
        OriginalCellQ24MaterialReceiptSourcesV1 {
            snapshot,
            source: &self.readback,
            identity: &self.identity,
            ledger: &mut self.writer,
            baseline: &self.baseline,
        }
    }

    pub(super) fn file(&self, name: &str, create: bool) -> anyhow::Result<File> {
        opened(&self.root, name, create)
    }

    pub(super) fn read_only_file(&self, name: &str) -> anyhow::Result<File> {
        Ok(File::open(self.root.join(name))?)
    }

    pub(super) fn witness(
        &self,
        name: &str,
        create: bool,
    ) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            self.file(name, create)?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.initial.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            64,
        )?)
    }

    fn files(
        &self,
        create: bool,
    ) -> anyhow::Result<
        OriginalCellQ24MaterialReceiptFilesV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        Ok(OriginalCellQ24MaterialReceiptFilesV1 {
            experience: self.file("experience-journal", create)?,
            experience_witness: self.witness("experience-witness", create)?,
            dataset: self.file("dataset-journal", create)?,
            dataset_witness: self.witness("dataset-witness", create)?,
        })
    }

    pub(super) fn create(&self) -> anyhow::Result<Owners> {
        Ok(Owners::create(
            self.files(true)?,
            self.config.clone(),
            SigningKey::from_bytes(&[4; 32]),
            SigningKey::from_bytes(&[5; 32]),
        )?)
    }

    pub(super) fn recover(
        &self,
        config: OriginalCellQ24MaterialReceiptConfigV1,
    ) -> anyhow::Result<Owners> {
        Ok(Owners::recover(
            self.files(false)?,
            config,
            SigningKey::from_bytes(&[4; 32]),
            SigningKey::from_bytes(&[5; 32]),
        )?)
    }

    pub(super) fn disk_bytes_after_drop(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "experience-journal",
            "experience-witness",
            "dataset-journal",
            "dataset-witness",
        ]
        .into_iter()
        .map(|name| Ok(fs::read(self.root.join(name))?))
        .collect()
    }

    pub(super) fn renewed_freeze(&self) -> SignedLearningEvidenceV1 {
        let mut renewed = self.config.freeze_evidence.clone();
        renewed.issued_at += 1;
        renewed.expires_at += 1;
        renewed.signature = SigningKey::from_bytes(&[3; 32])
            .sign(&renewed.signing_bytes())
            .to_bytes();
        renewed
    }

    pub(super) fn assert_renewed_freeze_is_valid(
        &self,
        renewed: &SignedLearningEvidenceV1,
    ) -> anyhow::Result<()> {
        self.config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            renewed,
            &dataset_freeze_signing_payload_v2(&self.writer.snapshot()?, &self.config.freeze_plan)?,
            binding::now()?,
        )?;
        assert_eq!(renewed.principal_id, self.evaluator.principal.principal_id);
        Ok(())
    }
}

fn opened(root: &std::path::Path, name: &str, create: bool) -> anyhow::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    if create {
        options.create_new(true);
    }
    Ok(options.open(root.join(name))?)
}

fn initial(
    publication: &crate::CircuitTaskSourcePublicationV1,
    bundle: &CellCompatibilityBundleV1,
    trust: Digest32,
    deadline: u64,
    maximum_artifact_bytes: u64,
    evaluation_profile: Digest32,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let input = publication.input();
    Ok(LearningIterationCoordinatorV1::new(
        LearningIterationRequestV1 {
            operation_id: id("original-material-operation"),
            principal_id: id(&input.scope.principal_digest.to_string()),
            agent_id: input.scope.agent_id.clone(),
            cell_id: input.scope.cell_id.clone(),
            source_run_id: input.scope.run_id.clone(),
            completed_task_receipt: publication.history_digest().as_str().parse()?,
            selected_artifact_digest: bundle.components.base,
            evaluation_profile,
            selected_bundle: bundle.clone(),
            envelope: IterationEnvelopeV1 {
                envelope_id: id("original-material-envelope"),
                base_commit: d("fixed-source-commit"),
                base_tree: d("fixed-source-tree"),
                objective_digest: input.objective_digest,
                grammar_digest: d("grammar"),
                maximum_files: 1,
                maximum_diff_bytes: 128,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: deadline,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 16,
                maximum_training_milliseconds: 1_000,
                maximum_artifact_bytes,
            },
        },
        LearningIterationOwnersV1 {
            evidence_trust_digest: trust,
            experience: id("experience"),
            dataset: id("dataset"),
            trainer: id("generator"),
            evaluator: id("evaluator"),
            proposal: id("proposal"),
            selector: id("selector"),
            next_use_observer: id("next-use-observer"),
        },
    )?
    .snapshot()
    .clone())
}

#[cfg(target_os = "linux")]
#[path = "cell_q24_training_source_tests.rs"]
mod training_source;

#[cfg(target_os = "linux")]
#[path = "cell_q24_material_evidence_support_tests.rs"]
mod evidence_service;
#[cfg(target_os = "linux")]
pub(crate) use evidence_service::ReadbackServiceFixture;

#[cfg(target_os = "linux")]
#[path = "cell_q24_material_command_fixture_tests.rs"]
mod command_fixture;
#[cfg(target_os = "linux")]
pub(crate) use command_fixture::MaterialCommandFixture;
#[cfg(target_os = "linux")]
pub(crate) use command_fixture::assert_dataset_pending;
#[cfg(target_os = "linux")]
pub(crate) use command_fixture::interrupt_dataset_claim;
