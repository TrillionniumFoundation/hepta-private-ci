use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_bellman_operator::FinalUseError;
use codex_hepta_bellman_operator::RuntimeLimitsV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TrainingProfileV1;
use codex_hepta_bellman_operator::UnboundTabularOperatorPlanV3;
use codex_hepta_bellman_operator::UnboundWorldModelDatasetV3;
use codex_hepta_bellman_operator::WorkControlError;
use codex_hepta_bellman_operator::WorldModelProfileV1;
use codex_hepta_bellman_operator::WorldModelSampleV1;
use codex_hepta_bellman_operator::fit_tabular_operator_verified_v3;
use codex_hepta_bellman_operator::fit_transition_model_verified_v3;
use codex_hepta_bellman_operator::revalidate_tabular_candidate_for_publication_v3;
use codex_hepta_bellman_operator::revalidate_world_model_candidate_for_publication_v3;
use codex_hepta_bellman_operator::verify_tabular_operator_plan_v3;
use codex_hepta_bellman_operator::verify_world_model_dataset_v3;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(1);
static NEXT_EVIDENCE: AtomicU64 = AtomicU64::new(1);

fn id(value: impl AsRef<str>) -> TestResult<StableId> {
    Ok(StableId::new(value.as_ref())?)
}

fn digest(value: impl AsRef<[u8]>) -> Digest32 {
    Digest32::of_bytes(value.as_ref())
}

fn key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

fn trusted(
    name: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TestResult<TrustedLearningSignerV1> {
    let signing = key(seed);
    Ok(TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name)?,
            credential_chain_digest: digest(format!("{name}-credential")),
            signing_key_digest: digest(signing.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(format!("{name}-controller"))?,
        verifying_key: signing.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    })
}

fn trust() -> TestResult<LearningEvidenceTrustV1> {
    Ok(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted("generator", 1, LearningEvidenceRoleV1::Generator)?,
            trusted("observer", 2, LearningEvidenceRoleV1::Observer)?,
            trusted("evaluator", 3, LearningEvidenceRoleV1::Evaluator)?,
        ],
    })
}

fn activated_trust() -> TestResult<ActivatedLearningTrustV1> {
    let root_key = key(99);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root")?,
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-distribution")?,
            generation: 1,
            effective_at: 20,
            trust: trust()?,
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes()?).to_bytes();
    Ok(activate_learning_trust(&root, signed, None, 50)?)
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> TestResult<SignedLearningEvidenceV1> {
    let signing = match principal {
        "generator" => key(1),
        "observer" => key(2),
        "evaluator" => key(3),
        _ => panic!("unknown principal"),
    };
    let nonce = NEXT_EVIDENCE.fetch_add(1, Ordering::Relaxed);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(format!("evidence-{principal}-{nonce}"))?,
        principal_id: id(principal)?,
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    Ok(evidence)
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let suffix = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-bellman-final-use-v3-{}-{suffix}",
            std::process::id()
        ));
        std::fs::create_dir(&root)?;
        Ok(Self { root })
    }

    fn new_file(&self, name: &str) -> TestResult<File> {
        Ok(OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(self.root.join(name))?)
    }

    fn directory(&self) -> TestResult<File> {
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;

            // Match the ledger owner's existing Windows directory-flush fixture.
            Ok(OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
                .open(&self.root)?)
        }
        #[cfg(not(windows))]
        Ok(File::open(&self.root)?)
    }

    fn writer(&self) -> TestResult<LedgerWriter> {
        let binding = digest("bellman-final-use-ledger");
        let ledger = DurableLedger::create(self.new_file("ledger")?, binding, 1_024)?;
        let witness = LedgerWitnessStore::create(self.new_file("witness")?, binding)?;
        let directory = self.directory()?;
        Ok(LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust()?,
            &directory,
            &directory,
        )?)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn decision(prefix: &str) -> TestResult<ProductionDecisionV2> {
    let candidates = vec![id(format!("{prefix}.selected"))?, id("abstain")?];
    Ok(ProductionDecisionV2 {
        record_id: id(format!("{prefix}.decision-record"))?,
        episode_id: id(format!("{prefix}.episode"))?,
        run_snapshot_digest: digest(format!("{prefix}.run")),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id(format!("{prefix}.selected"))?,
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(format!("{prefix}.candidate-set"))?,
            state_digest: digest(format!("{prefix}.state")),
            generator_id: id("generator")?,
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest(format!("{prefix}.support")),
    })
}

