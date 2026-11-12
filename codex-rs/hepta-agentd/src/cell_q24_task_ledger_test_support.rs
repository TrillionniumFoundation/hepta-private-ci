//! Actual native task/source/Cell with explicit test trust and role custody.
//! Labels below are supplied by this fixture's independent Observer.

use std::fs::File;
use std::path::Path;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use super::*;

pub(super) struct Fixture {
    pub(super) session: support::Session,
    pub(super) root: tempfile::TempDir,
    pub(super) ledger: Arc<Mutex<LedgerWriter>>,
    pub(super) producer: Arc<crate::OriginalCellQ24TaskLedgerProducerV1>,
    pub(super) config: crate::OriginalCellQ24TaskLedgerConfigV1,
    pub(super) signers: [TrustedLearningSignerV1; 3],
    pub(super) publication: CircuitTaskSourcePublicationV1,
    pub(super) baseline: Arc<crate::LoadedCellQ24ModelV1>,
    pub(super) bundle: codex_hepta_learning_artifacts::CellCompatibilityBundleV1,
    pub(super) _version: VersionFixture,
    pub(super) trust: ActivatedLearningTrustV1,
}

pub(super) fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

pub(super) fn file(root: &Path, name: &str) -> anyhow::Result<File> {
    let mut options: std::fs::OpenOptions = OpenOptions::new();
    options.read(true);
    options.write(true);
    options.create(true);
    options.truncate(false);
    Ok(options.open(root.join(name))?)
}

pub(super) fn witness(
    root: &Path,
    name: &str,
    objective: Digest32,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(root, name)?,
        JournalScope {
            scope_digest: cell::d("original-task-ledger-fixture-witness"),
            objective_digest: objective,
        },
        Generation::new(/*value*/ 1)?,
        /*max_records*/ 64,
    )?)
}

#[derive(Clone, Copy)]
pub(super) enum TaskProfile {
    NonLearning,
    Original,
    SuccessorFeedback,
    SuccessorRefusedGenerator,
}

#[cfg(test)]
impl Fixture {
    pub(super) async fn new(run: &str, lifetime: u64, automatic: bool) -> anyhow::Result<Self> {
        let profile = if automatic {
            TaskProfile::Original
        } else {
            TaskProfile::NonLearning
        };
        Self::new_profile(run, lifetime, profile).await
    }

