//! Behavior tests of real source/ledger reads and exact batch derivation.
//! RunStart, model receipts, signer keys and rewards are explicit fixtures;
//! these tests are not an ordinary-root adoption or independent evaluation.

use super::*;
use crate::circuit_cell::tests::support::checked;
use crate::circuit_cell::tests::support::d;
use crate::circuit_cell::tests::support::id;
use crate::circuit_credit::circuit_learning_run_id_v1;
use crate::circuit_task::cell_q24_dataset_source_test_support as source;
use crate::circuit_task::source_test_support::identity;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

#[path = "circuit_credit_ledger_test_support.rs"]
mod ledger;

#[path = "cell_q24_dataset_binding_tests.rs"]
mod binding;

fn initial(
    publication: &CircuitTaskSourcePublicationV1,
    bundle: &CellCompatibilityBundleV1,
    trust: Digest32,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let input = publication.input();
    let mut digest = [0_u8; 32];
    for (index, byte) in digest.iter_mut().enumerate() {
        *byte = u8::from_str_radix(
            &publication.history_digest().as_str()[2 * index..2 * index + 2],
            16,
        )?;
    }
    Ok(LearningIterationCoordinatorV1::new(
        LearningIterationRequestV1 {
            operation_id: id("original-dataset-operation"),
            principal_id: id(&input.scope.principal_digest.to_string()),
            agent_id: input.scope.agent_id.clone(),
            cell_id: input.scope.cell_id.clone(),
            source_run_id: input.scope.run_id.clone(),
            completed_task_receipt: Digest32::from_array(digest),
            selected_artifact_digest: bundle.components.base,
            evaluation_profile: d("frozen-independent-evaluation"),
            selected_bundle: bundle.clone(),
            envelope: IterationEnvelopeV1 {
                envelope_id: id("original-envelope"),
                base_commit: d("fixed-source-commit"),
                base_tree: d("fixed-source-tree"),
                objective_digest: input.objective_digest,
                grammar_digest: d("grammar"),
                maximum_files: 1,
                maximum_diff_bytes: 128,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: 100,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 16,
                maximum_training_milliseconds: 1_000,
                maximum_artifact_bytes: 1_024,
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
            next_use_observer: id("observer"),
        },
    )?
    .snapshot()
    .clone())
}

fn rule() -> CellQ24DatasetRuleV1 {
    CellQ24DatasetRuleV1 {
        head: CellQ24PrivateHeadV1::Prediction { index: 0 },
        unit_profile_digest: d("reward-units"),
    }
}

fn freeze(
    writer: &LedgerWriter,
    initial: &LearningIterationSnapshotV1,
    rule: CellQ24DatasetRuleV1,
) -> anyhow::Result<(DatasetFreezePlanV2, SignedLearningEvidenceV1)> {
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("original-snapshot"),
        objective_digest: initial.request.envelope.objective_digest,
        inclusion_policy_digest: rule.inclusion_policy_digest(initial)?,
    };
    let signed = ledger::sign(
        writer,
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&writer.snapshot()?, &plan)?,
    );
    Ok((plan, signed))
}

