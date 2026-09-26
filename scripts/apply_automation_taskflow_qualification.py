#!/usr/bin/env python3
"""Harden generated automation runtime tests and metadata."""

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


def patch_neural_runtime() -> None:
    path = "codex-rs/hepta-automation/src/neural_circuit_runtime.rs"
    text = read(path)
    old = '''                        return Ok(NeuralCircuitDecisionProgressV1::Feedback {
                            round,
                            choice_digest: required_receipt_digest(&existing)?,
                            replayed: true,
                        });
'''
    new = '''                        // A recovered feedback receipt is history, not a new
                        // response. Continue to the first missing bounded round
                        // instead of re-invoking or getting stuck on the same cell.
                        continue;
'''
    text = replace_once(text, old, new, "recorded feedback continuation")
    write(path, text)

    test_path = "codex-rs/hepta-automation/tests/neural_circuit_runtime.rs"
    test = read(test_path)
    if not test.startswith("#![allow(clippy::expect_used"):
        test = (
            '#![allow(clippy::expect_used, reason = "test assertions use explicit failure context")]\n\n'
            + test
        )
    write(test_path, test)

    reliability_path = "codex-rs/hepta-automation/tests/runtime_reliability.rs"
    reliability = read(reliability_path)
    if not reliability.startswith("#![allow(clippy::expect_used"):
        reliability = (
            '#![allow(clippy::expect_used, reason = "test assertions use explicit failure context")]\n\n'
            + reliability
        )
    write(reliability_path, reliability)


def create_crash_tests() -> None:
    write(
        "codex-rs/hepta-automation/tests/runtime_crash_points.rs",
        r'''#![allow(clippy::expect_used, reason = "test assertions use explicit failure context")]

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
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

#[derive(Clone, Copy)]
enum QueueMode {
    BeforeAdmissionFailure,
    OutcomeUnknown,
}

struct CrashQueue {
    mode: QueueMode,
}

impl AutomationTurnQueue for CrashQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        let mode = self.mode;
        Box::pin(async move {
            match mode {
                QueueMode::BeforeAdmissionFailure => Err(AutomationError::Dispatch),
                QueueMode::OutcomeUnknown => Err(AutomationError::DispatchUnknown),
            }
        })
    }
}

async fn create_due(store: &AutomationStore, prompt: &str) {
    store
        .create_task(&AutomationTaskDraft::new(
            THREAD_ID,
            prompt,
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await
        .expect("create task");
}

#[tokio::test]
async fn possible_admission_survives_close_and_reopen_as_exact_uncertainty() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    create_due(&store, "unknown after provider boundary").await;
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(CrashQueue {
            mode: QueueMode::OutcomeUnknown,
        }),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    let tick = scheduler.tick(100).await.expect("tick");
    let (task_id, occurrence) = match tick {
        AutomationTick::DispatchUncertain {
            task_id,
            occurrence,
        } => (task_id, occurrence),
        other => panic!("expected uncertainty, observed {other:?}"),
    };
    let before = store.uncertain_dispatches(8).await.expect("uncertain");
    assert_eq!(before.len(), 1);
    let stable_client_id = before[0].client_user_message_id.clone();
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout).await.expect("reopen");
    let after = reopened
        .uncertain_dispatches(8)
        .await
        .expect("reopened uncertainty");
    assert_eq!(after.len(), 1);
    assert_eq!(after[0].task_id, task_id);
    assert_eq!(after[0].occurrence, occurrence);
    assert_eq!(after[0].client_user_message_id, stable_client_id);
    reopened.close().await;
}

#[tokio::test]
async fn proven_pre_admission_failure_is_retryable_and_never_quarantined_unknown() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    create_due(&store, "failure before provider boundary").await;
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(CrashQueue {
            mode: QueueMode::BeforeAdmissionFailure,
        }),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("tick"),
        AutomationTick::RetryScheduled { .. }
    ));
    assert!(store
        .uncertain_dispatches(8)
        .await
        .expect("uncertain")
        .is_empty());
    store.close().await;
}
''',
    )

    write(
        "codex-rs/hepta-automation/tests/runtime_state_machine_fuzz.rs",
        r'''use codex_hepta_automation::AutomationBatchLimits;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::MAX_AUTOMATION_ADMISSION_BATCH;
use codex_hepta_automation::MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS;
use codex_hepta_automation::MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH;
use codex_hepta_automation::NeuralCircuitRuntimeBudgetV1;
use codex_hepta_automation::bounded_automation_retry_delay_ms;
use codex_hepta_automation::classify_automation_error;

fn xorshift64(mut value: u64) -> u64 {
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    value
}

#[test]
fn deterministic_property_sweep_preserves_all_runtime_bounds() {
    let mut state = 0x4d59_5df4_d0f3_3173_u64;
    for _ in 0..20_000 {
        state = xorshift64(state);
        let admissions = usize::try_from(state % 96).expect("bounded usize");
        assert_eq!(
            AutomationBatchLimits::new(admissions).is_ok(),
            (1..=MAX_AUTOMATION_ADMISSION_BATCH).contains(&admissions)
        );

        state = xorshift64(state);
        let depth = u32::try_from(state % 300).expect("bounded depth");
        state = xorshift64(state);
        let feedback = u32::try_from(state % 48).expect("bounded feedback");
        assert_eq!(
            NeuralCircuitRuntimeBudgetV1::new(depth, feedback).is_ok(),
            depth > 0
                && depth <= MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH
                && feedback <= MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS
        );

        state = xorshift64(state);
        let attempt = u8::try_from(state % 32).expect("bounded attempt");
        let delay = bounded_automation_retry_delay_ms(attempt);
        assert!((250..=4_000).contains(&delay));
    }
}

#[test]
fn failure_state_machine_never_retries_unknown_or_corrupt_outcomes() {
    let cases = [
        (AutomationError::AccessDenied, AutomationFailureDisposition::FailStop),
        (AutomationError::TimerFenced, AutomationFailureDisposition::FailStop),
        (AutomationError::Corrupt, AutomationFailureDisposition::FailStop),
        (AutomationError::Unavailable, AutomationFailureDisposition::Retry),
        (AutomationError::Dispatch, AutomationFailureDisposition::Retry),
        (AutomationError::Invalid, AutomationFailureDisposition::Isolate),
        (AutomationError::Conflict, AutomationFailureDisposition::Isolate),
        (
            AutomationError::DispatchUnknown,
            AutomationFailureDisposition::Reconcile,
        ),
    ];
    for (error, expected) in cases {
        assert_eq!(classify_automation_error(&error), expected);
    }
}
''',
    )