fn outcome(
    record_id: &str,
    outcome_id: &str,
    predecessor: Option<&str>,
    episode_id: &str,
    value: i64,
) -> TestResult<AuthenticatedOutcomeV1> {
    Ok(AuthenticatedOutcomeV1 {
        record_id: id(record_id)?,
        outcome_id: id(outcome_id)?,
        episode_id: id(episode_id)?,
        observer: trusted("observer", 2, LearningEvidenceRoleV1::Observer)?.principal,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(value)),
        unit_profile_digest: digest("outcome-units"),
        support_digest: digest(format!("support-{record_id}")),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: predecessor.map(id).transpose()?,
            finalized_at: Some(46),
        },
    })
}

fn collect(owner: &mut LedgerWriter, prefix: &str, value: i64) -> TestResult<StableId> {
    let decision = decision(prefix)?;
    let signed = sign(
        owner.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision)?,
    )?;
    let head = owner.witness_frontier()?.anchor.chain_digest;
    owner.append_decision(head, decision, &signed, 50)?;

    let outcome_id = id(format!("{prefix}.result"))?;
    let outcome = outcome(
        &format!("{prefix}.outcome-record"),
        outcome_id.as_str(),
        None,
        &format!("{prefix}.episode"),
        value,
    )?;
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    )?;
    let head = owner.witness_frontier()?.anchor.chain_digest;
    owner.append_outcome(head, outcome, &signed, 50)?;
    Ok(outcome_id)
}

fn qualified_dataset() -> TestResult<(Fixture, LedgerWriter, DatasetSnapshotReceiptV3, StableId)> {
    let fixture = Fixture::new()?;
    let mut owner = fixture.writer()?;
    let first_outcome = collect(&mut owner, "first", 0)?;
    collect(&mut owner, "second", FixedQ32::ONE.raw())?;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset")?,
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("policy"),
    };
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?,
    )?;
    let receipt = owner.freeze_dataset(plan, &signed, 50)?;
    Ok((fixture, owner, receipt, first_outcome))
}

#[path = "final_use_v3/memory_training.rs"]
mod memory_training;

fn runtime() -> TestResult<RuntimeLimitsV1> {
    Ok(RuntimeLimitsV1::new(10_000, 1_000_000)?)
}

fn training_profile(
    receipt: &DatasetSnapshotReceiptV3,
    maximum_absolute_error: FixedQ32,
) -> TestResult<TrainingProfileV1> {
    Ok(TrainingProfileV1::new(
        Generation::new(1)?,
        receipt.snapshot.objective_digest,
        digest("sensor-core"),
        receipt.snapshot.eligible_frontier,
        1,
        maximum_absolute_error,
        runtime()?,
    )?)
}

fn tabular_input(
    receipt: &DatasetSnapshotReceiptV3,
    varying_targets: bool,
) -> TestResult<UnboundTabularOperatorPlanV3> {
    let sensor = id("sensor")?;
    let action = id("action")?;
    let samples = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| {
            Ok(TabularOperatorSampleV1 {
                sample_id: id(format!("sample-{index}"))?,
                sensor_id: sensor.clone(),
                action_id: action.clone(),
                target: if varying_targets {
                    FixedQ32::from_raw(i64::try_from(index)?)
                } else {
                    FixedQ32::ZERO
                },
                evidence_digest: *evidence_digest,
            })
        })
        .collect::<TestResult<Vec<_>>>()?;
    Ok(UnboundTabularOperatorPlanV3 {
        artifact_id: id("artifact")?,
        producer_id: id("producer")?,
        sensor_ids: vec![sensor],
        action_ids: vec![action],
        samples,
    })
}

fn append_correction(owner: &mut LedgerWriter, predecessor: &StableId) -> TestResult<()> {
    let correction = outcome(
        "correction.record",
        "correction.result",
        Some(predecessor.as_str()),
        "first.episode",
        FixedQ32::ONE.raw(),
    )?;
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    )?;
    let head = owner.witness_frontier()?.anchor.chain_digest;
    owner.append_outcome(head, correction, &signed, 50)?;
    Ok(())
}

