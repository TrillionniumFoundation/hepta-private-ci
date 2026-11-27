//! Three explicit organizations of the same bounded single-effect task.
//! This is conformance coverage, not a performance or generalization ranking.

use std::path::Path;

use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use serde::Serialize;

use super::destination::Desired;
use super::destination::open_observation_pool;
use super::harness::Harness;
use super::harness::key;
use super::observer::Driver;

const LOOKUP_BUDGET: usize = 2;

#[derive(Clone, Copy, Debug)]
pub enum Baseline {
    DurableWorkflow,
    HandwrittenDsl,
    FlatSkills,
}

pub const BASELINES: [Baseline; 3] = [
    Baseline::DurableWorkflow,
    Baseline::HandwrittenDsl,
    Baseline::FlatSkills,
];

#[derive(Debug, Default)]
pub struct Outcome {
    pub reported_success: bool,
    pub lookup_calls: usize,
}

fn success(receipt: &TaskFlowStepReceipt) -> bool {
    receipt.observation == Some(TaskFlowStepObservation::Succeeded)
        || receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded)
}

impl Baseline {
    pub fn name(self) -> &'static str {
        match self {
            Self::DurableWorkflow => "deterministic_durable_workflow",
            Self::HandwrittenDsl => "handwritten_dsl_macro",
            Self::FlatSkills => "flat_skill_library",
        }
    }

    pub async fn run(self, harness: &Harness, driver: &mut Driver) -> Outcome {
        let receipt = harness
            .dispatch(driver)
            .await
            .expect("authorized first dispatch");
        if success(&receipt) {
            return Outcome {
                reported_success: true,
                lookup_calls: 0,
            };
        }
        self.resume(harness, driver).await
    }

    pub async fn resume(self, harness: &Harness, driver: &mut Driver) -> Outcome {
        let pending = harness.pending().await;
        let mut outcome = Outcome::default();
        match self {
            Self::DurableWorkflow => {
                // Explicit durable-workflow states. Recovery always loads the
                // owner's pending identity; it has no dispatch transition.
                enum State {
                    Reconcile,
                    Verify,
                    Stop,
                }
                let mut state = State::Reconcile;
                let mut receipt = None;
                loop {
                    state = match state {
                        State::Reconcile => {
                            if outcome.lookup_calls == LOOKUP_BUDGET {
                                State::Stop
                            } else {
                                outcome.lookup_calls += 1;
                                receipt = harness
                                    .recover(driver.lookup(&pending, &harness.wire).await)
                                    .await;
                                State::Verify
                            }
                        }
                        State::Verify => {
                            outcome.reported_success = receipt.as_ref().is_some_and(success);
                            if outcome.reported_success {
                                State::Stop
                            } else {
                                State::Reconcile
                            }
                        }
                        State::Stop => break,
                    };
                }
            }
            Self::HandwrittenDsl => {
                // The macro is parsed and interpreted, not renamed workflow
                // states. Each opcode uses the same driver and effect owner.
                let macro_source = "lookup\nassert_goal\nlookup\nassert_goal\nhalt";
                let mut receipt = None;
                for opcode in macro_source.lines() {
                    match opcode {
                        "lookup" => {
                            assert!(outcome.lookup_calls < LOOKUP_BUDGET);
                            outcome.lookup_calls += 1;
                            receipt = harness
                                .recover(driver.lookup(&pending, &harness.wire).await)
                                .await;
                        }
                        "assert_goal" => {
                            outcome.reported_success = receipt.as_ref().is_some_and(success);
                            if outcome.reported_success {
                                break;
                            }
                        }
                        "halt" => break,
                        _ => panic!("invalid hand-authored macro opcode"),
                    }
                }
            }
            Self::FlatSkills => {
                // No parent option or macro: a flat list of bounded primitive
                // verification skills is selected by its returned observation.
                for _ in 0..LOOKUP_BUDGET {
                    outcome.lookup_calls += 1;
                    match driver.lookup(&pending, &harness.wire).await {
                        AuthorizedProviderEffectLookup::Observed(receipt) => {
                            let recovered = harness
                                .recover(AuthorizedProviderEffectLookup::Observed(receipt))
                                .await;
                            outcome.reported_success = recovered.as_ref().is_some_and(success);
                            if outcome.reported_success {
                                break;
                            }
                        }
                        AuthorizedProviderEffectLookup::ProvenAbsent { .. }
                        | AuthorizedProviderEffectLookup::Unresolved => {}
                    }
                }
            }
        }
        outcome
    }
}

#[derive(Debug, Serialize)]
pub struct Oracle {
    pub actual_business_success: bool,
    pub business_events: usize,
    pub duplicate_effects: usize,
    pub dispatch_contacts: i64,
    pub lookup_contacts: i64,
}

pub async fn oracle(root: &Path) -> Oracle {
    // Separate connection and query path. This oracle never reads the
    // provider ACK, execution phase, goal observer, or injected fault plan.
    let pool = open_observation_pool(&root.join("destination.sqlite3")).await;
    let rows: Vec<String> = sqlx::query_scalar(
        "SELECT value FROM business_events WHERE effect_key = ? ORDER BY ordinal, event_id",
    )
    .bind(key().as_str())
    .fetch_all(&pool)
    .await
    .expect("independent oracle rows");
    let duplicates: i64 = sqlx::query_scalar(
        "SELECT COALESCE(SUM(n - 1), 0) FROM
            (SELECT COUNT(*) n FROM business_events GROUP BY effect_key, ordinal)",
    )
    .fetch_one(&pool)
    .await
    .expect("independent duplicate count");
    let dispatch_contacts =
        sqlx::query_scalar("SELECT COUNT(*) FROM contacts WHERE kind = 'dispatch'")
            .fetch_one(&pool)
            .await
            .expect("actual dispatch contacts");
    let lookup_contacts = sqlx::query_scalar("SELECT COUNT(*) FROM contacts WHERE kind = 'lookup'")
        .fetch_one(&pool)
        .await
        .expect("actual recovery contacts");
    pool.close().await;
    Oracle {
        actual_business_success: rows == Desired::standard().rows,
        business_events: rows.len(),
        duplicate_effects: usize::try_from(duplicates).expect("nonnegative duplicates"),
        dispatch_contacts,
        lookup_contacts,
    }
}

pub fn metric(baseline: Baseline, scenario: &str, outcome: &Outcome, truth: &Oracle) {
    assert!(
        !outcome.reported_success || truth.actual_business_success,
        "false business success"
    );
    assert_eq!(truth.duplicate_effects, 0);
    assert_eq!(truth.dispatch_contacts, 1);
    assert!(outcome.lookup_calls <= LOOKUP_BUDGET);
    assert_eq!(
        truth.lookup_contacts,
        i64::try_from(outcome.lookup_calls).expect("bounded lookup count")
    );
    eprintln!(
        "ACT1_METRIC {}",
        serde_json::json!({
            "baseline":baseline.name(), "scenario":scenario,
            "evaluation":"single_effect_conformance", "oracle":truth,
            "reported_success":outcome.reported_success,
            "false_success":outcome.reported_success && !truth.actual_business_success,
            "unknown_retained":!outcome.reported_success,
            "recovery_queries":outcome.lookup_calls,
            "dispatch_budget":1, "lookup_budget":LOOKUP_BUDGET,
        })
    );
}