def patch_docs() -> None:
    dossier_path = "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    dossier = read(dossier_path)
    if "Crash and state-machine qualification" not in dossier:
        dossier += textwrap.dedent(
            """

            ## 9. Crash and state-machine qualification

            `runtime_crash_points.rs` distinguishes proven pre-admission failure
            from a result that may have crossed the boundary and verifies that the
            latter survives close/reopen under the exact stable client identity.
            `runtime_state_machine_fuzz.rs` performs a deterministic 20,000-case
            property sweep over admission, depth, feedback and retry bounds and
            enumerates every public failure disposition. These tests supplement,
            rather than replace, selected-host crash injection and provider lookup.
            """
        )
    write(dossier_path, dossier)


def apply_source() -> None:
    patch_neural_runtime()
    create_crash_tests()
    patch_docs()


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
            "codex-rs/hepta-automation/tests/runtime_crash_points.rs",
            "codex-rs/hepta-automation/tests/runtime_state_machine_fuzz.rs",
        }
    )
    data["observedSourcePaths"] = sorted(observed)
    data["runtimeQualification"] = {
        "crashPointMatrix": True,
        "dispatchUnknownSurvivesReopen": True,
        "preAdmissionFailureNotQuarantined": True,
        "deterministicPropertyCases": 20000,
        "failureStateMachineExhaustive": True,
        "selectedHostCrashInjection": False,
    }
    claim = data["claimBoundary"]
    claim["crashPointQualificationComplete"] = True
    claim["propertyStateMachineQualificationComplete"] = True
    claim["selectedHostCrashQualificationComplete"] = False
    claim["deploymentQualificationComplete"] = False
    claim["release"] = False
    for operation in data["operations"]:
        operation["sourceBlob"] = git(
            "rev-parse", f"{source_sha}:{operation['sourcePath']}"
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
        raise SystemExit(f"automation qualification patch failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