fn world_input(
    receipt: &DatasetSnapshotReceiptV3,
    split_next_states: bool,
) -> TestResult<UnboundWorldModelDatasetV3> {
    let samples = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| {
            Ok(WorldModelSampleV1 {
                sample_id: id(format!("world-sample-{index}"))?,
                state_id: id("state")?,
                action_id: id("action")?,
                next_state_id: if split_next_states && index % 2 == 1 {
                    id("next-b")?
                } else {
                    id("next-a")?
                },
                outcome: FixedQ32::ZERO,
                evidence_digest: *evidence_digest,
            })
        })
        .collect::<TestResult<Vec<_>>>()?;
    Ok(UnboundWorldModelDatasetV3 {
        model_id: id("world-model")?,
        samples,
    })
}

fn world_profile(receipt: &DatasetSnapshotReceiptV3) -> TestResult<WorldModelProfileV1> {
    Ok(WorldModelProfileV1::new(
        Generation::new(1)?,
        receipt.snapshot.objective_digest,
        digest("sensor-core"),
        receipt.snapshot.eligible_frontier,
        1,
        FixedQ32::ZERO,
        runtime()?,
    )?)
}

#[test]
fn tabular_v3_uses_profile_control_and_only_hands_off_pinned_payload() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = qualified_dataset()?;
    let profile = training_profile(&receipt, FixedQ32::ONE)?;
    let (verified, cancellation) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false)?,
        &profile,
        receipt,
        50,
    )
    .unwrap();
    assert!(!cancellation.is_cancelled());
    let fitted = fit_tabular_operator_verified_v3(&owner, verified, 50).unwrap();
    let ready = revalidate_tabular_candidate_for_publication_v3(&owner, fitted, 50).unwrap();
    let prepared = ready.prepare_pinned_payload().unwrap();
    assert!(!prepared.pin().payload_digest.is_zero());
    let loaded = prepared.into_loaded().unwrap();
    let prediction = loaded.predict(&id("sensor")?, &id("action")?).unwrap();
    assert_eq!(prediction.value, FixedQ32::ZERO);
    assert!(!prediction.authority.grants_any());
    Ok(())
}

#[test]
fn tabular_v3_observes_cancellation_and_fit_time_currentness() -> TestResult<()> {
    let (_fixture, mut owner, receipt, predecessor) = qualified_dataset()?;
    let profile = training_profile(&receipt, FixedQ32::ONE)?;
    let (verified, cancellation) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false)?,
        &profile,
        receipt.clone(),
        50,
    )
    .unwrap();
    cancellation.cancel();
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::WorkControl(WorkControlError::Cancelled))
    ));

    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false)?,
        &profile,
        receipt,
        50,
    )
    .unwrap();
    append_correction(&mut owner, &predecessor)?;
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Ledger(_))
    ));
    Ok(())
}

#[test]
fn tabular_v3_revalidates_again_before_publication() -> TestResult<()> {
    let (_fixture, mut owner, receipt, predecessor) = qualified_dataset()?;
    let profile = training_profile(&receipt, FixedQ32::ONE)?;
    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false)?,
        &profile,
        receipt,
        50,
    )
    .unwrap();
    let fitted = fit_tabular_operator_verified_v3(&owner, verified, 50).unwrap();
    append_correction(&mut owner, &predecessor)?;
    assert!(matches!(
        revalidate_tabular_candidate_for_publication_v3(&owner, fitted, 50),
        Err(FinalUseError::Ledger(_))
    ));
    Ok(())
}

#[test]
fn canonical_error_budget_is_an_admission_condition() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = qualified_dataset()?;
    let profile = training_profile(&receipt, FixedQ32::ZERO)?;
    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, true)?,
        &profile,
        receipt,
        50,
    )
    .unwrap();
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Binding("tabular error budget"))
    ));
    Ok(())
}

