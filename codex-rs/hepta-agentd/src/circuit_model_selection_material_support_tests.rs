//! Original Source/Ledger -> Material receipts used by the positive fixture.
//! Roles, keys, terminal label and Root scope are explicit test custody. The
//! terminal label is fixed independently of every model output.
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

use super::*;

pub(super) struct Credentials {
    pub(super) generator: TrustedLearningSignerV1,
    pub(super) evaluator: TrustedLearningSignerV1,
    pub(super) selector: TrustedLearningSignerV1,
    pub(super) unlearning: TrustedLearningSignerV1,
    pub(super) observer: TrustedLearningSignerV1,
    experience: TrustedLearningSignerV1,
    dataset: TrustedLearningSignerV1,
}

impl Credentials {
    // Retain the exact original fixture actors without exposing private fields.
    pub(super) fn resident_checkpoint_signers(&self) -> [TrustedLearningSignerV1; 4] {
        [
            self.experience.clone(),
            self.dataset.clone(),
            self.generator.clone(),
            self.evaluator.clone(),
        ]
    }
}

fn signer(name: &str, role: LearningEvidenceRoleV1, seed: u8, at: u64) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: d(&format!("explicit-positive-{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: d("explicit-positive-original-trust"),
            authority_epoch: 7,
            authenticated_at: at - 60,
            expires_at: at + 2_400,
        },
        controller_id: id(&format!("explicit-positive-{name}-controller")),
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
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "explicit-positive-evidence:{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: signer.principal.principal_id.clone(),
        role: signer.roles[0],
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 7,
        issued_at: at,
        expires_at: at + 1_800,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

pub(super) fn ledger(
    root: &std::path::Path,
    objective: Digest32,
) -> anyhow::Result<(LedgerWriter, Credentials)> {
    ledger_at(root, objective, now()?, d("explicit-positive-ledger"))
}

pub(super) fn ledger_at(
    root: &std::path::Path,
    objective: Digest32,
    at: u64,
    binding: Digest32,
) -> anyhow::Result<(LedgerWriter, Credentials)> {
    let credentials = Credentials {
        generator: signer(
            "positive-generator",
            LearningEvidenceRoleV1::Generator,
            41,
            at,
        ),
        evaluator: signer(
            "positive-evaluator",
            LearningEvidenceRoleV1::Evaluator,
            42,
            at,
        ),
        observer: signer("positive-outcome", LearningEvidenceRoleV1::Observer, 43, at),
        experience: signer(
            "positive-experience",
            LearningEvidenceRoleV1::Observer,
            44,
            at,
        ),
        dataset: signer("positive-dataset", LearningEvidenceRoleV1::Observer, 45, at),
        selector: signer(
            "positive-selector",
            LearningEvidenceRoleV1::Selector,
            46,
            at,
        ),
        unlearning: signer(
            "positive-unlearning",
            LearningEvidenceRoleV1::UnlearningAuthority,
            48,
            at,
        ),
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("explicit-positive-trust-distribution"),
            generation: 1,
            effective_at: at - 40,
            trust: LearningEvidenceTrustV1 {
                scope_digest: d("explicit-positive-original-trust"),
                objective_digest: objective,
                authority_epoch: 7,
                signers: vec![
                    credentials.generator.clone(),
                    credentials.evaluator.clone(),
                    credentials.observer.clone(),
                    credentials.experience.clone(),
                    credentials.dataset.clone(),
                    credentials.selector.clone(),
                    credentials.unlearning.clone(),
                ],
            },
        },
        root_id: id("explicit-positive-root"),
        issued_at: at - 45,
        expires_at: at + 3_000,
        signature: [0; 64],
    };
    let root_key = SigningKey::from_bytes(&[99; 32]);
    distribution.signature = root_key.sign(&distribution.signing_bytes()?).to_bytes();
    let trust = activate_learning_trust(
        &LearningTrustRootV1 {
            root_id: distribution.root_id.clone(),
            scope_digest: d("explicit-positive-original-trust"),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: at - 60,
            expires_at: at + 3_600,
            revoked_at: None,
        },
        distribution,
        None,
        at,
    )?;
    let ledger = DurableLedger::create(opened(root, "positive-ledger", true)?, binding, 64)?;
    let witness =
        LedgerWitnessStore::create(opened(root, "positive-ledger-witness", true)?, binding)?;
    let directory = File::open(root)?;
    Ok((
        LedgerWriter::from_durable(ledger, witness, trust, &directory, &directory)?,
        credentials,
    ))
}