fn decision(publication: &CircuitTaskSourcePublicationV1) -> anyhow::Result<ProductionDecisionV2> {
    let policy = publication.original_policy()?;
    let mut candidates = policy
        .entries()
        .iter()
        .map(|entry| entry.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    Ok(ProductionDecisionV2 {
        record_id: publication.input().scope.run_id.clone(),
        episode_id: id("episode"),
        run_snapshot_digest: publication.input().ndu_snapshot_digest,
        objective_digest: publication.input().objective_digest,
        policy_digest: Digest32::of_bytes(publication.output()),
        candidate_ids: candidates.clone(),
        selected_candidate_id: policy.selected().clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("set"),
            state_digest: d("fixture-state"),
            generator_id: id("generator"),
            generator_code_digest: d("fixture-code"),
            grammar_digest: d("fixture-grammar"),
            hard_filter_digest: d("fixture-filter"),
            truncation_digest: d("fixture-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: publication.publication_digest(),
    })
}

fn append_decision(
    writer: &mut LedgerWriter,
    decision: ProductionDecisionV2,
) -> anyhow::Result<()> {
    let evidence = ledger::sign(
        writer,
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision)?,
    );
    writer.append_decision(
        writer.snapshot()?.head_digest,
        decision,
        &evidence,
        /*now*/ 50,
    )?;
    Ok(())
}

fn outcome(publication: &CircuitTaskSourcePublicationV1, value: i64) -> AuthenticatedOutcomeV1 {
    AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer: ledger::trusted(LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(value)),
        unit_profile_digest: d("reward-units"),
        support_digest: publication.publication_digest(),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: d("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    }
}

fn append_outcome(writer: &mut LedgerWriter, outcome: AuthenticatedOutcomeV1) {
    let evidence = ledger::sign(
        writer,
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    checked(writer.append_outcome(
        checked(writer.snapshot()).head_digest,
        outcome,
        &evidence,
        /*now*/ 50,
    ));
}

#[tokio::test]
async fn original_task_and_signed_cut_materialize_exact_q24_without_writes_or_new_claims()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (baseline, bundle) = source::model(root.path())?;
    let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
    let mut writer = fixture.writer;
    let identity = identity(root.path())?;
    let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
    // The actual TaskSource/Circuit run is fixed before execution and before
    // its completed publication; no finished trace is renamed into the ledger.
    let input = [codec::Q / 2, codec::Q / 4];
    let (identity, owner) =
        source::completed(root.path(), &bundle, &run, &source::observation(input)).await?;
    let publication = owner.read_run_publication(&identity, &run)?;
    append_decision(&mut writer, decision(&publication)?)?;
    append_outcome(&mut writer, outcome(&publication, /*value*/ 1 << 32));
    let ledger_snapshot = writer.read_current_durable_snapshot()?;
    let LedgerEvent::AuthenticatedDecisionV2(original_decision) =
        &ledger_snapshot.records()[0].event
    else {
        anyhow::bail!("original authenticated Decision");
    };
    assert_eq!(
        original_decision.run_snapshot_digest,
        publication.input().ndu_snapshot_digest
    );
    let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
    let (plan, signed) = freeze(&writer, &initial, rule())?;
    let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
    let readback = owner.readback();
    let read = |writer: &mut LedgerWriter| {
        CellQ24DatasetReaderV1::new(&readback, &identity, writer).read_current_with_clock(
            &initial,
            &baseline,
            rule(),
            plan.clone(),
            &signed,
            || Ok(50),
        )
    };
    let material = read(&mut writer)?;
    let repeated = read(&mut writer)?;
    let expected = CellQ24TrainingBatchV1::new(
        material.receipt().snapshot.dataset_digest,
        vec![CellQ24TrainingSampleV1 {
            input: input.to_vec(),
            target: codec::Q,
        }],
    )?;
    assert_eq!(material.batch().encoded(), expected.encoded());
    assert_eq!(material.batch().encoded(), repeated.batch().encoded());
    assert_eq!(material.receipt(), repeated.receipt());
    assert_eq!(material.provenance_digest(), repeated.provenance_digest());
    assert_eq!(
        material.experience_observation(),
        repeated.experience_observation()
    );
    assert_eq!(
        material.dataset_observation(),
        repeated.dataset_observation()
    );
    assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
    assert_eq!(owner.read_run_publication(&identity, &run)?, publication);
    owner.withdraw_source(&run)?;
    assert!(read(&mut writer).is_err());
    assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
    Ok(())
}

#[tokio::test]
async fn source_identity_signed_freeze_and_ledger_domain_cannot_be_rebound() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (baseline, bundle) = source::model(root.path())?;
    let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
    let mut writer = fixture.writer;
    let identity = identity(root.path())?;
    let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
    let (identity, owner) = source::completed(
        root.path(),
        &bundle,
        &run,
        &source::observation([codec::Q / 2, 0]),
    )
    .await?;
    let publication = owner.read_run_publication(&identity, &run)?;
    append_decision(&mut writer, decision(&publication)?)?;
    append_outcome(&mut writer, outcome(&publication, /*value*/ 1 << 32));
    let original = initial(&publication, &bundle, writer.verifier().trust_digest())?;
    let (plan, signed) = freeze(&writer, &original, rule())?;
    let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
    let readback = owner.readback();
    for change in ["principal", "agent", "cell", "run", "receipt"] {
        let mut request = original.request.clone();
        match change {
            "principal" => request.principal_id = id("other-principal"),
            "agent" => request.agent_id = id("other-agent"),
            "cell" => request.cell_id = id("other-cell"),
            "run" => request.source_run_id = id("other-run"),
            "receipt" => request.completed_task_receipt = d("other-receipt"),
            _ => unreachable!(),
        }
        let changed = LearningIterationCoordinatorV1::new(request, original.owners.clone())?
            .snapshot()
            .clone();
        // A newly fixture-signed cut still cannot rebind the original source.
        let (changed_plan, changed_signed) = freeze(&writer, &changed, rule())?;
        assert!(
            CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
                .read_current_with_clock(
                    &changed,
                    &baseline,
                    rule(),
                    changed_plan,
                    &changed_signed,
                    || Ok(50)
                )
                .is_err()
        );
    }
    let changed_rule = CellQ24DatasetRuleV1 {
        head: CellQ24PrivateHeadV1::Drive { index: 0 },
        ..rule()
    };
    let mut changed_plan = plan.clone();
    changed_plan.inclusion_policy_digest = changed_rule.inclusion_policy_digest(&original)?;
    assert!(
        CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
            .read_current_with_clock(
                &original,
                &baseline,
                changed_rule,
                changed_plan,
                &signed,
                || Ok(50)
            )
            .is_err()
    );

    // Same agent, episode, signer trust and byte-identical facts under another
    // ledger domain must not import the already executed original task.
    let other_fixture = ledger::LedgerFixture::new("different-ledger-domain");
    let mut other = other_fixture.writer;
    assert_ne!(
        circuit_learning_run_id_v1(&other, &identity.agent_id, &id("episode"))?,
        run
    );
    append_decision(&mut other, decision(&publication)?)?;
    append_outcome(&mut other, outcome(&publication, /*value*/ 1 << 32));
    let (other_plan, other_signed) = freeze(&other, &original, rule())?;
    assert!(matches!(
        CellQ24DatasetReaderV1::new(&readback, &identity, &mut other).read_current_with_clock(
            &original,
            &baseline,
            rule(),
            other_plan,
            &other_signed,
            || Ok(50)
        ),
        Err(CellQ24DatasetErrorV1::Binding(
            "original ledger-bound execution identity"
        ))
    ));
    assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);

    // Original evidence covers the exact current source set. A real correction
    // cannot silently reuse the earlier freeze signature or its label.
    let mut correction = outcome(&publication, /*value*/ 2 << 32);
    correction.record_id = id("correction-record");
    correction.outcome_id = id("corrected-outcome");
    correction.watermark.correction_predecessor = Some(id("outcome"));
    append_outcome(&mut writer, correction);
    let corrected = writer.qualification_file_bytes(8 * 1024 * 1024)?;
    assert!(
        CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
            .read_current_with_clock(&original, &baseline, rule(), plan, &signed, || Ok(50))
            .is_err()
    );
    assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, corrected);
    Ok(())
}

