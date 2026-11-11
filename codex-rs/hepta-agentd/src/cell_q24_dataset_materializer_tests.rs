//! Real ordinary task inputs and original signed ledger targets. Trust issuers,
//! stage credentials and CURRENT remain explicit test fixtures; these are
//! component checks, not an ordinary full-loop or independent B acceptance.

use std::sync::Mutex;

use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24DatasetProjectionV1;
use crate::CellQ24DatasetTaskV1;
use crate::CellQ24TrainingErrorV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::cell_q24_dataset_run_snapshot_digest_v1;

struct Dataset {
    ledger: Arc<Mutex<LedgerWriter>>,
    frozen: LedgerSnapshot,
    receipt: DatasetSnapshotReceiptV3,
    evidence: SignedLearningEvidenceV1,
    projection: CellQ24DatasetProjectionV1,
    tasks: Vec<CellQ24DatasetTaskV1>,
    outcomes: Vec<AuthenticatedOutcomeV1>,
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

fn sign(
    ledger: &LedgerWriter,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let (name, seed) = match role {
        LearningEvidenceRoleV1::Generator => ("generator", 1),
        LearningEvidenceRoleV1::Observer => ("observer", 2),
        LearningEvidenceRoleV1::Evaluator => ("evaluator", 3),
        _ => panic!("test role"),
    };
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: cell::id("fixture-evidence"),
        principal_id: cell::id(name),
        role,
        trust_digest: ledger.verifier().trust_digest(),
        scope_digest: cell::d("fixture-dataset-scope"),
        objective_digest: ledger.verifier().objective_digest(),
        authority_epoch: 1,
        issued_at: now() - 1,
        expires_at: now() + 3_600,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

#[derive(Clone, Copy)]
enum CandidateMutation {
    Missing,
    MissingAbstain,
    Extra,
    Duplicate,
}

impl Dataset {
    fn new(
        root: &Path,
        sources: &[(
            &support::Session,
            &CircuitTaskSourcePublicationV1,
            Option<i64>,
        )],
        terminality: OutcomeTerminalityV1,
    ) -> anyhow::Result<Self> {
        Self::with_unit(root, sources, terminality, cell::d("fixture-target-unit"))
    }

    fn with_unit(
        root: &Path,
        sources: &[(
            &support::Session,
            &CircuitTaskSourcePublicationV1,
            Option<i64>,
        )],
        terminality: OutcomeTerminalityV1,
        outcome_unit: Digest32,
    ) -> anyhow::Result<Self> {
        Self::with_candidate_mutation(root, sources, terminality, outcome_unit, None)
    }

    fn with_candidate_mutation(
        root: &Path,
        sources: &[(
            &support::Session,
            &CircuitTaskSourcePublicationV1,
            Option<i64>,
        )],
        terminality: OutcomeTerminalityV1,
        outcome_unit: Digest32,
        mutation: Option<CandidateMutation>,
    ) -> anyhow::Result<Self> {
        let projection = CellQ24DatasetProjectionV1 {
            inherited_inclusion_policy: cell::d("fixture-inherited-inclusion"),
            unit_profile_digest: cell::d("fixture-target-unit"),
            baseline_bundle: sources[0].1.bundle_digest(),
            input_width: 2,
        };
        let signers = [
            ("generator", 1, LearningEvidenceRoleV1::Generator),
            ("observer", 2, LearningEvidenceRoleV1::Observer),
            ("evaluator", 3, LearningEvidenceRoleV1::Evaluator),
        ]
        .map(|(name, seed, role)| {
            let key = SigningKey::from_bytes(&[seed; 32]);
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: cell::id(name),
                    credential_chain_digest: cell::d(&format!("{name}-credential")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: cell::d("fixture-dataset-scope"),
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
        let observer = signers[1].principal.clone();
        let key = SigningKey::from_bytes(&[99; 32]);
        let root_trust = LearningTrustRootV1 {
            root_id: cell::id("fixture-root"),
            scope_digest: cell::d("fixture-dataset-scope"),
            verifying_key: key.verifying_key().to_bytes(),
            valid_from: now() - 10,
            expires_at: now() + 7_200,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: cell::id("fixture-distribution"),
                generation: 1,
                effective_at: now() - 1,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: root_trust.scope_digest,
                    objective_digest: sources[0].1.input().objective_digest,
                    authority_epoch: 1,
                    signers: signers.to_vec(),
                },
            },
            root_id: root_trust.root_id.clone(),
            issued_at: now() - 1,
            expires_at: now() + 3_600,
            signature: [0; 64],
        };
        distribution.signature = key.sign(&distribution.signing_bytes()?).to_bytes();
        let trust = activate_learning_trust(&root_trust, distribution, None, now())?;
        #[cfg(windows)]
        let directory = {
            use std::os::windows::fs::OpenOptionsExt;
            OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(0x0200_0000)
                .open(root)?
        };
        #[cfg(not(windows))]
        let directory = File::open(root)?;
        let binding = cell::d("fixture-original-ledger");
        let mut ledger = LedgerWriter::from_durable(
            DurableLedger::create(file(root, "dataset.ledger")?, binding, 64)?,
            LedgerWitnessStore::create(file(root, "dataset.witness")?, binding)?,
            trust,
            &directory,
            &directory,
        )?;
        let mut tasks = Vec::new();
        let mut outcomes = Vec::new();
        for (i, (session, publication, target)) in sources.iter().enumerate() {
            let receipt = session.cell.committed(publication)?;
            tasks.push(CellQ24DatasetTaskV1::capture(
                session.source.as_ref().clone(),
                &session.cell,
                session.runtime.identity.clone(),
                publication.input().scope.run_id.clone(),
            )?);
            let mut candidates: Vec<_> = receipt
                .policy
                .iter()
                .map(|entry| entry.candidate_id.clone())
                .collect();
            match mutation {
                Some(CandidateMutation::Missing) => {
                    let index = candidates
                        .iter()
                        .position(|id| {
                            id != &receipt.selected_candidate && id != &cell::id("abstain")
                        })
                        .expect("fixture has an unselected non-abstain candidate");
                    let removed = candidates.remove(index);
                    assert_ne!(removed, receipt.selected_candidate);
                    assert_ne!(removed, cell::id("abstain"));
                }
                Some(CandidateMutation::MissingAbstain) => {
                    assert_eq!(candidates.pop(), Some(cell::id("abstain")));
                }
                Some(CandidateMutation::Extra) => {
                    candidates.push(cell::id("not-an-original-candidate"))
                }
                Some(CandidateMutation::Duplicate) => candidates.push(candidates[0].clone()),
                None => {}
            }
            let decision = ProductionDecisionV2 {
                record_id: publication.input().scope.run_id.clone(),
                episode_id: cell::id(&format!("episode-{i}")),
                run_snapshot_digest: cell_q24_dataset_run_snapshot_digest_v1(publication),
                objective_digest: publication.input().objective_digest,
                policy_digest: Digest32::of_bytes(publication.output()),
                candidate_ids: candidates.clone(),
                selected_candidate_id: receipt.selected_candidate,
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompletenessReceiptV1 {
                    set_id: cell::id(&format!("set-{i}")),
                    state_digest: receipt.semantic_request_digest,
                    generator_id: cell::id("generator"),
                    generator_code_digest: cell::d("fixture-generator-code"),
                    grammar_digest: cell::d("fixture-grammar"),
                    hard_filter_digest: cell::d("fixture-filter"),
                    truncation_digest: cell::d("fixture-truncation"),
                    candidates_digest: candidate_ids_digest_v2(&candidates),
                    candidate_count: candidates.len() as u32,
                    omitted_count_bound: 0,
                    canonical_order_digest: candidate_order_digest_v2(&candidates),
                    complete_for_generator: true,
                },
                support_digest: publication.publication_digest(),
            };
            let evidence = sign(
                &ledger,
                LearningEvidenceRoleV1::Generator,
                &decision_signing_payload_v2(&decision)?,
            );
            ledger.append_decision(ledger.snapshot()?.head_digest, decision, &evidence, now())?;
            let outcome = AuthenticatedOutcomeV1 {
                record_id: cell::id(&format!("target-record-{i}")),
                outcome_id: cell::id(&format!("target-{i}")),
                episode_id: cell::id(&format!("episode-{i}")),
                observer: observer.clone(),
                observed_at: target.map(|_| now()),
                value: target.map(FixedQ32::from_raw),
                unit_profile_digest: outcome_unit,
                support_digest: publication.publication_digest(),
                watermark: OutcomeWatermarkV1 {
                    latest_observable_at: now(),
                    expected_delay_profile_digest: cell::d("fixture-delay"),
                    terminality,
                    censoring_reason: (terminality == OutcomeTerminalityV1::Censored)
                        .then(|| cell::id("unobserved")),
                    correction_predecessor: None,
                    finalized_at: (terminality != OutcomeTerminalityV1::Pending).then(now),
                },
            };
            let evidence = sign(
                &ledger,
                LearningEvidenceRoleV1::Observer,
                &outcome_signing_payload_v2(&outcome),
            );
            ledger.append_outcome(
                ledger.snapshot()?.head_digest,
                outcome.clone(),
                &evidence,
                now(),
            )?;
            outcomes.push(outcome);
        }
        let frozen = ledger.snapshot()?;
        let plan = DatasetFreezePlanV2 {
            snapshot_id: cell::id("fixture-dataset"),
            objective_digest: sources[0].1.input().objective_digest,
            inclusion_policy_digest: projection.inclusion_policy_digest()?,
        };
        let evidence = sign(
            &ledger,
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&frozen, &plan)?,
        );
        let receipt = ledger.freeze_dataset(plan, &evidence, now())?;
        Ok(Self {
            ledger: Arc::new(Mutex::new(ledger)),
            frozen,
            receipt,
            evidence,
            projection,
            tasks,
            outcomes,
        })
    }

    fn batch(&self) -> Result<CellQ24TrainingBatchV1, crate::CellQ24DatasetErrorV1> {
        CellQ24TrainingBatchV1::from_original_dataset(
            Arc::clone(&self.ledger),
            self.frozen.clone(),
            self.receipt.clone(),
            self.evidence.clone(),
            self.projection.clone(),
            self.tasks.clone(),
        )
    }

    fn refreeze(&mut self) -> anyhow::Result<()> {
        let ledger = self.ledger.lock().unwrap();
        self.frozen = ledger.snapshot()?;
        let plan = DatasetFreezePlanV2 {
            snapshot_id: self.receipt.snapshot.snapshot_id.clone(),
            objective_digest: self.receipt.snapshot.objective_digest,
            inclusion_policy_digest: self.projection.inclusion_policy_digest()?,
        };
        self.evidence = sign(
            &ledger,
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&self.frozen, &plan)?,
        );
        self.receipt = ledger.freeze_dataset(plan, &self.evidence, now())?;
        Ok(())
    }

    fn correct(&self) -> anyhow::Result<()> {
        let mut outcome = self.outcomes[0].clone();
        outcome.record_id = cell::id("corrected-record");
        outcome.outcome_id = cell::id("corrected-outcome");
        outcome.value = Some(FixedQ32::from_raw(0));
        outcome.watermark.correction_predecessor = Some(self.outcomes[0].outcome_id.clone());
        let mut ledger = self.ledger.lock().unwrap();
        let signed = sign(
            &ledger,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&outcome),
        );
        let head = ledger.snapshot()?.head_digest;
        ledger.append_outcome(head, outcome, &signed, now())?;
        Ok(())
    }
}

