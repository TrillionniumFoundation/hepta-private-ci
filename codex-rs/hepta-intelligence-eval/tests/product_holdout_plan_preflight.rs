//! Real product runner and locked-file holdout ordering, without model-gain claims.
//! The provider records contact and deliberately refuses release; no external
//! task custody, operator independence or model installation is fabricated.

use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

static NEXT: AtomicU64 = AtomicU64::new(0);
type TestResult = Result<(), Box<dyn Error>>;
type Runner = ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Journal {
    path: PathBuf,
    fence: HoldoutWriterFenceV1,
    initial: FinalHoldoutCasAnchorV1,
    initial_bytes: Vec<u8>,
}

impl Journal {
    fn create() -> Result<Self, Box<dyn Error>> {
        let path = std::env::temp_dir().join(format!(
            "hepta-product-plan-preflight-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)?;
        let fence = HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 1,
            lease_digest: digest("authorized-local-lease"),
        };
        let store = LockedFileFinalHoldoutCasStoreV1::create(file, digest("binding"))?;
        let owner =
            FencedFinalHoldoutOwnerV1::initialize(store, digest("binding"), fence.clone())?;
        let initial = owner.anchor();
        // Drop the lock before independent byte readback, also on Windows.
        drop(owner);
        let initial_bytes = fs::read(&path)?;
        Ok(Self {
            path,
            fence,
            initial,
            initial_bytes,
        })
    }

    fn reopen(&self, minimum: FinalHoldoutCasAnchorV1) -> Result<Runner, Box<dyn Error>> {
        let file = OpenOptions::new().read(true).write(true).open(&self.path)?;
        let store =
            LockedFileFinalHoldoutCasStoreV1::recover(file, digest("binding"), Some(minimum))?;
        let owner =
            FencedFinalHoldoutOwnerV1::recover(store, digest("binding"), self.fence.clone())?;
        Ok(ProductEvaluationRunnerV1::new(owner))
    }
}

impl Drop for Journal {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

#[derive(Default)]
struct ReleaseProbe {
    manifests: usize,
    releases: usize,
}

impl FinalHoldoutProviderV1 for ReleaseProbe {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.manifests += 1;
        Ok(digest("final-holdout"))
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        assert!(receipt.sequence > 0);
        self.releases += 1;
        Err(ProductProviderErrorV1::Rejected)
    }
}

fn temporal(name: &str) -> Result<TemporalEvaluationPlan, Box<dyn Error>> {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: digest("objective"),
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope-plan")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest()?;
    Ok(plan)
}

fn freeze(
    candidate: &TemporalEvaluationPlan,
    baseline: &TemporalEvaluationPlan,
) -> Result<ProductFrozenEvaluationPlanV1, Box<dyn Error>> {
    let mut folds = Vec::new();
    for (name, window) in [("a", "final-window"), ("b", "other-window")] {
        folds.push(CrossFoldPartitionV1 {
            fold_id: id(&format!("fold-{name}")),
            training_principals: vec![id(&format!("train-principal-{name}"))],
            training_episodes: vec![id(&format!("train-episode-{name}"))],
            training_windows: vec![id(&format!("past-{name}"))],
            holdout_principals: vec![id(&format!("holdout-principal-{name}"))],
            holdout_episodes: vec![id(&format!("holdout-episode-{name}"))],
            holdout_windows: vec![id(window)],
            model_digest: digest(&format!("model-{name}")),
            predictions_digest: digest(&format!("predictions-{name}")),
        });
    }
    Ok(freeze_product_evaluation_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("product-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            estimand_digest: digest("task-success-estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("task-success"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::ZERO),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds,
            final_holdout_window_id: id("final-window"),
            final_holdout_digest: digest("final-holdout"),
        },
        vec![MetricRoleContractV2 {
            metric_id: id("task-success"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
        vec![ProductMetricSourceContractV1 {
            metric_id: id("task-success"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
        candidate,
        baseline,
    )?)
}

// Mutate every canonical execution field not already checked by the original
// objective/claimed-digest comparisons. Keep the old declared digest in place.
const MUTATIONS: &[fn(&mut TemporalEvaluationPlan)] = &[
    |p| p.evaluation_id = id("substituted-evaluation"),
    |p| p.fold.plan_digest = digest("substituted-fold"),
    |p| p.fold.fold_id = id("substituted-fold"),
    |p| p.fold.training_watermark += 1,
    |p| p.fold.evaluation_start += 1,
    |p| p.fold.minimum_per_action += 1,
    |p| p.ope.plan_digest = digest("substituted-ope"),
    |p| p.ope.outcome_watermark += 1,
    |p| p.ope.minimum_rows += 1,
    |p| p.ope.minimum_ess = FixedQ32::ZERO,
    |p| p.ope.maximum_weight = FixedQ32::ONE,
    |p| p.confidence.plan_digest = digest("substituted-confidence"),
    |p| p.confidence.assumptions_digest = digest("substituted-assumptions"),
    |p| p.confidence.family_alpha_ppm += 1,
    |p| p.confidence.simultaneous_comparisons += 1,
    |p| p.confidence.minimum_clusters += 1,
];

#[derive(Clone, Copy, Debug)]
enum Side {
    Candidate,
    Baseline,
}

fn changed_plan_is_rejected_before_contact(side: Side) -> TestResult {
    let candidate = temporal("candidate-evaluation")?;
    let baseline = temporal("baseline-evaluation")?;
    let frozen = freeze(&candidate, &baseline)?;
    let journal = Journal::create()?;
    let mut runner = journal.reopen(journal.initial)?;
    let mut provider = ReleaseProbe::default();
    for (index, mutate) in MUTATIONS.iter().enumerate() {
        let mut candidate_input = candidate.clone();
        let mut baseline_input = baseline.clone();
        let changed = match side {
            Side::Candidate => &mut candidate_input,
            Side::Baseline => &mut baseline_input,
        };
        mutate(changed);
        assert_ne!(changed.plan_digest, changed.canonical_digest()?);
        let error = runner
            .evaluate_temporal_comparison(
                &frozen,
                &candidate_input,
                &baseline_input,
                &mut provider,
            )
            .err();
        assert!(
            matches!(
                error.as_ref(),
                Some(ProductEvaluationError::Binding("temporal execution plan"))
            ),
            "{side:?} mutation {index} must be refused before consuming the window: {error:?}"
        );
        assert_eq!((provider.manifests, provider.releases), (0, 0));
        assert_eq!(runner.holdout_anchor(), journal.initial);
        assert_eq!(runner.holdout_state_digest(), journal.initial.state_digest);
    }
    drop(runner);
    assert_eq!(fs::read(&journal.path)?, journal.initial_bytes);
    let reopened = journal.reopen(journal.initial)?;
    assert_eq!(reopened.holdout_anchor(), journal.initial);
    Ok(())
}

#[test]
fn changed_candidate_plan_cannot_contact_or_consume_holdout() -> TestResult {
    changed_plan_is_rejected_before_contact(Side::Candidate)
}

#[test]
fn changed_baseline_plan_cannot_contact_or_consume_holdout() -> TestResult {
    changed_plan_is_rejected_before_contact(Side::Baseline)
}

#[test]
fn rehashing_changed_plan_does_not_replace_frozen_preregistration() -> TestResult {
    let candidate = temporal("candidate-evaluation")?;
    let baseline = temporal("baseline-evaluation")?;
    let frozen = freeze(&candidate, &baseline)?;
    let journal = Journal::create()?;
    let mut runner = journal.reopen(journal.initial)?;
    let mut provider = ReleaseProbe::default();
    for side in [Side::Candidate, Side::Baseline] {
        let mut candidate_input = candidate.clone();
        let mut baseline_input = baseline.clone();
        let changed = match side {
            Side::Candidate => &mut candidate_input,
            Side::Baseline => &mut baseline_input,
        };
        changed.fold.evaluation_start += 1;
        changed.plan_digest = changed.canonical_digest()?;
        let error = runner
            .evaluate_temporal_comparison(
                &frozen,
                &candidate_input,
                &baseline_input,
                &mut provider,
            )
            .err();
        assert!(matches!(
            error,
            Some(ProductEvaluationError::Binding("temporal execution plan"))
        ));
        assert_eq!((provider.manifests, provider.releases), (0, 0));
        assert_eq!(runner.holdout_anchor(), journal.initial);
    }
    drop(runner);
    assert_eq!(fs::read(&journal.path)?, journal.initial_bytes);
    Ok(())
}

#[test]
fn valid_plan_consumes_before_release_and_provider_failure_survives_reopen() -> TestResult {
    let candidate = temporal("candidate-evaluation")?;
    let baseline = temporal("baseline-evaluation")?;
    let frozen = freeze(&candidate, &baseline)?;
    let journal = Journal::create()?;
    let mut runner = journal.reopen(journal.initial)?;
    let mut provider = ReleaseProbe::default();
    let error = runner
        .evaluate_temporal_comparison(&frozen, &candidate, &baseline, &mut provider)
        .err();
    assert!(matches!(
        error,
        Some(ProductEvaluationError::Provider(
            ProductProviderErrorV1::Rejected
        ))
    ));
    assert_eq!((provider.manifests, provider.releases), (1, 1));
    let consumed = runner.holdout_anchor();
    assert_eq!(consumed.record_count, journal.initial.record_count + 1);
    assert_ne!(consumed.state_digest, journal.initial.state_digest);
    drop(runner);
    let consumed_bytes = fs::read(&journal.path)?;
    assert_ne!(consumed_bytes, journal.initial_bytes);
    let mut reopened = journal.reopen(consumed)?;
    assert_eq!(reopened.holdout_anchor(), consumed);
    let error = reopened
        .evaluate_temporal_comparison(&frozen, &candidate, &baseline, &mut provider)
        .err();
    assert!(matches!(error, Some(ProductEvaluationError::Holdout(_))));
    assert_eq!((provider.manifests, provider.releases), (2, 1));
    assert_eq!(reopened.holdout_anchor(), consumed);
    drop(reopened);
    assert_eq!(fs::read(&journal.path)?, consumed_bytes);
    Ok(())
}