#[tokio::test]
async fn nonterminal_nonrepresentable_and_out_of_range_targets_are_never_clipped_or_filled()
-> anyhow::Result<()> {
    for change in [
        "pending",
        "censored",
        "nonrepresentable",
        "outside",
        "wrong-unit",
    ] {
        let root = tempfile::tempdir()?;
        let (baseline, bundle) = source::model(root.path())?;
        let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
        let mut writer = fixture.writer;
        let identity = identity(root.path())?;
        let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
        let (identity, owner) = source::completed(
            root.path(),
            &bundle,
            &run,
            &source::observation([codec::Q / 2, 0]),
        )
        .await?;
        let publication = owner.read_run_publication(&identity, &run)?;
        let raw = match change {
            "nonrepresentable" => (1_i64 << 32) + 1,
            "outside" => 9_i64 << 32,
            _ => 1_i64 << 32,
        };
        append_decision(&mut writer, decision(&publication)?)?;
        let mut outcome = outcome(&publication, raw);
        if change == "pending" || change == "censored" {
            outcome.value = None;
            outcome.observed_at = None;
            outcome.watermark.terminality = if change == "pending" {
                outcome.watermark.finalized_at = None;
                OutcomeTerminalityV1::Pending
            } else {
                outcome.watermark.censoring_reason = Some(id("censored-by-fixture"));
                OutcomeTerminalityV1::Censored
            };
        }
        if change == "wrong-unit" {
            outcome.unit_profile_digest = d("different-unit");
        }
        append_outcome(&mut writer, outcome);
        let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
        let (plan, signed) = freeze(&writer, &initial, rule())?;
        let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
        let readback = owner.readback();
        assert!(
            CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
                .read_current_with_clock(&initial, &baseline, rule(), plan, &signed, || Ok(50))
                .is_err(),
            "{change}"
        );
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
    }
    Ok(())
}

