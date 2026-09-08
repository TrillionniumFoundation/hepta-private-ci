#!/usr/bin/env python3
"""Remove stale lint formalism and repair strict workspace lint findings.

Every edit is an exact, single-source transformation against the pinned source
candidate. A mismatch aborts instead of guessing or weakening a lint.
"""

from __future__ import annotations

from pathlib import Path


REGISTRY = Path("codex-rs/core/src/tools/registry.rs")
BEDROCK = Path(
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs"
)
TURN_INPUT = Path("codex-rs/core/src/session/turn_input.rs")
SESSION = Path("codex-rs/core/src/session/mod.rs")
DYNAMIC = Path("codex-rs/core/src/tools/handlers/dynamic.rs")
TASKS = Path("codex-rs/core/src/tasks/mod.rs")
BINDING = Path("codex-rs/core/src/model_provider_policy/binding.rs")


def replace_exact(text: str, old: str, new: str, *, label: str, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{label}: expected {count} exact matches, found {actual}")
    return text.replace(old, new, count)


def patch_registry() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '    #[expect(dead_code, reason = "retained tool cancellation metadata query")]\n',
        "",
        label="trait cancellation lint expectation",
    )
    wrapper = '''
    pub(crate) fn waits_for_runtime_cancellation(&self, name: &ToolName) -> Option<bool> {
        let tool = self.tool(name)?;
        Some(tool.waits_for_runtime_cancellation())
    }
'''
    text = replace_exact(
        text,
        wrapper,
        "",
        label="unused ToolRegistry cancellation wrapper",
    )
    REGISTRY.write_text(text, encoding="utf-8")


def patch_bedrock() -> None:
    text = BEDROCK.read_text(encoding="utf-8")
    top_level_expect = '''#[expect(
    dead_code,
    reason = "Bedrock account endpoints are not yet routed by the stable protocol"
)]
'''
    text = replace_exact(
        text,
        top_level_expect,
        "",
        label="top-level Bedrock lint expectations",
        count=4,
    )
    BEDROCK.write_text(text, encoding="utf-8")


def patch_turn_input() -> None:
    text = TURN_INPUT.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '''    let Some(expected) = session.reference_context_item().await else {
        return None;
    };
''',
        '''    let expected = session.reference_context_item().await?;
''',
        label="recovery reference context question-mark simplification",
    )
    TURN_INPUT.write_text(text, encoding="utf-8")


def patch_session() -> None:
    text = SESSION.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        ".map_or(true, |current| current.task_terminalization.is_some())",
        ".is_none_or(|current| current.task_terminalization.is_some())",
        label="session active-turn terminalization predicates",
        count=2,
    )
    SESSION.write_text(text, encoding="utf-8")


def patch_dynamic() -> None:
    text = DYNAMIC.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        ".map_or(true, |current| current.task_terminalization.is_some())",
        ".is_none_or(|current| current.task_terminalization.is_some())",
        label="dynamic tool active-turn predicate",
    )
    DYNAMIC.write_text(text, encoding="utf-8")