#[test]
fn world_v3_enforces_uncertainty_and_keeps_raw_model_private() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = qualified_dataset()?;
    let profile = world_profile(&receipt)?;
    let (verified, cancellation) = verify_world_model_dataset_v3(
        &owner,
        world_input(&receipt, false)?,
        &profile,
        receipt.clone(),
        50,
    )
    .unwrap();
    assert!(!cancellation.is_cancelled());
    let fitted = fit_transition_model_verified_v3(&owner, verified, 50).unwrap();
    let ready = revalidate_world_model_candidate_for_publication_v3(&owner, fitted, 50).unwrap();
    assert!(!ready.model_digest().is_zero());
    assert_eq!(ready.dataset_digest(), receipt.snapshot.dataset_digest);
    assert_eq!(ready.profile_digest(), profile.digest());

    let (verified, _) =
        verify_world_model_dataset_v3(&owner, world_input(&receipt, true)?, &profile, receipt, 50)
            .unwrap();
    assert!(matches!(
        fit_transition_model_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Binding("world uncertainty budget"))
    ));
    Ok(())
}

#[test]
fn terminal_cell_fits_only_observed_actions_and_rechecks_the_owner() -> TestResult<()> {
    use codex_hepta_bellman_operator::TerminalCellError;
    use codex_hepta_bellman_operator::TerminalCellProfileV1;
    use codex_hepta_bellman_operator::TerminalSupportedCellProfileV1;
    use codex_hepta_bellman_operator::fit_terminal_cell_from_owner_v1;
    use codex_hepta_bellman_operator::freeze_supported_terminal_cells_from_owner_v1;
    use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;

    let fixture = Fixture::new()?;
    let mut owner = fixture.writer()?;
    let target = FixedQ32::from_raw(FixedQ32::ONE.raw() / 4);
    let outcome_id = collect(&mut owner, "first", target.raw())?;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("terminal.dataset")?,
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("policy"),
    };
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?,
    )?;
    let now = 50;
    let dataset = owner.freeze_dataset(plan, &signed, now)?;
    let selected = id("first.selected")?;
    let cells = TerminalCellProfileV1 {
        artifact_id: id("terminal.artifact")?,
        producer_id: id("terminal.producer")?,
        generation: Generation::new(1)?,
        sensor_id: id("single-state")?,
        objective_digest: dataset.snapshot.objective_digest,
        run_snapshot_digest: digest("first.run"),
        unit_profile_digest: digest("outcome-units"),
        action_ids: vec![selected.clone()],
        minimum_samples_per_action: 1,
    };
    let supported = TerminalSupportedCellProfileV1 {
        cells: cells.clone(),
        candidate_ids: vec![selected.clone(), id("abstain")?],
    };

    let mut complete = cells;
    complete.action_ids.clone_from(&supported.candidate_ids);
    let complete = freeze_terminal_cell_from_owner_v1(&owner, &dataset, complete, now)?;
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&owner, complete, now),
        Err(TerminalCellError::Fit(_))
    ));

    let mut insufficient = supported.clone();
    insufficient.cells.minimum_samples_per_action = 2;
    assert!(matches!(
        freeze_supported_terminal_cells_from_owner_v1(&owner, &dataset, insufficient, now),
        Err(TerminalCellError::Unsupported(
            "insufficient owner action support"
        ))
    ));
    let frozen = freeze_supported_terminal_cells_from_owner_v1(&owner, &dataset, supported, now)?;
    assert_eq!(frozen.dataset(), &dataset);
    assert_eq!(frozen.sample_count(), 1);
    let artifact = fit_terminal_cell_from_owner_v1(&owner, frozen.clone(), now)?;
    assert_eq!(artifact.dataset_digest, dataset.snapshot.dataset_digest);
    assert!(!artifact.authority.grants_any());
    let [cell] = artifact.cells.as_slice() else {
        return Err("expected exactly one observed action cell".into());
    };
    assert_eq!(cell.action_id, selected);
    assert_eq!(cell.sample_count, 1);
    assert_eq!(
        (cell.minimum_target, cell.mean_target, cell.maximum_target),
        (target, target, target)
    );

    append_correction(&mut owner, &outcome_id)?;
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&owner, frozen, now),
        Err(TerminalCellError::Ledger(_))
    ));
    Ok(())
}