#[tokio::test]
async fn current_uses_internal_time_and_rechecks_expiry_after_physical_reads() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    let (baseline, bundle) = source::model(root.path())?;
    let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
    let mut writer = fixture.writer;
    let identity = identity(root.path())?;
    let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
    let (identity, owner) = source::completed(
        root.path(),
        &bundle,
        &run,
        &source::observation([codec::Q / 2, 0]),
    )
    .await?;
    let publication = owner.read_run_publication(&identity, &run)?;
    append_decision(&mut writer, decision(&publication)?)?;
    append_outcome(&mut writer, outcome(&publication, /*value*/ 1 << 32));
    let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
    let (plan, signed) = freeze(&writer, &initial, rule())?;
    let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
    let readback = owner.readback();

    // Existing fixture freeze evidence expires at 90, and its request at 100.
    // The public method has no old timestamp argument with which to revive it.
    assert!(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() >= 100);
    assert!(matches!(
        CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer).read_current(
            &initial,
            &baseline,
            rule(),
            plan.clone(),
            &signed
        ),
        Err(CellQ24DatasetErrorV1::Binding("learning request expired"))
    ));

    for finished_at in [49, 91, 100] {
        let mut times = [50, finished_at].into_iter();
        let result = CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
            .read_current_with_clock(&initial, &baseline, rule(), plan.clone(), &signed, || {
                Ok(times
                    .next()
                    .expect("initial and post-read clock observations"))
            });
        // Reaching the second clock means all real source/ledger reads and
        // their signatures passed at admission. Their elapsed time still
        // cannot produce material after expiry or a backwards clock.
        assert_eq!(times.next(), None);
        match finished_at {
            49 => assert!(matches!(
                result,
                Err(CellQ24DatasetErrorV1::Binding(
                    "system clock moved backwards"
                ))
            )),
            91 => assert!(matches!(result, Err(CellQ24DatasetErrorV1::Ledger(_)))),
            100 => assert!(matches!(
                result,
                Err(CellQ24DatasetErrorV1::Binding(
                    "learning request expired during materialization"
                ))
            )),
            _ => unreachable!(),
        }
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
    }
    Ok(())
}
