#!/usr/bin/env python3
"""Asserted wiring for canonical run-phase dwell observability."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{path}: expected one observability rewrite target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    lib = "codex-rs/hepta-agentd/src/lib.rs"
    replace_once(
        lib,
        '''pub use intelligence_observability::AgentdIntelligenceStageTelemetrySnapshotV1;
pub use intelligence_observability::AgentdIntelligenceTelemetrySnapshotV1;''',
        '''pub use intelligence_observability::AgentdIntelligenceRunDwellSnapshotV1;
pub use intelligence_observability::AgentdIntelligenceRunPhaseDurationV1;
pub use intelligence_observability::AgentdIntelligenceStageTelemetrySnapshotV1;
pub use intelligence_observability::AgentdIntelligenceTelemetrySnapshotV1;''',
    )

    observability = "codex-rs/hepta-agentd/src/intelligence_observability.rs"
    replace_once(
        observability,
        '''    #[must_use]
    pub fn run_phase_dwell_snapshot(
        &self,
        run_id: &str,
        observed_at_ms: u64,
    ) -> Option<AgentdIntelligenceRunDwellSnapshotV1> {''',
        '''    #[must_use]
    pub fn tracks_run(&self, run_id: &str) -> bool {
        self.run_dwell
            .lock()
            .is_ok_and(|records| records.contains_key(run_id))
    }

    #[must_use]
    pub fn run_phase_dwell_snapshot(
        &self,
        run_id: &str,
        observed_at_ms: u64,
    ) -> Option<AgentdIntelligenceRunDwellSnapshotV1> {''',
    )

    state = "codex-rs/hepta-agentd/src/state.rs"
    replace_once(
        state,
        '''    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {
        self.intelligence_product.get().is_some() && self.intelligence_invocation.get().is_some()
    }

    /// Prepare the exact durable Objective''',
        '''    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {
        self.intelligence_product.get().is_some() && self.intelligence_invocation.get().is_some()
    }

    pub(crate) fn record_intelligence_run_receipt(
        &self,
        receipt: &crate::RunReceipt,
        initialize: bool,
    ) {
        let Some(runner) = self.intelligence_product.get() else {
            return;
        };
        let telemetry = runner.telemetry();
        if !initialize && !telemetry.tracks_run(&receipt.run_id) {
            return;
        }
        if let Ok(now_ms) = unix_now_ms() {
            telemetry.observe_run_receipt(receipt, now_ms);
        }
    }

    /// Prepare the exact durable Objective''',
    )
    replace_once(
        state,
        '''                    )
                    .map_err(run_error)?;
                let run_receipt = runs
                    .attach_context(''',
        '''                    )
                    .map_err(run_error)?;
                runner.telemetry().observe_run_receipt(&admitted, now_ms);
                let run_receipt = runs
                    .attach_context(''',
    )
    replace_once(
        state,
        '''                    )
                    .map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {''',
        '''                    )
                    .map_err(run_error)?;
                runner.telemetry().observe_run_receipt(&run_receipt, now_ms);
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {''',
    )

    control = "codex-rs/hepta-agentd/src/state_control.rs"
    replace_once(
        control,
        '''                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunMarkDispatched {''',
        '''                    )
                    .map_err(run_error)?;
                self.record_intelligence_run_receipt(&receipt, false);
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunMarkDispatched {''',
    )
    replace_once(
        control,
        '''                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))''',
        '''                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                self.record_intelligence_run_receipt(&receipt, false);
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))''',
    )
    replace_once(
        control,
        '''                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                AgentdPayload::RunCancellation(crate::AgentRunCancellation {''',
        '''                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                self.record_intelligence_run_receipt(&receipt, false);
                AgentdPayload::RunCancellation(crate::AgentRunCancellation {''',
    )
    replace_once(
        control,
        '''                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunStatus {''',
        '''                    )
                    .map_err(run_error)?;
                self.record_intelligence_run_receipt(&receipt, false);
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunStatus {''',
    )

    status = "scripts/hepta-intelligence-control-status.py"
    replace_once(
        status,
        '''    "authorityEpochTelemetryPresent": ("telemetry", "last_authority_epoch"),
    "hardTimeoutProcessFencePresent": (''',
        '''    "authorityEpochTelemetryPresent": ("telemetry", "last_authority_epoch"),
    "runPhaseDwellTelemetryPresent": (
        "telemetry",
        "run_phase_dwell_snapshot",
    ),
    "hardTimeoutProcessFencePresent": (''',
    )
    replace_once(
        status,
        '''    "stage_failure_classes_remain_separate",
    "operation_ids_are_kind_separated_and_stable",''',
        '''    "stage_failure_classes_remain_separate",
    "run_phase_dwell_accumulates_exact_transitions",
    "same_phase_idempotent_replay_does_not_reset_dwell",
    "operation_ids_are_kind_separated_and_stable",''',
    )
    replace_once(
        status,
        '''                    "lateWorkerTelemetryPresent",
                    "hardTimeoutProcessFencePresent",''',
        '''                    "lateWorkerTelemetryPresent",
                    "runPhaseDwellTelemetryPresent",
                    "hardTimeoutProcessFencePresent",''',
    )
    replace_once(
        status,
        '''                "tests": names("worker_timeout", "stage_failure_classes", "total_budget_timeout"),''',
        '''                "tests": names(
                    "worker_timeout",
                    "stage_failure_classes",
                    "run_phase_dwell",
                    "same_phase_idempotent",
                    "total_budget_timeout",
                ),''',
    )


if __name__ == "__main__":
    main()
