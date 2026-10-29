//! Frozen task contract and actual label-free nuisance predictions.
use super::*;
use pretty_assertions::assert_eq;

pub(super) fn binary_tasks(
    seed: &[u8; 32],
    yes: &StableId,
    actions: &[StableId; 2],
) -> TestResult<Value> {
    let raw = include_bytes!("../fixtures/smollm-consumed-prompts-067-v2.json");
    if Digest32::of_bytes(raw).to_string()
        != "d2101f954f9b025d5fe0a87b73ae2d31f20eb6f989ed279a04ffe38d0932b06d"
    {
        return Err("frozen previous prompt exclusion changed".into());
    }
    let previous: Value = serde_json::from_slice(raw)?;
    let excluded = previous["excluded_prompt_sha256"]
        .as_array()
        .ok_or("prior prompt identities")?
        .iter()
        .map(|value| value.as_str().ok_or("prior prompt digest"))
        .collect::<Result<std::collections::BTreeSet<_>, _>>()?;
    if excluded.len() != 1024 {
        return Err("all previously consumed prompts required".into());
    }
    let no = actions
        .iter()
        .find(|value| *value != yes)
        .ok_or("no action")?;
    let mut used = std::collections::BTreeSet::new();
    let mut windows = Vec::new();
    for window in 0_u64..2 {
        let mut rows = Vec::new();
        for index in 0_u64..512 {
            let hash = Digest32::of_parts(&[
                b"hepta.neural.study.binary.two-families.v2\0",
                seed,
                &window.to_be_bytes(),
                &index.to_be_bytes(),
            ]);
            let bytes = hash.as_array();
            let mut number = 100 + u64::from_be_bytes(bytes[..8].try_into()?) % 9_899;
            let expected = if index.is_multiple_of(2) { no } else { yes };
            let mut selected = None;
            for _ in 0..9_899 {
                let (family, prompt) = if index < 256 {
                    let (left, right) = if expected == yes {
                        (number + 1, number)
                    } else {
                        (number, number + 1)
                    };
                    (
                        "integer-comparison",
                        format!("Answer with only yes or no. Is {left} greater than {right}?"),
                    )
                } else {
                    let words = if expected == yes {
                        ["Alpha", "Gamma"]
                    } else {
                        ["beta", "delta"]
                    };
                    let word = words[usize::from(bytes[8] & 1)];
                    (
                        "uppercase",
                        format!(
                            "Answer with only yes or no. Does the first character of {word} use uppercase? Item {number}."
                        ),
                    )
                };
                let digest = Digest32::of_bytes(prompt.as_bytes()).to_string();
                if !used.contains(&number) && !excluded.contains(digest.as_str()) {
                    used.insert(number);
                    selected = Some((family, prompt));
                    break;
                }
                number = 100 + (number - 99) % 9_899;
            }
            let (family, prompt) = selected.ok_or("unseen original task support exhausted")?;
            rows.push(json!({"id":format!("future-{window}-{index}"),"family":family,"prompt":prompt,
                "expected":expected.as_str(),"principal":format!("future-sample-{window}-{index}"),
                "episode":format!("future-episode-{window}-{index}"),"cluster":format!("future-cluster-{window}-{index}")}));
        }
        windows.push(rows);
    }
    Ok(json!(windows))
}

#[test]
fn binary_future_cohort_excludes_consumed_prompts_without_changing_original_family_counts()
-> TestResult<()> {
    let yes = id("yes");
    let actions = [yes.clone(), id("no")];
    let tasks = binary_tasks(&[7; 32], &yes, &actions)?;
    let previous: Value = serde_json::from_slice(include_bytes!(
        "../fixtures/smollm-consumed-prompts-067-v2.json"
    ))?;
    let mut all = std::collections::BTreeSet::new();
    for window in tasks.as_array().ok_or("windows")? {
        let rows = window.as_array().ok_or("window rows")?;
        assert_eq!(rows.len(), 512);
        for family in ["integer-comparison", "uppercase"] {
            for expected in &actions {
                assert_eq!(
                    rows.iter()
                        .filter(
                            |row| row["family"] == family && row["expected"] == expected.as_str()
                        )
                        .count(),
                    128
                );
            }
        }
        for row in rows {
            let hash =
                Digest32::of_bytes(row["prompt"].as_str().ok_or("prompt")?.as_bytes()).to_string();
            assert!(all.insert(hash.clone()));
            assert!(
                !previous["excluded_prompt_sha256"]
                    .as_array()
                    .ok_or("prior prompts")?
                    .iter()
                    .any(|item| item == &json!(hash))
            );
        }
    }
    assert_eq!(all.len(), 1024);
    Ok(())
}