async fn ordinary(
    root: &Path,
    run: &str,
    source_envelope: Option<&str>,
) -> anyhow::Result<(
    support::Session,
    Arc<LoadedCellQ24ModelV1>,
    CellCompatibilityBundleV1,
    VersionFixture,
)> {
    let (baseline, bundle, definition) = support::model(root)?;
    let mut admission = support::admission(run).await?;
    if let Some(envelope) = source_envelope {
        admission.request.body.source_envelope_json = envelope.to_owned();
    }
    let source = support::source(&admission, [Q, Q / 4])?;
    let config = support::configuration(&baseline, &bundle, &definition, &source, 1)?;
    let version = VersionFixture::new_initial(config, "ordinary-q24-initial")?;
    let published = support::publish_initial(&version, definition, source)?;
    let session =
        support::start(admission, published, Arc::clone(&baseline), bundle.clone()).await?;
    Ok((session, baseline, bundle, version))
}

fn prefix(
    publication: &CircuitTaskSourcePublicationV1,
    bundle: CellCompatibilityBundleV1,
    batch: &CellQ24TrainingBatchV1,
    dataset: Digest32,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let (previous, _) = training_cut(publication, bundle)?;
    let mut c = LearningIterationCoordinatorV1::new(previous.request, previous.owners)?;
    for observation in [
        previous.receipts[0].observation.clone(),
        LearningIterationObservationV1::Dataset {
            snapshot_digest: dataset,
            episode_digest: publication.publication_digest(),
            withdrawal_frontier: publication.publication_digest(),
            rows: batch.rows(),
            bytes: batch.encoded().len() as u64,
        },
    ] {
        c.record(learning_test_receipt(&c, observation), 20)?;
    }
    Ok(c.snapshot().clone())
}

