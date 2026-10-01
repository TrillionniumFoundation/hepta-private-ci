#!/usr/bin/env python3
"""Make the durable Agentd run owner publish state only after persistence succeeds.

The preceding durability migration adds a generation-bound, fsync+rename store.
This pass removes the remaining write-through ordering hazard: product RPCs now
mutate a clone, persist that candidate under the store-revision fence, and only
then replace the process-visible coordinator. A failed fsync/CAS therefore
cannot leak uncommitted run state to later requests in the same process.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one source block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: source block and migrated marker are both absent")


def lane_b_runtime(text: str) -> str:
    text = replace_once(
        text,
        "#[derive(Debug)]\npub struct AgentRunCoordinator {",
        "#[derive(Clone, Debug)]\npub struct AgentRunCoordinator {",
        "#[derive(Clone, Debug)]\npub struct AgentRunCoordinator",
    )
    old = '''        self.durable_store_revision = next_revision;
        Ok(())
    }

    pub fn composition(&self) -> &RuntimeComposition {
'''
    new = '''        self.durable_store_revision = next_revision;
        Ok(())
    }

    /// Persist a fully prepared candidate and publish it to in-process readers
    /// only after the durable store accepted the exact preceding revision.
    /// On every error `self` remains byte-for-byte at its last committed state.
    pub(crate) fn publish_candidate<T>(
        &mut self,
        mut candidate: Self,
        value: T,
    ) -> Result<T, AgentRunError> {
        if candidate.composition != self.composition
            || candidate.durable_path != self.durable_path
            || candidate.durable_store_revision != self.durable_store_revision
        {
            return Err(AgentRunError::Persistence(
                "durable run candidate did not originate from the current owner revision"
                    .to_string(),
            ));
        }
        candidate.persist()?;
        *self = candidate;
        Ok(value)
    }

    pub fn composition(&self) -> &RuntimeComposition {
'''
    return replace_once(text, old, new, "pub(crate) fn publish_candidate")


def state_control(text: str) -> str:
    replacements = [
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .start_run(now_ms()?, internal_run_snapshot(snapshot))
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .start_run(now_ms()?, internal_run_snapshot(snapshot))
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"publish_candidate(candidate, ())",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .attach_context(
                        now_ms()?,
                        expected_revision,
                        internal_context_attachment(attachment),
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .attach_context(
                        now_ms()?,
                        expected_revision,
                        internal_context_attachment(attachment),
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"candidate\n                    .attach_context",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"candidate\n                    .mark_dispatched(now_ms()?",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .mark_dispatched_bound(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        dispatch_binding_digest,
                        pre_effect_abort_commitment_digest,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .mark_dispatched_bound(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        dispatch_binding_digest,
                        pre_effect_abort_commitment_digest,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"candidate\n                    .mark_dispatched_bound",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .abort_before_effect(
                        &run_id,
                        expected_revision,
                        &dispatch_binding_digest,
                        &abort_nonce_hex,
                        &proof_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .abort_before_effect(
                        &run_id,
                        expected_revision,
                        &dispatch_binding_digest,
                        &abort_nonce_hex,
                        &proof_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"candidate\n                    .abort_before_effect",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let (disposition, receipt) = runs
                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let (disposition, receipt) = candidate
                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"let (disposition, receipt) = candidate",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .observe_terminal(
                        &run_id,
                        expected_revision,
                        internal_run_phase(phase),
                        terminal_observed,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .observe_terminal(
                        &run_id,
                        expected_revision,
                        internal_run_phase(phase),
                        terminal_observed,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs
                        .publish_candidate(candidate, ())
                        .map_err(run_error)?;
                }
''',
"candidate\n                    .observe_terminal",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .remove_closed_run(&run_id, expected_revision)
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let receipt = candidate
                    .remove_closed_run(&run_id, expected_revision)
                    .map_err(run_error)?;
                runs
                    .publish_candidate(candidate, ())
                    .map_err(run_error)?;
''',
"candidate\n                    .remove_closed_run",
        ),
    ]
    for old, new, marker in replacements:
        text = replace_once(text, old, new, marker)
    return text


def state(text: str) -> str:
    replacements = [
        (
'''            if runtime.lifecycle == AgentLifecycle::Draining {
                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                runs
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
            }
''',
'''            if runtime.lifecycle == AgentLifecycle::Draining {
                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                candidate
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
                runs
                    .publish_candidate(candidate, ())
                    .map_err(run_error)?;
            }
''',
"candidate\n                    .begin_drain(unix_now_ms()?, \"supervisor_draining\")",
        ),
        (
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        runs
            .begin_drain(unix_now_ms()?, "agentd_shutdown")
            .map_err(run_error)?;
        runs.persist().map_err(run_error)?;
        Ok(())
''',
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let mut candidate = runs.clone();
        candidate
            .begin_drain(unix_now_ms()?, "agentd_shutdown")
            .map_err(run_error)?;
        runs
            .publish_candidate(candidate, ())
            .map_err(run_error)?;
        Ok(())
''',
"candidate\n            .begin_drain(unix_now_ms()?, \"agentd_shutdown\")",
        ),
        (
'''        if let Ok(mut runs) = self.runs.lock() {
            runs.close_admissions();
            if let Ok(now_ms) = unix_now_ms() {
                let _ = runs.begin_drain(now_ms, "generation_fenced");
            }
            let _ = runs.mark_unresolved_indeterminate("generation_fenced");
            let _ = runs.persist();
        }
''',
'''        if let Ok(mut runs) = self.runs.lock() {
            let mut candidate = runs.clone();
            candidate.close_admissions();
            if let Ok(now_ms) = unix_now_ms() {
                let _ = candidate.begin_drain(now_ms, "generation_fenced");
            }
            let _ = candidate.mark_unresolved_indeterminate("generation_fenced");
            let _ = runs.publish_candidate(candidate, ());
        }
''',
"let _ = runs.publish_candidate(candidate, ());",
        ),
        (
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let admitted = runs
                    .start_run(
                        now_ms,
                        crate::RunSnapshot {
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let mut candidate = runs.clone();
                let admitted = candidate
                    .start_run(
                        now_ms,
                        crate::RunSnapshot {
''',
"let admitted = candidate",
        ),
        (
'''                let run_receipt = runs
                    .attach_context(
''',
'''                let run_receipt = candidate
                    .attach_context(
''',
"let run_receipt = candidate",
        ),
        (
'''                    )
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
''',
'''                    )
                    .map_err(run_error)?;
                runs
                    .publish_candidate(candidate, ())
                    .map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
''',
"publish_candidate(candidate, ())\n                    .map_err(run_error)?;\n                Ok(Some",
        ),
        (
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let receipt = runs
            .start_revalidated_run_start(now_ms, record)
            .map_err(run_error)?;
        if !receipt.idempotent {
            runs.persist().map_err(run_error)?;
        }
        Ok(receipt)
''',
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let mut candidate = runs.clone();
        let receipt = candidate
            .start_revalidated_run_start(now_ms, record)
            .map_err(run_error)?;
        if !receipt.idempotent {
            runs
                .publish_candidate(candidate, ())
                .map_err(run_error)?;
        }
        Ok(receipt)
''',
"candidate\n            .start_revalidated_run_start",
        ),
        (
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let changed = runs
            .expire_deadlines(unix_now_ms()?)
            .map_err(run_error)?;
        if changed != 0 {
            runs.persist().map_err(run_error)?;
        }
        Ok(changed)
''',
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let mut candidate = runs.clone();
        let changed = candidate
            .expire_deadlines(unix_now_ms()?)
            .map_err(run_error)?;
        if changed != 0 {
            runs
                .publish_candidate(candidate, ())
                .map_err(run_error)?;
        }
        Ok(changed)
''',
"let changed = candidate\n            .expire_deadlines",
        ),
        (
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let changed = runs
            .mark_unresolved_indeterminate(reason)
            .map_err(run_error)?;
        if changed != 0 {
            runs.persist().map_err(run_error)?;
        }
        Ok(changed)
''',
'''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let mut candidate = runs.clone();
        let changed = candidate
            .mark_unresolved_indeterminate(reason)
            .map_err(run_error)?;
        if changed != 0 {
            runs
                .publish_candidate(candidate, ())
                .map_err(run_error)?;
        }
        Ok(changed)
''',
"let changed = candidate\n            .mark_unresolved_indeterminate",
        ),
    ]
    for old, new, marker in replacements:
        text = replace_once(text, old, new, marker)
    return text


def lane_b_tests(text: str) -> str:
    if "failed_candidate_publish_does_not_leak_uncommitted_state" in text:
        return text
    return text + r'''

#[test]
fn failed_candidate_publish_does_not_leak_uncommitted_state() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("agent-runs.json");
    let mut current = AgentRunCoordinator::open_durable(composition(), path.clone())
        .expect("open current owner");
    let mut stale = AgentRunCoordinator::open_durable(composition(), path)
        .expect("open stale owner");

    let mut committed = current.clone();
    let receipt = committed
        .start_run(100, snapshot())
        .expect("prepare committed run");
    current
        .publish_candidate(committed, receipt)
        .expect("publish committed run");

    let mut second = snapshot();
    second.run_id = "run:stale-candidate".to_string();
    let mut uncommitted = stale.clone();
    let stale_receipt = uncommitted
        .start_run(100, second)
        .expect("prepare stale candidate");
    assert!(matches!(
        stale.publish_candidate(uncommitted, stale_receipt),
        Err(AgentRunError::Persistence(_))
    ));
    assert!(stale.run("run:stale-candidate").is_none());
    assert!(stale.run("run.1").is_none());
}
'''


def historical_compatibility(text: str) -> str:
    marker = "//! Historical compatibility source: not included in the active hepta-agentd module tree.\n"
    if text.startswith(marker):
        return text
    return marker + text


def main() -> None:
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime.rs", lane_b_runtime)
    rewrite("codex-rs/hepta-agentd/src/state_control.rs", state_control)
    rewrite("codex-rs/hepta-agentd/src/state.rs", state)
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs", lane_b_tests)
    for path in [
        "codex-rs/hepta-agentd/src/objective_host.rs",
        "codex-rs/hepta-agentd/src/objective_ingress.rs",
        "codex-rs/hepta-agentd/src/objective_dispatch.rs",
    ]:
        rewrite(path, historical_compatibility)


if __name__ == "__main__":
    main()