pub(super) fn tasks(seed: &[u8; 32], yes: &StableId, actions: &[StableId; 2]) -> Value {
    let no = actions.iter().find(|value| *value != yes).unwrap();
    let mut used = std::collections::BTreeSet::new();
    let windows = (0_u64..2).map(|window| {
        (0_u64..512).map(|index| {
            let hash = Digest32::of_parts(&[b"hepta.neural.study.two-families.v1\0", seed,
                &window.to_be_bytes(), &index.to_be_bytes()]);
            let bytes = hash.as_array();
            let mut number = 100 + u64::from_be_bytes(bytes[..8].try_into().unwrap()) % 9_899;
            while !used.insert(number) { number = 100 + (number - 99) % 9_899; }
            let expected = if index.is_multiple_of(2) { no } else { yes };
            let (family, prompt) = if index < 256 {
                let (left, right) = if expected == yes { (number + 1, number) } else { (number, number + 1) };
                ("integer-comparison",format!("Answer with only yes or no. Is {left} greater than {right}?"))
            } else {
                let words = if expected == yes { ["Alpha","Gamma"] } else { ["beta","delta"] };
                let word = words[usize::from(bytes[8]&1)];
                ("uppercase",format!("Answer with only yes or no. Does the first character of {word} use uppercase? Item {number}."))
            };
            json!({"id":format!("future-{window}-{index}"),"family":family,"prompt":prompt,
                "expected":expected.as_str(),"principal":format!("future-sample-{window}-{index}"),
                "episode":format!("future-episode-{window}-{index}"),"cluster":format!("future-cluster-{window}-{index}")})
        }).collect::<Vec<_>>()
    }).collect::<Vec<_>>();
    json!(windows)
}

pub(super) struct Prepared {
    pub raw: eval::CrossFoldPlanV1,
    pub product: eval::ProductFrozenEvaluationPlanV1,
    pub candidate: eval::TemporalEvaluationPlan,
    pub baseline: eval::TemporalEvaluationPlan,
    pub targets: Vec<eval::HeldOutTarget>,
    pub predictions: Value,
    pub candidate_predictions: Digest32,
    pub baseline_predictions: Digest32,
}