pub(super) fn decision(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<()> {
    let source = publication.input();
    let policy = publication.original_policy()?;
    let mut candidates = policy
        .entries()
        .iter()
        .map(|item| item.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    let record = ProductionDecisionV2 {
        record_id: source.scope.run_id.clone(),
        episode_id: id("positive-original-episode"),
        run_snapshot_digest: source.ndu_snapshot_digest,
        objective_digest: source.objective_digest,
        policy_digest: Digest32::of_bytes(publication.output()),
        candidate_ids: candidates.clone(),
        selected_candidate_id: policy.selected().clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("explicit-positive-candidates"),
            state_digest: d("explicit-positive-decision-state"),
            generator_id: credentials.generator.principal.principal_id.clone(),
            generator_code_digest: d("explicit-positive-generator-code"),
            grammar_digest: d("explicit-positive-grammar"),
            hard_filter_digest: d("explicit-positive-filter"),
            truncation_digest: d("explicit-positive-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: candidates.len().try_into()?,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: publication.publication_digest(),
    };
    let at = now()?;
    let evidence = sign(
        writer.verifier(),
        &credentials.generator,
        41,
        &decision_signing_payload_v2(&record)?,
        at,
    );
    writer.append_decision(Digest32::ZERO, record, &evidence, at)?;
    Ok(())
}

pub(super) fn terminal_outcome(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<()> {
    terminal_outcome_with_value(
        writer,
        credentials,
        publication,
        FixedQ32::from_raw(2_i64 << 32),
    )
}

// The caller fixes this explicit test measurement before material or Training.
// It is never computed from the model output or a subsequent training result.
pub(super) fn terminal_outcome_with_value(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
    value: FixedQ32,
) -> anyhow::Result<()> {
    let admitted_at = publication
        .original_record()
        .admission
        .observed_at_unix_micros
        .div_ceil(1_000_000);
    let before = now()?;
    if admitted_at > before {
        anyhow::ensure!(
            admitted_at - before == 1,
            "fixture admission is in the future"
        );
        // The signed Outcome has second precision. Wait for the real clock
        // rather than inventing a future timestamp or rounding admission down.
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    let at = now()?;
    anyhow::ensure!(at >= admitted_at, "clock moved before source admission");
    // Explicit independent terminal target, fixed before any material read.
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("positive-original-outcome-record"),
        outcome_id: id("positive-original-outcome"),
        episode_id: id("positive-original-episode"),
        observer: credentials.observer.principal.clone(),
        observed_at: Some(at),
        value: Some(value),
        unit_profile_digest: d("explicit-positive-terminal-unit"),
        support_digest: d("explicit-positive-independent-terminal-label"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: at,
            expected_delay_profile_digest: d("explicit-positive-observation-delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(at),
        },
    };
    let evidence = sign(
        writer.verifier(),
        &credentials.observer,
        43,
        &outcome_signing_payload_v2(&outcome),
        at,
    );
    writer.append_outcome(writer.snapshot()?.head_digest, outcome, &evidence, at)?;
    Ok(())
}

pub(super) struct Material {
    pub(super) command_config: crate::OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) initial: LearningIterationSnapshotV1,
    pub(super) config: crate::OriginalCellQ24TrainingSourceConfigV1,
    pub(super) frozen: DatasetSnapshotReceiptV3,
}

pub(super) fn material(
    root: &std::path::Path,
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    source: &crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    identity: &crate::AgentdIdentity,
    baseline: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<Material> {
    material_with_profile(
        root,
        writer,
        credentials,
        source,
        identity,
        baseline,
        bundle,
        publication,
        d("explicit-positive-independent-evaluation-profile"),
    )
}

pub(super) fn unstarted_material_with_profile(
    _root: &std::path::Path,
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    source: &crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    identity: &crate::AgentdIdentity,
    baseline: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    publication: &CircuitTaskSourcePublicationV1,
    evaluation_profile: Digest32,
    next_use_observer: StableId,
) -> anyhow::Result<(
    crate::OriginalCellQ24MaterialReceiptConfigV1,
    crate::CellQ24SgdRuleV1,
)> {
    let input = publication.input();
    let initial = LearningIterationCoordinatorV1::new(
        LearningIterationRequestV1 {
            operation_id: id("positive-original-learning-operation"),
            principal_id: id(&input.scope.principal_digest.to_string()),
            agent_id: input.scope.agent_id.clone(),
            cell_id: input.scope.cell_id.clone(),
            source_run_id: input.scope.run_id.clone(),
            completed_task_receipt: publication.history_digest().as_str().parse()?,
            selected_artifact_digest: bundle.components.base,
            selected_bundle: bundle.clone(),
            evaluation_profile,
            envelope: IterationEnvelopeV1 {
                envelope_id: id("positive-original-envelope"),
                base_commit: d("0bfe47e53bae47977c4423362e4d3823edac99fd"),
                base_tree: d("8663f89daca111ba7f681d2c36442f6f4ded97f5"),
                objective_digest: input.objective_digest,
                grammar_digest: d("explicit-positive-single-head-grammar"),
                maximum_files: 1,
                maximum_diff_bytes: 4_096,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: now()? + 900,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 2,
                maximum_training_milliseconds: 10_000,
                maximum_artifact_bytes: 4_096,
            },
        },
        LearningIterationOwnersV1 {
            evidence_trust_digest: writer.verifier().trust_digest(),
            experience: credentials.experience.principal.principal_id.clone(),
            dataset: credentials.dataset.principal.principal_id.clone(),
            trainer: credentials.generator.principal.principal_id.clone(),
            evaluator: credentials.evaluator.principal.principal_id.clone(),
            proposal: id("positive-original-model"),
            selector: credentials.selector.principal.principal_id.clone(),
            next_use_observer,
        },
    )?
    .snapshot()
    .clone();
    let rule = crate::CellQ24DatasetRuleV1 {
        head: crate::CellQ24PrivateHeadV1::Prediction { index: 0 },
        unit_profile_digest: d("explicit-positive-terminal-unit"),
    };
    let freeze_plan = DatasetFreezePlanV2 {
        snapshot_id: id("positive-original-dataset"),
        objective_digest: input.objective_digest,
        inclusion_policy_digest: rule.inclusion_policy_digest(&initial)?,
    };
    let freeze_evidence = sign(
        writer.verifier(),
        &credentials.evaluator,
        42,
        &dataset_freeze_signing_payload_v2(&writer.snapshot()?, &freeze_plan)?,
        now()?,
    );
    let observed = crate::CellQ24DatasetReaderV1::new(source, identity, writer).read_current(
        &initial,
        baseline,
        rule,
        freeze_plan.clone(),
        &freeze_evidence,
    )?;
    let optimizer = crate::CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    let update_rule = crate::cell_q24_single_head_update_rule_v1(
        bundle,
        rule.head,
        optimizer.digest(observed.batch())?,
    )?;
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    let config = crate::OriginalCellQ24MaterialReceiptConfigV1 {
        initial: initial.clone(),
        scope: scope.clone(),
        rule,
        freeze_plan: freeze_plan.clone(),
        freeze_evidence: freeze_evidence.clone(),
        experience_signer: credentials.experience.clone(),
        dataset_signer: credentials.dataset.clone(),
        verifier: writer.verifier().clone(),
        maximum_signature_lifetime_seconds: 600,
    };
    Ok((config, optimizer))
}

pub(super) fn material_with_profile(
    root: &std::path::Path,
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    source: &crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    identity: &crate::AgentdIdentity,
    baseline: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    publication: &CircuitTaskSourcePublicationV1,
    evaluation_profile: Digest32,
) -> anyhow::Result<Material> {
    material_with_profile_and_observer(
        root,
        writer,
        credentials,
        source,
        identity,
        baseline,
        bundle,
        publication,
        evaluation_profile,
        id("unused-positive-next-use-role"),
    )
}

// Choose C's original enrolled actor before the first material receipt is
// signed. No completed cut or predecessor signature is rewritten for C.
pub(super) fn material_with_profile_and_observer(
    root: &std::path::Path,
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    source: &crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    identity: &crate::AgentdIdentity,
    baseline: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    publication: &CircuitTaskSourcePublicationV1,
    evaluation_profile: Digest32,
    next_use_observer: StableId,
) -> anyhow::Result<Material> {
    let (config, optimizer) = unstarted_material_with_profile(
        root,
        writer,
        credentials,
        source,
        identity,
        baseline,
        bundle,
        publication,
        evaluation_profile,
        next_use_observer,
    )?;
    let input = publication.input();
    let initial = config.initial.clone();
    let scope = config.scope.clone();
    let rule = config.rule;
    let freeze_plan = config.freeze_plan.clone();
    let freeze_evidence = config.freeze_evidence.clone();
    let mut owners = crate::OriginalCellQ24MaterialReceiptOwnersV1::create(
        crate::OriginalCellQ24MaterialReceiptFilesV1 {
            experience: opened(root, "positive-experience", true)?,
            experience_witness: original_witness(
                root,
                "positive-experience-witness",
                &scope,
                input.objective_digest,
                true,
            )?,
            dataset: opened(root, "positive-dataset", true)?,
            dataset_witness: original_witness(
                root,
                "positive-dataset-witness",
                &scope,
                input.objective_digest,
                true,
            )?,
        },
        config.clone(),
        SigningKey::from_bytes(&[44; 32]),
        SigningKey::from_bytes(&[45; 32]),
    )?;
    let experience = owners.attest_experience(crate::OriginalCellQ24MaterialReceiptSourcesV1 {
        snapshot: &initial,
        source,
        identity,
        ledger: writer,
        baseline,
    })?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    coordinator.record(
        experience.receipt.clone(),
        experience.receipt.observed_unix_seconds,
    )?;
    let dataset = owners.attest_dataset(crate::OriginalCellQ24MaterialReceiptSourcesV1 {
        snapshot: coordinator.snapshot(),
        source,
        identity,
        ledger: writer,
        baseline,
    })?;
    coordinator.record(
        dataset.receipt.clone(),
        dataset.receipt.observed_unix_seconds,
    )?;
    let frozen = dataset.material.receipt().clone();
    drop(owners);
    Ok(Material {
        command_config: config,
        initial,
        config: crate::OriginalCellQ24TrainingSourceConfigV1 {
            dataset: coordinator.snapshot().clone(),
            scope,
            rule,
            optimizer,
            freeze_plan,
            freeze_evidence,
            experience_evidence: experience.attestation,
            dataset_evidence: dataset.attestation,
            verifier: writer.verifier().clone(),
        },
        frozen,
    })
}

#[path = "circuit_original_evaluation_ledger_support_tests.rs"]
pub(super) mod evaluation_provider;