#[tokio::test]
async fn q24_dataset_original_task_and_terminal_target_drive_native_fit_and_no_update()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut a, baseline, bundle, _current) =
        ordinary(root.path(), "dataset-original-A", None).await?;
    a.request.body.artifact_set_digest = cell::d("independent-ingress-artifact-set").to_string();
    a.request.signature_hex = SigningKey::from_bytes(&[91; 32])
        .sign(&crate::authbus_objective_claims(&a.runtime.identity, &a.request)?.signing_bytes())
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let publication = execute(&a, 1).await?;
    assert_ne!(
        publication.original_record().snapshot.artifact_set_digest,
        bundle.digest()?
    );
    let parent = fs::read(root.path().join("heads"))?;
    for (index, raw) in [2_i64 << 32, 1_i64 << 32].into_iter().enumerate() {
        let files = tempfile::tempdir()?;
        let dataset = Dataset::new(
            files.path(),
            &[(&a, &publication, Some(raw))],
            OutcomeTerminalityV1::Terminal,
        )?;
        let original = a.cell.committed(&publication)?;
        let mut original_ids: Vec<_> = original
            .policy
            .iter()
            .map(|entry| entry.candidate_id.clone())
            .collect();
        let LedgerEvent::AuthenticatedDecisionV2(decision) = &dataset.frozen.records()[0].event
        else {
            anyhow::bail!("the original signed decision is the first ledger fact")
        };
        assert_ne!(decision.candidate_ids, original_ids);
        original_ids.sort();
        assert_eq!(decision.candidate_ids, original_ids);
        let batch = dataset.batch()?;
        assert_eq!(&batch.encoded()[..8], b"HQ24T002");
        let rule = CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let prefix = prefix(
            &publication,
            bundle.clone(),
            &batch,
            dataset.receipt.snapshot.dataset_digest,
        )?;
        let legacy = CellQ24TrainingBatchV1::new(
            dataset.receipt.snapshot.dataset_digest,
            vec![CellQ24TrainingSampleV1 {
                input: vec![Q, Q / 4],
                target: raw / 256,
            }],
        )?;
        assert_eq!(&legacy.encoded()[..8], b"HQ24T001");
        assert_ne!(rule.digest(&legacy)?, rule.digest(&batch)?);
        assert!(
            plan(Arc::clone(&baseline), &prefix, &batch, rule)?
                .fit(legacy, rule, &AtomicBool::new(false))
                .is_err()
        );
        let mut owner = CellQ24TrainingOwnerV1::create(
            file(files.path(), "training.journal")?,
            witness(files.path(), &prefix)?,
            plan(Arc::clone(&baseline), &prefix, &batch, rule)?,
            batch.clone(),
            rule,
        )?;
        match owner.fit_or_readback(&AtomicBool::new(false))? {
            CellQ24TrainingOutcomeV1::Candidate(candidate) => {
                assert_eq!(index, 0);
                assert_ne!(candidate.heads, parent);
                assert_eq!(candidate.model.components(), &candidate.bundle.components);
                fs::write(files.path().join("candidate.heads"), &candidate.heads)?;
                let loaded = LoadedCellQ24ModelV1::open_files(crate::CellQ24ModelFilesV1 {
                    base: File::open(root.path().join("base"))?,
                    encoder: File::open(root.path().join("encoder"))?,
                    heads: File::open(files.path().join("candidate.heads"))?,
                    organ_adapter: None,
                    cell_adapter: None,
                })?;
                assert_eq!(loaded.components(), &candidate.bundle.components);
                assert_eq!(
                    candidate.bundle.rollback_predecessor,
                    Some(bundle.digest()?)
                );
                assert!(
                    candidate.metrics.squared_error_after_q48
                        < candidate.metrics.squared_error_before_q48
                );
            }
            CellQ24TrainingOutcomeV1::NoUpdate {
                retained_bundle,
                metrics,
            } => {
                assert_eq!(index, 1);
                assert_eq!(retained_bundle, bundle.digest()?);
                assert_eq!(metrics.squared_error_before_q48, 0);
            }
        }
        let retained = fs::read(files.path().join("training.journal"))?;
        drop(owner);
        let mut recovered = CellQ24TrainingOwnerV1::recover(
            file(files.path(), "training.journal")?,
            witness(files.path(), &prefix)?,
            plan(Arc::clone(&baseline), &prefix, &batch, rule)?,
            batch.clone(),
            rule,
        )?;
        assert!(recovered.fit_or_readback(&AtomicBool::new(true)).is_ok());
        dataset.correct()?;
        assert!(matches!(
            recovered.readback(),
            Err(CellQ24TrainingOwnerErrorV1::Training(
                CellQ24TrainingErrorV1::Dataset(_)
            ))
        ));
        assert!(
            plan(Arc::clone(&baseline), &prefix, &batch, rule)?
                .fit(batch.clone(), rule, &AtomicBool::new(false))
                .is_err()
        );
        assert_eq!(fs::read(files.path().join("training.journal"))?, retained);
    }
    assert_eq!(fs::read(root.path().join("heads"))?, parent);
    a.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_dataset_rejects_missing_censored_wrong_units_and_untrusted_freeze()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut a, _, _, _current) = ordinary(root.path(), "dataset-negative-A", None).await?;
    let publication = execute(&a, 1).await?;
    for terminality in [
        OutcomeTerminalityV1::Pending,
        OutcomeTerminalityV1::Censored,
    ] {
        let files = tempfile::tempdir()?;
        let dataset = Dataset::new(files.path(), &[(&a, &publication, None)], terminality)?;
        assert!(dataset.batch().is_err());
    }
    for mutation in [CandidateMutation::Missing, CandidateMutation::Extra] {
        let files = tempfile::tempdir()?;
        let dataset = Dataset::with_candidate_mutation(
            files.path(),
            &[(&a, &publication, Some(0))],
            OutcomeTerminalityV1::Terminal,
            cell::d("fixture-target-unit"),
            Some(mutation),
        )?;
        assert!(matches!(
            dataset.batch(),
            Err(crate::CellQ24DatasetErrorV1::Binding(
                "exact task, model, decision, unit and outcome"
            ))
        ));
    }
    let missing_abstain_root = tempfile::tempdir()?;
    let missing_abstain = Dataset::with_candidate_mutation(
        missing_abstain_root.path(),
        &[(&a, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
        cell::d("fixture-target-unit"),
        Some(CandidateMutation::MissingAbstain),
    )
    .err()
    .expect("the original ledger rejects missing abstain before freezing");
    assert!(matches!(
        missing_abstain.downcast_ref::<ProductionLedgerError>(),
        Some(ProductionLedgerError::Durable(
            DurableLedgerError::Semantic(LedgerError::MissingAbstainCandidate)
        ))
    ));
    let duplicate_root = tempfile::tempdir()?;
    let duplicate = Dataset::with_candidate_mutation(
        duplicate_root.path(),
        &[(&a, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
        cell::d("fixture-target-unit"),
        Some(CandidateMutation::Duplicate),
    )
    .err()
    .expect("the original ledger rejects duplicate candidates before freezing");
    assert!(matches!(
        duplicate.downcast_ref::<ProductionLedgerError>(),
        Some(ProductionLedgerError::Binding("duplicate candidate"))
    ));
    let wrong_unit_root = tempfile::tempdir()?;
    let wrong_unit = Dataset::with_unit(
        wrong_unit_root.path(),
        &[(&a, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
        cell::d("different-signed-outcome-unit"),
    )?;
    assert!(matches!(
        wrong_unit.batch(),
        Err(crate::CellQ24DatasetErrorV1::Binding(
            "exact task, model, decision, unit and outcome"
        ))
    ));
    let wrong_bundle_root = tempfile::tempdir()?;
    let mut wrong_bundle = Dataset::new(
        wrong_bundle_root.path(),
        &[(&a, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    wrong_bundle.projection.baseline_bundle = cell::d("different-cell-bundle");
    wrong_bundle.refreeze()?;
    assert!(matches!(
        wrong_bundle.batch(),
        Err(crate::CellQ24DatasetErrorV1::Binding(
            "exact task, model, decision, unit and outcome"
        ))
    ));
    for raw in [-257_i64, -255, (8_i64 << 32) + 1] {
        let files = tempfile::tempdir()?;
        let mut dataset = Dataset::new(
            files.path(),
            &[(&a, &publication, Some(raw))],
            OutcomeTerminalityV1::Terminal,
        )?;
        if raw > (8_i64 << 32) {
            assert!(dataset.batch().is_err());
            continue;
        }
        let batch = dataset.batch()?;
        assert_eq!(
            i64::from_le_bytes(batch.encoded()[60..68].try_into()?),
            raw / 256
        );
        dataset.projection.unit_profile_digest = cell::d("different-unit");
        assert!(dataset.batch().is_err());
        dataset.projection.unit_profile_digest = cell::d("fixture-target-unit");
        dataset.evidence.signature[0] ^= 1;
        assert!(dataset.batch().is_err());
        dataset.evidence.signature[0] ^= 1;
        dataset.frozen.head_digest = cell::d("forged-frozen-prefix");
        assert!(dataset.batch().is_err());
    }
    a.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_dataset_row_order_and_original_withdrawal_are_preserved() -> anyhow::Result<()> {
    let root_a = tempfile::tempdir()?;
    let root_b = tempfile::tempdir()?;
    let (mut a, baseline, bundle, _current_a) =
        ordinary(root_a.path(), "dataset-order-A", None).await?;
    let (mut b, _, _, _current_b) = ordinary(
        root_b.path(),
        "dataset-order-B",
        Some(&a.request.body.source_envelope_json),
    )
    .await?;
    let pa = execute(&a, 1).await?;
    let pb = execute(&b, 1).await?;
    assert_ne!(pa.input().scope.run_id, pb.input().scope.run_id);
    assert_eq!(pa.input().objective_digest, pb.input().objective_digest);
    let files = tempfile::tempdir()?;
    let mut multiple = Dataset::new(
        files.path(),
        &[(&b, &pb, Some(-257)), (&a, &pa, Some(3_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let ordered = multiple.batch()?;
    assert_eq!(ordered.rows(), 2);
    assert_eq!(
        i64::from_le_bytes(ordered.encoded()[60..68].try_into()?),
        -1
    );
    assert_eq!(
        i64::from_le_bytes(ordered.encoded()[84..92].try_into()?),
        3 * Q
    );
    multiple.tasks.reverse();
    assert_eq!(multiple.batch()?.encoded(), ordered.encoded());
    multiple.tasks.push(multiple.tasks[0].clone());
    assert!(multiple.batch().is_err());

    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&a, &pa, Some(1_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let batch = dataset.batch()?;
    let prefix = prefix(&pa, bundle, &batch, dataset.receipt.snapshot.dataset_digest)?;
    let rule = CellQ24SgdRuleV1 {
        epochs: 1,
        learning_rate_q24: Q / 2,
    };
    let mut trainer = CellQ24TrainingOwnerV1::create(
        file(files.path(), "training.journal")?,
        witness(files.path(), &prefix)?,
        plan(Arc::clone(&baseline), &prefix, &batch, rule)?,
        batch.clone(),
        rule,
    )?;
    let retained = fs::read(files.path().join("training.journal"))?;
    a.source
        .withdraw_for_dataset_test(&pa.input().scope.run_id)?;
    assert!(matches!(
        trainer.fit_or_readback(&AtomicBool::new(false)),
        Err(CellQ24TrainingOwnerErrorV1::Training(
            CellQ24TrainingErrorV1::Dataset(_)
        ))
    ));
    assert_eq!(fs::read(files.path().join("training.journal"))?, retained);
    drop(trainer);
    assert!(matches!(
        CellQ24TrainingOwnerV1::recover(
            file(files.path(), "training.journal")?,
            witness(files.path(), &prefix)?,
            plan(baseline, &prefix, &batch, rule)?,
            batch,
            rule,
        ),
        Err(CellQ24TrainingOwnerErrorV1::Training(
            CellQ24TrainingErrorV1::Dataset(_)
        ))
    ));
    a.stop().await?;
    b.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_dataset_expiry_is_an_error_for_a_no_update_target() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut a, baseline, bundle, _current) =
        ordinary(root.path(), "dataset-expiry-A", None).await?;
    let publication = execute(&a, 1).await?;
    let files = tempfile::tempdir()?;
    let mut dataset = Dataset::new(
        files.path(),
        &[(&a, &publication, Some(1_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    dataset.evidence.expires_at = now() + 1;
    dataset.evidence.signature = SigningKey::from_bytes(&[3; 32])
        .sign(&dataset.evidence.signing_bytes())
        .to_bytes();
    let batch = dataset.batch()?;
    let prefix = prefix(
        &publication,
        bundle,
        &batch,
        dataset.receipt.snapshot.dataset_digest,
    )?;
    let rule = CellQ24SgdRuleV1 {
        epochs: 1,
        learning_rate_q24: Q / 2,
    };
    let plan = plan(baseline, &prefix, &batch, rule)?;
    tokio::time::timeout(Duration::from_secs(5), async {
        while now() <= dataset.evidence.expires_at {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert!(matches!(
        plan.fit(batch, rule, &AtomicBool::new(false)),
        Err(CellQ24TrainingErrorV1::Dataset(
            crate::CellQ24DatasetErrorV1::Authentication(SignedEvidenceError::ValidityWindow)
        ))
    ));
    a.stop().await?;
    Ok(())
}