    pub(super) async fn new_profile(
        run: &str,
        lifetime: u64,
        profile: TaskProfile,
    ) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let (baseline, bundle, definition) = support::model(root.path())?;
        let admission = support::admission(run).await?;
        let source = support::source(&admission, [Q, Q / 4])?;
        let generation = support::configuration(
            &baseline,
            &bundle,
            &definition,
            &source,
            /*generation*/ 1,
        )?;
        let version = VersionFixture::new_initial(generation, "ordinary-q24-initial")?;
        let published = support::publish_initial(&version, definition, source.clone())?;
        let signers = [
            ("task-generator", 1, LearningEvidenceRoleV1::Generator),
            ("task-observer", 2, LearningEvidenceRoleV1::Observer),
            ("task-evaluator", 3, LearningEvidenceRoleV1::Evaluator),
        ]
        .map(|(name, seed, role)| {
            let key = SigningKey::from_bytes(&[seed; 32]);
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: cell::id(name),
                    credential_chain_digest: cell::d(&format!("{name}-credential")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: cell::d("original-task-ledger-fixture-scope"),
                    authority_epoch: 1,
                    authenticated_at: now() - 10,
                    expires_at: now() + 7_200,
                },
                controller_id: cell::id(&format!("{name}-controller")),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            }
        });
        let key = SigningKey::from_bytes(&[99; 32]);
        let trust_root = LearningTrustRootV1 {
            root_id: cell::id("original-task-ledger-fixture-root"),
            scope_digest: signers[0].principal.scope_digest,
            verifying_key: key.verifying_key().to_bytes(),
            valid_from: now() - 10,
            expires_at: now() + 7_200,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: cell::id("original-task-ledger-fixture-distribution"),
                generation: 1,
                effective_at: now() - 1,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: trust_root.scope_digest,
                    objective_digest: source.objective_digest,
                    authority_epoch: 1,
                    signers: signers.to_vec(),
                },
            },
            root_id: trust_root.root_id.clone(),
            issued_at: now() - 1,
            expires_at: now() + 3_600,
            signature: [0; 64],
        };
        distribution.signature = key.sign(&distribution.signing_bytes()?).to_bytes();
        let trust =
            activate_learning_trust(&trust_root, distribution, /*previous*/ None, now())?;
        let directory = File::open(root.path())?;
        let binding = cell::d("original-task-ledger-fixture");
        let ledger = Arc::new(Mutex::new(LedgerWriter::from_durable(
            DurableLedger::create(
                file(root.path(), "ledger")?,
                binding,
                /*max_records*/ 64,
            )?,
            LedgerWitnessStore::create(file(root.path(), "ledger.witness")?, binding)?,
            trust.clone(),
            &directory,
            &directory,
        )?));
        let config = crate::OriginalCellQ24TaskLedgerConfigV1 {
            episode_id: cell::id("original-task-episode"),
            candidate_set_id: cell::id("original-task-candidates"),
            generator_code_digest: cell::d("fixture-native-generator"),
            grammar_digest: cell::d("fixture-finite-grammar"),
            hard_filter_digest: cell::d("fixture-filter"),
            truncation_digest: cell::d("fixture-no-truncation"),
            generator: signers[0].clone(),
            observer: signers[1].clone(),
            outcome_record_id: cell::id("original-business-outcome-record"),
            outcome_id: cell::id("original-business-outcome"),
            unit_profile_digest: cell::d("fixture-target-unit"),
            expected_delay_profile_digest: cell::d("fixture-business-delay"),
            claim_deadline_unix_seconds: now() + 3_600,
            maximum_signature_lifetime_seconds: lifetime,
        };
        let inputs = crate::OriginalCellQ24TaskLedgerInputsV1 {
            ledger: Arc::clone(&ledger),
            signature_journal: file(root.path(), "signatures")?,
            signature_witness: witness(root.path(), "signatures.witness", source.objective_digest)?,
            open_mode: crate::CircuitQ24TaskOpenModeV1::Create,
            config: config.clone(),
            generator_key: SigningKey::from_bytes(&[match profile {
                TaskProfile::SuccessorRefusedGenerator => 4,
                TaskProfile::NonLearning | TaskProfile::Original | TaskProfile::SuccessorFeedback => 1,
            }; 32]),
        };
        let session = match profile {
            TaskProfile::Original => {
                support::start_learning(
                    admission,
                    published,
                    Arc::clone(&baseline),
                    bundle.clone(),
                    inputs,
                )
                .await?
            }
            TaskProfile::NonLearning => {
                drop(inputs);
                support::start(admission, published, Arc::clone(&baseline), bundle.clone()).await?
            }
            TaskProfile::SuccessorFeedback | TaskProfile::SuccessorRefusedGenerator => {
                support::start_successor_learning(
                    admission,
                    published,
                    Arc::clone(&baseline),
                    bundle.clone(),
                    inputs,
                )
                .await?
            }
        };
        // This is the only task dispatch performed by this fixture.
        let publication = execute(&session, /*request_id*/ 1).await?;
        let producer = match &session.ledger {
            Some(producer) => Arc::clone(producer),
            None => Arc::new(crate::OriginalCellQ24TaskLedgerProducerV1::open_original(
                crate::OriginalCellQ24TaskLedgerInputsV1 {
                    ledger: Arc::clone(&ledger),
                    signature_journal: file(root.path(), "signatures")?,
                    signature_witness: witness(
                        root.path(),
                        "signatures.witness",
                        source.objective_digest,
                    )?,
                    open_mode: crate::CircuitQ24TaskOpenModeV1::Create,
                    config: config.clone(),
                    generator_key: SigningKey::from_bytes(&[1; 32]),
                },
                Arc::clone(&session.source),
                session.cell.clone(),
                session.retirement.clone(),
                session.runtime.identity.clone(),
            )?),
        };
        Ok(Self {
            session,
            root,
            ledger,
            producer,
            config,
            signers,
            publication,
            baseline,
            bundle,
            _version: version,
            trust,
        })
    }

    pub(super) fn outcome(&self) -> AuthenticatedOutcomeV1 {
        AuthenticatedOutcomeV1 {
            record_id: self.config.outcome_record_id.clone(),
            outcome_id: self.config.outcome_id.clone(),
            episode_id: self.config.episode_id.clone(),
            observer: self.signers[1].principal.clone(),
            observed_at: Some(now()),
            value: Some(FixedQ32::from_raw(2_i64 << 32)),
            unit_profile_digest: self.config.unit_profile_digest,
            support_digest: self.publication.publication_digest(),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: now(),
                expected_delay_profile_digest: self.config.expected_delay_profile_digest,
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(now()),
            },
        }
    }

    pub(super) fn sign_outcome(
        &self,
        outcome: &AuthenticatedOutcomeV1,
        lifetime: u64,
    ) -> SignedLearningEvidenceV1 {
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: cell::id("original-observer-evidence"),
            principal_id: self.signers[1].principal.principal_id.clone(),
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: self.ledger.lock().unwrap().verifier().trust_digest(),
            scope_digest: self.signers[1].principal.scope_digest,
            objective_digest: self.publication.input().objective_digest,
            authority_epoch: self.signers[1].principal.authority_epoch,
            issued_at: now(),
            expires_at: now() + lifetime,
            payload_digest: Digest32::of_bytes(&outcome_signing_payload_v2(outcome)),
            signature: [0; 64],
        };
        signed.signature = SigningKey::from_bytes(&[2; 32])
            .sign(&signed.signing_bytes())
            .to_bytes();
        signed
    }

    pub(super) fn task_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "q24-source.journal",
            "q24-source.witness",
            "q24-cell.journal",
            "q24-cell.witness",
            "q24-control.journal",
        ]
        .map(|name| fs::read(self.session.runtime.identity.home_root.join(name)))
        .into_iter()
        .collect::<Result<Vec<_>, _>>()
        .map_err(Into::into)
    }

    pub(super) fn learning_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "ledger",
            "ledger.witness",
            "signatures",
            "signatures.witness",
        ]
        .map(|name| fs::read(self.root.path().join(name)))
        .into_iter()
        .collect::<Result<Vec<_>, _>>()
        .map_err(Into::into)
    }

    pub(super) fn preparation(&self) -> anyhow::Result<crate::CellQ24LearningPreparationConfigV1> {
        // These are explicit stage-profile fixtures only. Its synthetic E/D
        // receipts are discarded; this API receives an empty original request.
        let (prefix, _) = trained::training_cut(&self.publication, self.bundle.clone())?;
        Ok(crate::CellQ24LearningPreparationConfigV1 {
            request: prefix.request,
            owners: prefix.owners,
            baseline: Arc::clone(&self.baseline),
            head: crate::CellQ24PrivateHeadV1::Drive { index: 0 },
            rule: crate::CellQ24SgdRuleV1 {
                epochs: 2,
                learning_rate_q24: Q / 2,
            },
            projection: crate::CellQ24DatasetProjectionV1 {
                inherited_inclusion_policy: cell::d("fixture-task-inclusion"),
                unit_profile_digest: self.config.unit_profile_digest,
                baseline_bundle: self.bundle.digest()?,
                input_width: 2,
            },
            snapshot_id: cell::id("original-task-dataset"),
        })
    }

    pub(super) fn freeze_inputs(
        &self,
    ) -> anyhow::Result<crate::OriginalCellQ24TaskDatasetFreezeInputsV1> {
        let verifier = self.ledger.lock().unwrap().verifier().clone();
        Ok(crate::OriginalCellQ24TaskDatasetFreezeInputsV1 {
            journal: file(self.root.path(), "freeze")?,
            witness: witness(
                self.root.path(),
                "freeze.witness",
                self.publication.input().objective_digest,
            )?,
            open_mode: crate::CircuitQ24TaskOpenModeV1::Create,
            signing: crate::OriginalCellQ24DatasetFreezeSigningConfigV1 {
                signer: self.signers[2].clone(),
                verifier,
                maximum_signature_lifetime_seconds: 300,
            },
            evaluator_key: SigningKey::from_bytes(&[3; 32]),
        })
    }

    pub(super) async fn reconcile(&self) -> anyhow::Result<()> {
        let state = &self.session.runtime.state;
        let store = state.circuit_task_store()?;
        state
            .objective_runtime
            .get()
            .expect("original Objective owner")
            .reconcile_learning_outbox(
                &store,
                Some(&self.publication.original_record().snapshot.run_id),
                state,
            )
            .await?;
        Ok(())
    }

    pub(super) async fn no_outbox(&self) -> anyhow::Result<()> {
        assert!(
            self.session
                .runtime
                .state
                .circuit_task_store()?
                .circuit_learning_delivery(&self.session.request.body.run_id)
                .await
                .unwrap()
                .is_none()
        );
        Ok(())
    }

    pub(super) fn require_task_unchanged(&self, original: &[Vec<u8>]) -> anyhow::Result<()> {
        assert_eq!(self.task_bytes()?, original);
        assert_eq!(
            self.session.source.read_run_publication(
                &self.session.runtime.identity,
                &self.publication.original_record().snapshot.run_id,
            )?,
            self.publication
        );
        Ok(())
    }
}

pub(super) async fn after_expiry(expires_at: u64) {
    while now() <= expires_at {
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}
