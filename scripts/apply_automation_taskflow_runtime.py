#!/usr/bin/env python3
"""Apply bounded automation scheduling, recovery budgets and runtime policy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PatchError(RuntimeError):
    pass


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one occurrence, observed {count}")
    return text.replace(old, new, 1)


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def patch_scheduler() -> None:
    path = "codex-rs/hepta-automation/src/scheduler.rs"
    text = read(path)
    anchor = (
        "pub type AutomationFuture<'a, T> =\n"
        "    Pin<Box<dyn Future<Output = Result<T, AutomationError>> + Send + 'a>>;\n"
    )
    addition = anchor + textwrap.dedent(
        """

        /// Hard source bound for one scheduler admission pass. Product hosts may
        /// choose a smaller value; callers cannot request unbounded draining.
        pub const MAX_AUTOMATION_ADMISSION_BATCH: usize = 64;

        #[derive(Clone, Copy, Debug, Eq, PartialEq)]
        pub struct AutomationBatchLimits {
            max_admissions: usize,
        }

        impl AutomationBatchLimits {
            pub fn new(max_admissions: usize) -> Result<Self, AutomationError> {
                if max_admissions == 0 || max_admissions > MAX_AUTOMATION_ADMISSION_BATCH {
                    return Err(AutomationError::Invalid);
                }
                Ok(Self { max_admissions })
            }

            #[must_use]
            pub const fn max_admissions(self) -> usize {
                self.max_admissions
            }
        }

        #[derive(Clone, Debug, Eq, PartialEq)]
        pub struct AutomationBatch {
            pub ticks: Vec<AutomationTick>,
            /// True only when every admitted item consumed the configured source
            /// budget. It is backlog pressure, not proof that more work exists.
            pub budget_exhausted: bool,
        }
        """
    )
    text = replace_once(text, anchor, addition, "scheduler batch types")

    method = textwrap.dedent(
        """

            /// Admit a bounded FIFO batch through the existing single-occurrence
            /// transaction and provider boundary. Calls remain sequential so one
            /// slow/unknown provider cannot create unbounded in-flight work, while
            /// bursts no longer wait for one fixed timer period per occurrence.
            pub async fn tick_batch(
                &self,
                now_ms: u64,
                limits: AutomationBatchLimits,
            ) -> Result<AutomationBatch, AutomationError> {
                let mut ticks = Vec::with_capacity(limits.max_admissions());
                for _ in 0..limits.max_admissions() {
                    let tick = self.tick(now_ms).await?;
                    let admitted = matches!(&tick, AutomationTick::Submitted { .. });
                    ticks.push(tick);
                    if !admitted {
                        return Ok(AutomationBatch {
                            ticks,
                            budget_exhausted: false,
                        });
                    }
                }
                Ok(AutomationBatch {
                    ticks,
                    budget_exhausted: true,
                })
            }
        """
    )
    closing = text.rfind("\n}")
    if closing < 0:
        raise PatchError("scheduler impl closing brace was not found")
    text = text[:closing] + method + text[closing:]
    write(path, text)


def create_failure_policy() -> None:
    write(
        "codex-rs/hepta-automation/src/failure_policy.rs",
        r'''//! Stable failure disposition shared by the scheduler host and qualification.
//!
//! Classification does not grant retry authority. The durable occurrence,
//! provider identity and final-use contracts still decide whether work can be
//! retried; `Reconcile` explicitly forbids blind redispatch.

use crate::AutomationError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationFailureDisposition {
    FailStop,
    Retry,
    Isolate,
    Reconcile,
}

#[must_use]
pub const fn classify_automation_error(
    error: &AutomationError,
) -> AutomationFailureDisposition {
    match error {
        AutomationError::AccessDenied
        | AutomationError::TimerFenced
        | AutomationError::Corrupt => AutomationFailureDisposition::FailStop,
        AutomationError::Unavailable | AutomationError::Dispatch => {
            AutomationFailureDisposition::Retry
        }
        AutomationError::Invalid | AutomationError::Conflict => {
            AutomationFailureDisposition::Isolate
        }
        AutomationError::DispatchUnknown => AutomationFailureDisposition::Reconcile,
    }
}

/// Bounded host retry delay. Attempt 1 starts at 250 ms and the delay caps at
/// four seconds; it never applies to an unknown provider outcome.
#[must_use]
pub const fn bounded_automation_retry_delay_ms(consecutive_attempt: u8) -> u64 {
    match consecutive_attempt {
        0 | 1 => 250,
        2 => 500,
        3 => 1_000,
        4 => 2_000,
        _ => 4_000,
    }
}
''',
    )


def create_runtime_status() -> None:
    write(
        "codex-rs/hepta-automation/src/runtime_status.rs",
        r'''//! Bounded backlog observations for host backpressure and SLO receipts.

use serde::Serialize;

use crate::AutomationError;
use crate::AutomationStore;
use crate::AutomationTaskState;

const BACKLOG_SCAN_LIMIT: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationBacklogSnapshot {
    pub observed_at_ms: u64,
    pub scanned_tasks: usize,
    pub due_tasks: usize,
    pub oldest_due_age_ms: Option<u64>,
    pub pending_occurrences: usize,
    pub uncertain_dispatches: usize,
    pub oldest_uncertain_age_ms: Option<u64>,
    pub scan_truncated: bool,
    pub fairness_order: &'static str,
}

impl AutomationStore {
    /// Observe a bounded backlog without claiming work or contacting a provider.
    /// Equal-time fairness remains the durable owner ordering
    /// `(scheduled_for_ms, task_id, occurrence)`.
    pub async fn backlog_snapshot(
        &self,
        observed_at_ms: u64,
    ) -> Result<AutomationBacklogSnapshot, AutomationError> {
        let tasks = self.list_tasks(BACKLOG_SCAN_LIMIT).await?;
        let pending = self.pending_occurrence_work(BACKLOG_SCAN_LIMIT).await?;
        let uncertain = self.uncertain_dispatches(BACKLOG_SCAN_LIMIT).await?;

        let due_instants = tasks.iter().filter_map(|task| {
            (task.state == AutomationTaskState::Enabled)
                .then_some(task.next_run_at_ms)
                .flatten()
                .filter(|instant| *instant <= observed_at_ms)
        });
        let due_values = due_instants.collect::<Vec<_>>();
        let oldest_due_age_ms = due_values
            .iter()
            .min()
            .map(|instant| observed_at_ms.saturating_sub(*instant));
        let oldest_uncertain_age_ms = uncertain
            .iter()
            .map(|item| item.observed_at_ms)
            .min()
            .map(|instant| observed_at_ms.saturating_sub(instant));

        Ok(AutomationBacklogSnapshot {
            observed_at_ms,
            scanned_tasks: tasks.len(),
            due_tasks: due_values.len(),
            oldest_due_age_ms,
            pending_occurrences: pending.len(),
            uncertain_dispatches: uncertain.len(),
            oldest_uncertain_age_ms,
            scan_truncated: tasks.len() == BACKLOG_SCAN_LIMIT
                || pending.len() == BACKLOG_SCAN_LIMIT
                || uncertain.len() == BACKLOG_SCAN_LIMIT,
            fairness_order: "scheduled_for_ms,task_id,occurrence",
        })
    }
}
''',
    )


def patch_lib() -> None:
    path = "codex-rs/hepta-automation/src/lib.rs"
    text = read(path)
    text = replace_once(
        text,
        "mod effect_dispatch_ledger;\nmod lifecycle;\n",
        "mod effect_dispatch_ledger;\nmod failure_policy;\nmod lifecycle;\n",
        "failure policy module",
    )
    text = replace_once(
        text,
        "mod scheduler;\nmod store;\n",
        "mod runtime_status;\nmod scheduler;\nmod store;\n",
        "runtime status module",
    )
    text = replace_once(
        text,
        "pub use lifecycle::deterministic_occurrence_id;\n",
        "pub use failure_policy::AutomationFailureDisposition;\n"
        "pub use failure_policy::bounded_automation_retry_delay_ms;\n"
        "pub use failure_policy::classify_automation_error;\n"
        "pub use lifecycle::deterministic_occurrence_id;\n",
        "failure policy exports",
    )
    text = replace_once(
        text,
        "pub use scheduler::AutomationFuture;\n",
        "pub use runtime_status::AutomationBacklogSnapshot;\n"
        "pub use scheduler::AutomationBatch;\n"
        "pub use scheduler::AutomationBatchLimits;\n"
        "pub use scheduler::AutomationFuture;\n"
        "pub use scheduler::MAX_AUTOMATION_ADMISSION_BATCH;\n",
        "batch exports",
    )
    write(path, text)


def patch_recovery() -> None:
    path = "codex-rs/hepta-agentd/src/automation_recovery.rs"
    text = read(path)
    marker = "\nasync fn reconcile_one_unknown_dispatch("
    index = text.find(marker)
    if index < 0:
        raise PatchError("automation recovery insertion point was not found")
    addition = textwrap.dedent(
        """

        pub(crate) async fn reconcile_bounded(
            store: &AutomationStore,
            state: &AgentdState,
            identity: &AgentdIdentity,
            now_ms: u64,
            budget: usize,
        ) -> Result<usize, AgentdError> {
            if budget == 0 {
                return Err(AgentdError::Protocol(
                    "automation recovery budget must be non-zero".to_string(),
                ));
            }
            let mut reconciled = 0;
            for _ in 0..budget {
                if !reconcile_one(store, state, identity, now_ms).await? {
                    break;
                }
                reconciled += 1;
            }
            Ok(reconciled)
        }
        """
    )
    text = text[:index] + addition + text[index:]
    write(path, text)


def patch_agentd_scheduler() -> None:
    path = "codex-rs/hepta-agentd/src/automation.rs"
    text = read(path)
    text = replace_once(
        text,
        "use codex_hepta_automation::AutomationAdmission;\n",
        "use codex_hepta_automation::AutomationAdmission;\n"
        "use codex_hepta_automation::AutomationBatchLimits;\n"
        "use codex_hepta_automation::AutomationFailureDisposition;\n",
        "agentd batch imports",
    )
    text = replace_once(
        text,
        "use codex_hepta_automation::AutomationTurnQueue;\n",
        "use codex_hepta_automation::AutomationTurnQueue;\n"
        "use codex_hepta_automation::bounded_automation_retry_delay_ms;\n"
        "use codex_hepta_automation::classify_automation_error;\n",
        "agentd failure imports",
    )
    text = replace_once(
        text,
        "const AUTOMATION_MAX_CONSECUTIVE_DISPATCH_RETRIES: u8 = 3;\n",
        "const AUTOMATION_MAX_CONSECUTIVE_DISPATCH_RETRIES: u8 = 3;\n"
        "const AUTOMATION_MAX_CONSECUTIVE_RUNTIME_RETRIES: u8 = 3;\n"
        "const AUTOMATION_RECOVERY_BUDGET: usize = 4;\n"
        "const AUTOMATION_ADMISSION_BUDGET: usize = 8;\n",
        "agentd runtime budgets",
    )
    text = replace_once(
        text,
        "    let mut retry_budget = DispatchRetryBudget::default();\n    loop {\n",
        "    let batch_limits = AutomationBatchLimits::new(AUTOMATION_ADMISSION_BUDGET)\n"
        "        .map_err(AgentdError::from)?;\n"
        "    let mut retry_budget = DispatchRetryBudget::default();\n"
        "    let mut runtime_error_budget = RuntimeErrorBudget::default();\n"
        "    loop {\n",
        "agentd loop budgets",
    )
    text = replace_once(
        text,
        "        if let Err(error) =\n"
        "            automation_recovery::reconcile_one(scheduler.store(), &state, state.identity(), now_ms)\n"
        "                .await\n"
        "        {\n",
        "        if let Err(error) = automation_recovery::reconcile_bounded(\n"
        "            scheduler.store(),\n"
        "            &state,\n"
        "            state.identity(),\n"
        "            now_ms,\n"
        "            AUTOMATION_RECOVERY_BUDGET,\n"
        "        )\n"
        "        .await\n"
        "        {\n",
        "bounded recovery lane",
    )
    old = (
        "        // Once admitted, the tick must record the queue outcome. Dropping this\n"
        "        // future on cancellation could lose an acknowledgement after dispatch.\n"
        "        match scheduler.tick(now_ms).await {\n"
        "            Ok(tick) => {\n"
        "                if handle_automation_tick(tick, &mut retry_budget, &state, &cancellation).await? {\n"
        "                    return Ok(());\n"
        "                }\n"
        "            }\n"
        "            Err(error) => {\n"
        "                return stop_after_automation_error(error, &state, &cancellation).await;\n"
        "            }\n"
        "        }\n"
    )
    new = (
        "        // Every occurrence still records its own queue outcome before the\n"
        "        // next one is admitted. The batch is bounded and sequential.\n"
        "        match scheduler.tick_batch(now_ms, batch_limits).await {\n"
        "            Ok(batch) => {\n"
        "                runtime_error_budget.reset();\n"
        "                for tick in batch.ticks {\n"
        "                    if handle_automation_tick(\n"
        "                        tick,\n"
        "                        &mut retry_budget,\n"
        "                        &state,\n"
        "                        &cancellation,\n"
        "                    )\n"
        "                    .await?\n"
        "                    {\n"
        "                        return Ok(());\n"
        "                    }\n"
        "                }\n"
        "            }\n"
        "            Err(error) => match classify_automation_error(&error) {\n"
        "                AutomationFailureDisposition::FailStop => {\n"
        "                    return stop_after_automation_error(error, &state, &cancellation).await;\n"
        "                }\n"
        "                AutomationFailureDisposition::Retry => {\n"
        "                    let Some(delay) = runtime_error_budget.next_delay() else {\n"
        "                        return stop_after_automation_error(\n"
        "                            error,\n"
        "                            &state,\n"
        "                            &cancellation,\n"
        "                        )\n"
        "                        .await;\n"
        "                    };\n"
        "                    tokio::time::sleep(delay).await;\n"
        "                }\n"
        "                AutomationFailureDisposition::Isolate\n"
        "                | AutomationFailureDisposition::Reconcile => {\n"
        "                    runtime_error_budget.reset();\n"
        "                }\n"
        "            },\n"
        "        }\n"
    )
    text = replace_once(text, old, new, "agentd bounded admission lane")

    insertion = text.find("\nasync fn stop_after_automation_error(")
    if insertion < 0:
        raise PatchError("runtime error budget insertion point was not found")
    budget = textwrap.dedent(
        """

        #[derive(Default)]
        struct RuntimeErrorBudget {
            consecutive_retries: u8,
        }

        impl RuntimeErrorBudget {
            fn next_delay(&mut self) -> Option<Duration> {
                self.consecutive_retries = self.consecutive_retries.saturating_add(1);
                if self.consecutive_retries > AUTOMATION_MAX_CONSECUTIVE_RUNTIME_RETRIES {
                    return None;
                }
                Some(Duration::from_millis(bounded_automation_retry_delay_ms(
                    self.consecutive_retries,
                )))
            }

            fn reset(&mut self) {
                self.consecutive_retries = 0;
            }
        }
        """
    )
    text = text[:insertion] + budget + text[insertion:]
    write(path, text)


def create_runtime_tests() -> None:
    write(
        "codex-rs/hepta-automation/tests/runtime_reliability.rs",
        r'''use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationBatchLimits;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_automation::classify_automation_error;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tokio::sync::Mutex;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    #[allow(clippy::expect_used, reason = "test fixture construction must fail loudly")]
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(
                workspace.canonicalize().expect("canonical workspace"),
                &fleet_root,
            )
            .expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

#[derive(Default)]
struct RecordingQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
}

impl AutomationTurnQueue for RecordingQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.admissions.lock().await.push(admission.clone());
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!(
                    "queue-{}-{}",
                    admission.task_id, admission.occurrence
                ),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[tokio::test]
async fn bounded_batch_preserves_fifo_identity_and_backlog_age() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    for index in 0..5 {
        let draft = AutomationTaskDraft::new(
            THREAD_ID,
            format!("batch task {index}"),
            AutomationSchedule::Once,
            100,
            1,
        );
        store.create_task(&draft).await.expect("task");
    }

    let before = store.backlog_snapshot(150).await.expect("backlog");
    assert_eq!(before.due_tasks, 5);
    assert_eq!(before.oldest_due_age_ms, Some(50));
    assert_eq!(before.fairness_order, "scheduled_for_ms,task_id,occurrence");

    let queue = Arc::new(RecordingQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    let limits = AutomationBatchLimits::new(2).expect("limits");

    let first = scheduler.tick_batch(150, limits).await.expect("first batch");
    assert_eq!(first.ticks.len(), 2);
    assert!(first.budget_exhausted);
    assert!(first
        .ticks
        .iter()
        .all(|tick| matches!(tick, AutomationTick::Submitted { .. })));

    let second = scheduler.tick_batch(150, limits).await.expect("second batch");
    assert_eq!(second.ticks.len(), 2);
    assert!(second.budget_exhausted);

    let third = scheduler.tick_batch(150, limits).await.expect("third batch");
    assert_eq!(third.ticks.len(), 2);
    assert!(matches!(third.ticks[0], AutomationTick::Submitted { .. }));
    assert_eq!(third.ticks[1], AutomationTick::Idle);
    assert!(!third.budget_exhausted);

    let admissions = queue.admissions.lock().await;
    assert_eq!(admissions.len(), 5);
    let identities = admissions
        .iter()
        .map(|item| item.client_user_message_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(identities.len(), admissions.len());
    drop(admissions);

    let after = store.backlog_snapshot(150).await.expect("backlog");
    assert_eq!(after.due_tasks, 0);
    store.close().await;
}

#[test]
fn invalid_batch_and_failure_dispositions_are_explicit() {
    assert_eq!(
        AutomationBatchLimits::new(0),
        Err(AutomationError::Invalid)
    );
    assert_eq!(
        classify_automation_error(&AutomationError::Corrupt),
        AutomationFailureDisposition::FailStop
    );
    assert_eq!(
        classify_automation_error(&AutomationError::Unavailable),
        AutomationFailureDisposition::Retry
    );
    assert_eq!(
        classify_automation_error(&AutomationError::Conflict),
        AutomationFailureDisposition::Isolate
    );
    assert_eq!(
        classify_automation_error(&AutomationError::DispatchUnknown),
        AutomationFailureDisposition::Reconcile
    );
}
''',
    )


def create_slo() -> None:
    write(
        "docs/modules/automation.taskflow/SLO.md",
        r'''# automation.taskflow runtime budgets and SLO contract

**Automation store schema: v19.** Values below are source defaults and
qualification thresholds; they are not selected-host measurements or a release
receipt.

| Signal | Source bound | Required operational observation |
|---|---:|---|
| scheduler wake interval | 250 ms | tick delay and scheduling jitter |
| new admissions per pass | 8, hard library ceiling 64 | admitted count, budget exhaustion and oldest due age |
| historical reconciliation per pass | 4 | pending/uncertain count and oldest uncertain age |
| occurrence lease | 30 s | expiry/reclaim count by writer generation |
| App Server admission timeout | 5 s | timeout count and subsequent exact-ID reconciliation |
| proven pre-admission retries | 3 consecutive | retry delay and terminal isolation/fail-stop result |
| transient runtime retries | 3, 250/500/1000 ms | failure disposition and exhausted budget |
| terminal turn scan | 16 pages x 100 per pass | durable cursor continuation and exhaustion result |

## Failure disposition

* `AccessDenied`, `TimerFenced` and `Corrupt` are fail-stop.
* `Unavailable` and proven pre-contact `Dispatch` receive bounded retry/backoff.
* `Invalid` and state `Conflict` are isolated from provider execution and cannot
  manufacture success or a new external effect identity.
* `DispatchUnknown` enters reconciliation only; blind redispatch is forbidden.

## Fairness and backpressure

The authoritative due order is `(scheduled_for_ms, task_id, occurrence)`. A batch
reuses the existing one-occurrence transaction sequentially, so provider calls do
not become unbounded concurrent work. Recovery and admission have separate source
budgets. `AutomationBacklogSnapshot` exposes a bounded task/occurrence/uncertainty
scan, oldest ages, truncation and the fairness order without claiming work.

Before activation, qualify p50/p95/p99 scheduling delay, maximum backlog age,
restart drain time, provider saturation, SQLite busy behavior, lease expiry and
writer-epoch mismatch on the selected host. Missing, truncated or fixture-only
measurements keep deployment qualification false.
''',
    )


def patch_runtime_docs() -> None:
    dossier_path = "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    dossier = read(dossier_path)
    old = (
        "Current hard bounds include <=1024 recovery/due frontier records per owner query, <=1024 catch-up occurrences per configured window, <=512 timezone transitions per Calendar V2 profile, <=1032 bounded calendar-day probes, TaskFlow's registered graph/step bounds, and <=16 pages of 100 persisted turns for one terminal-observation scan. Agentd still admits at most one new scheduler occurrence per tick and reconciles at most one historical occurrence per tick. No busy-loop retry or unlimited backlog is introduced."
    )
    new = (
        "Current hard bounds include <=1024 recovery/due frontier records per owner query, <=1024 catch-up occurrences per configured window, <=512 timezone transitions per Calendar V2 profile, <=1032 bounded calendar-day probes, TaskFlow's registered graph/step bounds, and <=16 pages of 100 persisted turns for one terminal-observation scan. Agentd uses separate per-pass budgets of four historical reconciliations and eight sequential new admissions; the library rejects zero or more than 64 admissions. The durable due order remains `(scheduled_for_ms, task_id, occurrence)`, backlog snapshots expose bounded oldest-age/truncation evidence, and no busy-loop retry or unlimited provider concurrency is introduced."
    )
    dossier = replace_once(dossier, old, new, "dossier capacity profile")
    if "SLO.md" not in dossier:
        dossier = dossier.replace(
            "Pilot ceilings remain design/qualification inputs, not deployment measurements. Bind selected-host latency, backlog, restore and saturation evidence before activation.",
            "Pilot ceilings remain design/qualification inputs, not deployment measurements. Bind selected-host latency, backlog, restore and saturation evidence before activation. The source budgets and required observations are enumerated in `docs/modules/automation.taskflow/SLO.md`.",
            1,
        )
    write(dossier_path, dossier)

    technical_path = "docs/modules/automation.taskflow/TECHNICAL.md"
    technical = read(technical_path)
    if "Bounded admission and recovery budgets" in technical:
        raise PatchError("runtime technical section already exists")
    technical += textwrap.dedent(
        """

        ## 20. Bounded admission and recovery budgets

        The product host uses separate budgets: four historical reconciliations
        and eight sequential new admissions per 250-ms wake. The public library
        rejects zero and caps a caller at 64 admissions. Every item still crosses
        the original occurrence transaction, durable dispatch-intent boundary and
        queue/provider acknowledgement before the next item, so batching does not
        create unbounded provider concurrency.

        Due selection remains ordered by scheduled instant, task ID and occurrence.
        `AutomationBacklogSnapshot` exposes a bounded oldest-due/oldest-uncertain
        age, pending counts and truncation without claiming work. Stable failure
        dispositions distinguish fail-stop, bounded retry, isolated invalid/conflict
        input and reconcile-only unknown outcomes. Source constants and target-host
        qualification requirements are in [SLO.md](SLO.md).
        """
    )
    write(technical_path, technical)


def apply_source() -> None:
    patch_scheduler()
    create_failure_policy()
    create_runtime_status()
    patch_lib()
    patch_recovery()
    patch_agentd_scheduler()
    create_runtime_tests()
    create_slo()
    patch_runtime_docs()


def apply_metadata(source_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise PatchError("source SHA must be exact")
    path = "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
    data = json.loads(read(path))
    data["observedAtHead"] = {
        "commit": source_sha,
        "tree": git("rev-parse", f"{source_sha}^{{tree}}"),
    }
    observed = set(data["observedSourcePaths"])
    observed.update(
        {
            "codex-rs/hepta-automation/src/failure_policy.rs",
            "codex-rs/hepta-automation/src/runtime_status.rs",
            "codex-rs/hepta-automation/tests/runtime_reliability.rs",
            "docs/modules/automation.taskflow/SLO.md",
        }
    )
    data["observedSourcePaths"] = sorted(observed)
    data["runtimeBudgets"] = {
        "tickIntervalMs": 250,
        "recoveryPerPass": 4,
        "admissionsPerPass": 8,
        "libraryAdmissionCeiling": 64,
        "leaseMs": 30000,
        "dispatchTimeoutMs": 5000,
        "terminalTurnPagesPerPass": 16,
        "terminalTurnsPerPage": 100,
        "slo": "docs/modules/automation.taskflow/SLO.md",
    }
    claim = data["claimBoundary"]
    claim["boundedAdmissionBatchComplete"] = True
    claim["separateRecoveryAdmissionBudgetsComplete"] = True
    claim["failureDispositionComplete"] = True
    claim["backlogAgeObservable"] = True
    claim["providerBackpressureBounded"] = True
    claim["deploymentQualificationComplete"] = False
    claim["release"] = False

    for operation in data["operations"]:
        operation["sourceBlob"] = git(
            "rev-parse", f"{source_sha}:{operation['sourcePath']}"
        )
        if operation["designOperation"] == "materialize_due":
            operation["sourceSemantics"] = (
                "Claims FIFO due work, freezes schedule revision and canonical "
                "occurrence identity, and admits a caller-bounded sequential batch "
                "through the unchanged durable per-occurrence transaction; recovery "
                "and admission consume separate host budgets."
            )
            tests = operation.setdefault("tests", [])
            tests.append(
                {
                    "path": "codex-rs/hepta-automation/tests/runtime_reliability.rs",
                    "kind": "bounded_batch_fifo_identity_backlog_and_failure_policy",
                    "command": "cargo test -p codex-hepta-automation --test runtime_reliability",
                }
            )

    for entry in data["exactSourceEvidence"]["entries"]:
        entry["blobSha"] = git("rev-parse", f"{source_sha}:{entry['path']}")

    object_paths = {
        row["path"] for row in data.get("sourceObjects", []) if isinstance(row, dict)
    }
    object_paths.update(observed)
    data["sourceObjects"] = [
        {"path": item, "object": git("rev-parse", f"{source_sha}:{item}")}
        for item in sorted(object_paths)
    ]
    write(path, json.dumps(data, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("source")
    metadata = sub.add_parser("metadata")
    metadata.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        if args.command == "source":
            apply_source()
        else:
            apply_metadata(args.source_sha)
    except (OSError, ValueError, KeyError, PatchError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"automation runtime patch failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