pub(super) fn plans(
    profile: StudyProfile,
    dataset: &ledger::DatasetSnapshotReceiptV3,
    snapshot: &ledger::LedgerSnapshot,
    material: Digest32,
    tasks: &Value,
    actions: &[StableId; 2],
) -> TestResult<Prepared> {
    let training = training(profile, dataset, snapshot)?;
    // These are real preassignment/prediction times, recorded now. They never
    // represent the future neural query clock, which the Provider records later.
    let prediction_start = now();
    let temporal = |name: &str| -> TestResult<eval::TemporalEvaluationPlan> {
        let mut plan = eval::TemporalEvaluationPlan {
            plan_digest: Digest32::ZERO,
            evaluation_id: id(name),
            objective_digest: dataset.snapshot.objective_digest,
            fold: eval::TemporalFoldPlan {
                plan_digest: digest(&format!("{name}-fold")),
                fold_id: id(name),
                training_watermark: dataset.snapshot.outcome_watermark,
                evaluation_start: prediction_start,
                minimum_per_action: 4,
            },
            ope: eval::OpePlan {
                plan_digest: digest(&format!("{name}-ips")),
                outcome_watermark: prediction_start + 2_700_000_000,
                minimum_rows: 512,
                minimum_ess: FixedQ32::ONE,
                maximum_weight: FixedQ32::from_raw(/*raw*/ 2_i64 << 32),
            },
            confidence: eval::ClusterConfidencePlan {
                plan_digest: digest(&format!("{name}-confidence")),
                assumptions_digest: digest(
                    "predeclared distinct two-family task units; controlled test sampling",
                ),
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                minimum_clusters: 512,
            },
        };
        plan.plan_digest = plan.canonical_digest()?;
        Ok(plan)
    };
    let candidate = temporal("neural-study-candidate")?;
    let baseline = temporal("neural-study-parent")?;
    let mut targets = Vec::new();
    let mut folds = Vec::new();
    let mut predictions = Vec::new();
    for window in 0..2 {
        let rows = tasks[window]
            .as_array()
            .ok_or("complete future task window")?;
        let local = rows
            .iter()
            .map(|row| -> TestResult<eval::HeldOutTarget> {
                Ok(eval::HeldOutTarget {
                    decision_id: id(row["id"].as_str().ok_or("task id")?),
                    principal_lineage: id(row["principal"].as_str().ok_or("task principal")?),
                    episode_lineage: id(row["episode"].as_str().ok_or("task episode")?),
                    window_id: id(&format!("future-window-{window}")),
                    decision_at: now(),
                    actions: actions.to_vec(),
                })
            })
            .collect::<TestResult<Vec<_>>>()?;
        let fitted = eval::fit_temporal_fold(&candidate.fold, &training, &local)?;
        if fitted.authority.grants_any() {
            return Err("nuisance fitter cannot grant authority".into());
        }
        predictions.push(json!({"window":window,"model_digest":fitted.model_digest.to_string(),
            "predictions_digest":fitted.predictions_digest.to_string(),
            "predictions":fitted.predictions.iter().map(|prediction| json!({
                "decision_id":prediction.decision_id.as_str(),"outcomes":prediction.outcomes.iter()
                    .map(|(action,value)|json!({"action_id":action.as_str(),"q32":value.raw()})).collect::<Vec<_>>()
            })).collect::<Vec<_>>() }));
        folds.push(eval::CrossFoldPartitionV1 {
            fold_id: id(&format!("future-fold-{window}")),
            training_principals: vec![id("controlled-neural-role-0")],
            training_episodes: training
                .iter()
                .map(|row| row.episode_lineage.clone())
                .collect(),
            training_windows: vec![dataset.snapshot.snapshot_id.clone()],
            holdout_principals: local
                .iter()
                .map(|row| row.principal_lineage.clone())
                .collect(),
            holdout_episodes: local
                .iter()
                .map(|row| row.episode_lineage.clone())
                .collect(),
            holdout_windows: vec![id(&format!("future-window-{window}"))],
            // Both fields come from the actual unchanged temporal fitter.
            // Neural parent/child bytes are separately pinned by material.
            model_digest: fitted.model_digest,
            predictions_digest: fitted.predictions_digest,
        });
        targets.extend(local);
    }
    let final_targets = targets
        .iter()
        .filter(|target| target.window_id == id("future-window-1"))
        .cloned()
        .collect::<Vec<_>>();
    let candidate_predictions =
        eval::fit_temporal_fold(&candidate.fold, &training, &final_targets)?.predictions_digest;
    let baseline_predictions =
        eval::fit_temporal_fold(&baseline.fold, &training, &final_targets)?.predictions_digest;
    let raw = eval::CrossFoldPlanV1 {
        plan_id: id("real-neural-two-window-v1"),
        claim_scope: eval::EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: id("real-trained-generation-two"),
        baseline_id: id("selected-initial-zero"),
        objective_digest: dataset.snapshot.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        estimand_digest: digest(
            "original two-family binary correctness IPS; no external efficacy claim",
        ),
        metric_contracts: vec![eval::MetricContractV1 {
            metric_id: id("binary-correctness"),
            direction: eval::EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds,
        final_holdout_window_id: id("future-window-1"),
        final_holdout_digest: material,
    };
    let product = eval::freeze_product_evaluation_plan_v1(
        raw.clone(),
        vec![eval::MetricRoleContractV2 {
            metric_id: id("binary-correctness"),
            role: eval::MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
        vec![eval::ProductMetricSourceContractV1 {
            metric_id: id("binary-correctness"),
            source: eval::ProductMetricSourceV1::Ips,
        }],
        &candidate,
        &baseline,
    )?;
    Ok(Prepared {
        raw,
        product,
        candidate,
        baseline,
        targets,
        predictions: json!(predictions),
        candidate_predictions,
        baseline_predictions,
    })
}

pub(super) fn training(
    profile: StudyProfile,
    dataset: &ledger::DatasetSnapshotReceiptV3,
    snapshot: &ledger::LedgerSnapshot,
) -> TestResult<Vec<eval::OutcomeTrainingSample>> {
    ledger::verify_dataset_snapshot_receipt_against_ledger_v3(dataset, snapshot, now())?;
    let sources = dataset
        .snapshot
        .source_record_digests
        .iter()
        .collect::<std::collections::BTreeSet<_>>();
    let mut decisions = std::collections::BTreeMap::new();
    for record in snapshot
        .records()
        .iter()
        .filter(|r| sources.contains(&r.event_digest))
    {
        if let ledger::LedgerEvent::AuthenticatedDecisionV2(value) = &record.event
            && (value.objective_digest != dataset.snapshot.objective_digest
                || value.authentication_digest.is_zero()
                || decisions.insert(value.episode_id.clone(), value).is_some())
        {
            return Err("training decision provenance".into());
        }
    }
    let mut result = Vec::new();
    for record in snapshot
        .records()
        .iter()
        .filter(|r| sources.contains(&r.event_digest))
    {
        if let ledger::LedgerEvent::AuthenticatedOutcomeV2(value) = &record.event {
            let decision = decisions
                .get(&value.episode_id)
                .ok_or("training decision missing")?;
            if value.authentication_digest.is_zero()
                || value.correction_predecessor.is_some()
                || value.terminality != ledger::AuthenticatedOutcomeTerminality::Terminal
                || value.value != Some(FixedQ32::ONE)
            {
                return Err("actual supervised ground-truth outcome provenance".into());
            }
            result.push(eval::OutcomeTrainingSample {
                decision_id: decision.record_id.clone(),
                principal_lineage: decision.generator_id.clone(),
                episode_lineage: value.episode_id.clone(),
                window_id: dataset.snapshot.snapshot_id.clone(),
                action_id: decision.selected_candidate_id.clone(),
                outcome: value.value.ok_or("pending outcome")?,
                observed_at: value.observed_at.ok_or("pending clock")?,
                evidence_digest: record.event_digest,
            });
        }
    }
    if result.len() != profile.training_source_rows()
        || sources.len() != 2 * profile.training_source_rows()
        || result
            .iter()
            .any(|r| r.observed_at > dataset.snapshot.outcome_watermark)
    {
        return Err("exact profile training rows and their authenticated targets required".into());
    }
    Ok(result)
}

#[test]
fn diverse_authenticated_training_rows_require_sixty_rows_and_reject_old_profile() -> TestResult<()>
{
    let root = tempfile::tempdir()?;
    let yes = id("yes");
    let actions = [yes.clone(), id("no")];
    let mut roles = roles::ControlledRoles::new(digest(diverse::OBJECTIVE), actions, yes);
    let rows = diverse::training_rows()?;
    let (dataset, ledger) = roles.dataset(
        StudyProfile::BinaryDiverse60V3,
        &root.path().join("ledger"),
        &rows,
    );
    assert_eq!(dataset.snapshot.source_record_digests.len(), 120);
    assert_eq!(
        training(StudyProfile::BinaryDiverse60V3, &dataset, &ledger)?.len(),
        60
    );
    assert!(training(StudyProfile::BinaryAnswerV2, &dataset, &ledger).is_err());
    assert!(training(StudyProfile::OriginalV1, &dataset, &ledger).is_err());
    let (old, old_ledger) = roles.dataset(
        StudyProfile::BinaryAnswerV2,
        &root.path().join("old-ledger"),
        &rows[..10],
    );
    assert_eq!(
        training(StudyProfile::BinaryAnswerV2, &old, &old_ledger)?.len(),
        10
    );
    assert!(training(StudyProfile::BinaryDiverse60V3, &old, &old_ledger).is_err());
    Ok(())
}