def patch_tasks() -> None:
    text = TASKS.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        "excluded_identity.map_or(true, |excluded| !Arc::ptr_eq(identity, excluded))",
        "excluded_identity.is_none_or(|excluded| !Arc::ptr_eq(identity, excluded))",
        label="terminalization exclusion predicate",
    )
    text = replace_exact(
        text,
        "ignored_identity.map_or(true, |ignored| !Arc::ptr_eq(identity, ignored))",
        "ignored_identity.is_none_or(|ignored| !Arc::ptr_eq(identity, ignored))",
        label="pending transition exclusion predicates",
        count=2,
    )
    text = replace_exact(
        text,
        '''        let Some(active_turn) = active.as_mut() else {
            return None;
        };
        let Some(marker) = active_turn.task_terminalization.as_ref() else {
            return None;
        };
''',
        '''        let active_turn = active.as_mut()?;
        let marker = active_turn.task_terminalization.as_ref()?;
''',
        label="terminalization marker question-mark simplification",
    )
    text = replace_exact(
        text,
        '''        let Some(authority) = authority else {
            return None;
        };
''',
        '''        let authority = authority?;
''',
        label="recovery authority question-mark simplification",
    )

    first_lock_old = '''        let turn_state = {
            let active = self.active_turn.lock().await;
            let Some(turn) = active.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if turn.task.is_some() || turn.task_terminalization.is_some() {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
            let Some(transition) = turn.start_transition.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if !Arc::ptr_eq(&transition.identity, &start_transition_identity) {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
            Arc::clone(&turn.turn_state)
        };
'''
    first_lock_new = '''        let turn_state = {
            let active = self.active_turn.lock().await;
            active.as_ref().and_then(|turn| {
                if turn.task.is_some() || turn.task_terminalization.is_some() {
                    return None;
                }
                let transition = turn.start_transition.as_ref()?;
                Arc::ptr_eq(&transition.identity, &start_transition_identity)
                    .then(|| Arc::clone(&turn.turn_state))
            })
        };
        let Some(turn_state) = turn_state else {
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        };
'''
    text = replace_exact(
        text,
        first_lock_old,
        first_lock_new,
        label="pre-attach active-turn lock scope",
    )

    second_lock_old = '''        let mut active = self.active_turn.lock().await;
        let Some(turn) = active.as_mut() else {
            drop(active);
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        };
        if turn.task.is_some() || turn.task_terminalization.is_some() {
            drop(active);
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        }
        {
            let Some(transition) = turn.start_transition.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if !Arc::ptr_eq(&transition.identity, &start_transition_identity) {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
        }
'''
    second_lock_new = '''        let mut active = self.active_turn.lock().await;
        let transition_is_current = active.as_ref().is_some_and(|turn| {
            turn.task.is_none()
                && turn.task_terminalization.is_none()
                && turn.start_transition.as_ref().is_some_and(|transition| {
                    Arc::ptr_eq(&transition.identity, &start_transition_identity)
                })
        });
        if !transition_is_current {
            drop(active);
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        }
        let turn = active
            .as_mut()
            .unwrap_or_else(|| panic!("current start transition retains the active turn"));
'''
    text = replace_exact(
        text,
        second_lock_old,
        second_lock_new,
        label="final attach active-turn lock scope",
    )

    text = replace_exact(
        text,
        '''            if let Some(cleanup) = start_transition_owner.spawn_cleanup(reason) {
                if let Err(error) = cleanup.await {
                    // A panic or runtime teardown in the detached path must
                    // remain observable.  The cleanup CAS is intentionally
                    // fail-closed, so an errored join cannot make this turn
                    // look idle or permit a replacement start.
                    warn!(
                        turn_id = %turn_context.sub_id,
                        ?error,
                        "start transition terminalizer did not complete"
                    );
                }
            }
''',
        '''            if let Some(cleanup) = start_transition_owner.spawn_cleanup(reason)
                && let Err(error) = cleanup.await
            {
                // A panic or runtime teardown in the detached path must
                // remain observable.  The cleanup CAS is intentionally
                // fail-closed, so an errored join cannot make this turn
                // look idle or permit a replacement start.
                warn!(
                    turn_id = %turn_context.sub_id,
                    ?error,
                    "start transition terminalizer did not complete"
                );
            }
''',
        label="start cleanup conditional collapse",
    )
    text = replace_exact(
        text,
        '''            if transition.abort_reason.is_none() {
                if transition.request_abort(fallback_reason.clone())
                    && matches!(
                        fallback_reason,
                        TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
                    )
                {
                    self.mark_interrupted();
                }
            }
''',
        '''            if transition.abort_reason.is_none()
                && transition.request_abort(fallback_reason.clone())
                && matches!(
                    fallback_reason,
                    TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
                )
            {
                self.mark_interrupted();
            }
''',
        label="dropped transition abort conditional collapse",
    )
    text = replace_exact(
        text,
        ".and_then(|transition| transition.take_deferred_idle())",
        ".and_then(StartTransition::take_deferred_idle)",
        label="deferred idle method closure",
    )
    text = replace_exact(
        text,
        '''    let Some((content, client_id)) = user_input else {
        return None;
    };
''',
        '''    let (content, client_id) = user_input?;
''',
        label="qualification identity question-mark simplification",
    )
    TASKS.write_text(text, encoding="utf-8")


def patch_binding() -> None:
    text = BINDING.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        ".map(|host| host.to_ascii_lowercase())",
        ".map(str::to_ascii_lowercase)",
        label="canonical endpoint host mapping",
    )
    BINDING.write_text(text, encoding="utf-8")


def main() -> None:
    patch_registry()
    patch_bedrock()
    patch_turn_input()
    patch_session()
    patch_dynamic()
    patch_tasks()
    patch_binding()


if __name__ == "__main__":
    main()
