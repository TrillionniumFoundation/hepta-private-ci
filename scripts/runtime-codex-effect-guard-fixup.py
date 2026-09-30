#!/usr/bin/env python3
"""Bind the real App Server send capability to the owner-committed typestate.

This pass also carries Agentd's admitted absolute deadline into the private
runtime.codex product binding. The worker converts that deadline to one
monotonic budget; it may not replace it with `now + local timeout`.
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
    raise RuntimeError(f"{marker}: legacy block and migrated marker are both absent")


def native_run_control(text: str) -> str:
    old = '''pub struct NativeIntelligenceRunBinding {
    run_id: String,
    expected_revision: u64,
    context_digest: String,
    envelope_digest: String,
}
'''
    new = '''pub struct NativeIntelligenceRunBinding {
    pub(super) run_id: String,
    pub(super) expected_revision: u64,
    pub(super) absolute_deadline_ms: u64,
    pub(super) context_digest: String,
    pub(super) envelope_digest: String,
}
'''
    text = replace_once(text, old, new, "absolute_deadline_ms: u64")

    old = '''        if expected_revision == 0 {
            return Err("Agentd admitted run revision is zero".into());
        }
'''
    new = '''        if expected_revision == 0 {
            return Err("Agentd admitted run revision is zero".into());
        }
        if receipt.deadline_ms == 0 {
            return Err("Agentd admitted run deadline is zero".into());
        }
'''
    text = replace_once(text, old, new, "Agentd admitted run deadline is zero")

    old = '''        Ok(Self {
            run_id: receipt.run_id,
            expected_revision,
            context_digest,
            envelope_digest,
        })
'''
    new = '''        Ok(Self {
            run_id: receipt.run_id,
            expected_revision,
            absolute_deadline_ms: receipt.deadline_ms,
            context_digest,
            envelope_digest,
        })
'''
    text = replace_once(text, old, new, "absolute_deadline_ms: receipt.deadline_ms")

    old = '''            &binding.context_digest,
            &binding.envelope_digest,
        ))?,
'''
    new = '''            &binding.context_digest,
            &binding.envelope_digest,
            binding.absolute_deadline_ms,
        ))?,
'''
    text = replace_once(text, old, new, "binding.absolute_deadline_ms")
    return text


def native_deadline(text: str) -> str:
    old = '''impl NativeDeadline {
    pub(crate) fn new(wall_at_anchor_ms: u64, budget: Duration) -> Result<Self> {
        if budget.is_zero() {
            return Err("native deadline budget must be positive".into());
        }
        let milliseconds = u64::try_from(budget.as_millis())?;
        let deadline_ms = wall_at_anchor_ms
            .checked_add(milliseconds)
            .ok_or("native deadline overflow")?;
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms,
        })
    }
'''
    new = '''impl NativeDeadline {
    pub(crate) fn new(wall_at_anchor_ms: u64, budget: Duration) -> Result<Self> {
        Self::from_budget(wall_at_anchor_ms, budget)
    }

    pub(crate) fn from_budget(wall_at_anchor_ms: u64, budget: Duration) -> Result<Self> {
        if budget.is_zero() {
            return Err("native deadline budget must be positive".into());
        }
        let milliseconds = u64::try_from(budget.as_millis())?;
        let deadline_ms = wall_at_anchor_ms
            .checked_add(milliseconds)
            .ok_or("native deadline overflow")?;
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms,
        })
    }

    /// Anchor an upstream-admitted absolute deadline to the local monotonic
    /// clock. The local profile is a ceiling only; it cannot extend the owner
    /// deadline or manufacture a fresh budget after queueing/restart delay.
    pub(crate) fn from_absolute(
        wall_at_anchor_ms: u64,
        deadline_ms: u64,
        maximum_budget: Duration,
    ) -> Result<Self> {
        if deadline_ms <= wall_at_anchor_ms || maximum_budget.is_zero() {
            return Err("runtime.codex admitted deadline is already elapsed".into());
        }
        let budget = Duration::from_millis(deadline_ms - wall_at_anchor_ms);
        if budget > maximum_budget {
            return Err("runtime.codex admitted deadline exceeds the worker profile ceiling".into());
        }
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms,
        })
    }
'''
    return replace_once(text, old, new, "pub(crate) fn from_absolute")


def attempt(text: str) -> str:
    anchor = '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AbortedBeforeEffect;
'''
    addition = anchor + '''
/// Linear permission for exactly one App Server `turn/start` call.
///
/// The constructor is private to the owner-committed typestate transition. The
/// type is intentionally neither `Clone` nor serializable; restart recovery can
/// only reconcile the original operation and can never recreate a send permit.
pub struct AppServerSendPermit {
    _private: (),
}

impl std::fmt::Debug for AppServerSendPermit {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("AppServerSendPermit([LINEAR])")
    }
}
'''
    text = replace_once(text, anchor, addition, "pub struct AppServerSendPermit")

    old = '''    #[must_use]
    pub fn enter_effect(mut self) -> Attempt<EffectEntered> {
        self.effect_may_have_happened = true;
        self.transition()
    }
'''
    new = '''    #[must_use]
    pub fn enter_effect_with_permit(
        mut self,
    ) -> (Attempt<EffectEntered>, AppServerSendPermit) {
        self.effect_may_have_happened = true;
        (
            self.transition(),
            AppServerSendPermit { _private: () },
        )
    }

    #[cfg(test)]
    #[must_use]
    pub fn enter_effect(self) -> Attempt<EffectEntered> {
        self.enter_effect_with_permit().0
    }
'''
    return replace_once(text, old, new, "pub fn enter_effect_with_permit")


def execution(text: str) -> str:
    old = '''        let execution_clock =
            crate::native_deadline::NativeDeadline::new(unix_time_ms()?, self.config.timeout)?;
'''
    new = '''        let wall_at_anchor_ms = unix_time_ms()?;
        let execution_clock = match intelligence {
            Some(binding) => crate::native_deadline::NativeDeadline::from_absolute(
                wall_at_anchor_ms,
                binding.absolute_deadline_ms,
                self.config.timeout,
            )?,
            None => crate::native_deadline::NativeDeadline::from_budget(
                wall_at_anchor_ms,
                self.config.timeout,
            )?,
        };
'''
    text = replace_once(text, old, new, "binding.absolute_deadline_ms")

    old = '''        let preparation: Result<(EnteredUseToken, Duration)> = async {
'''
    new = '''        let preparation: Result<(
            crate::runtime_codex_attempt::Attempt<crate::runtime_codex_attempt::OwnerCommitted>,
            EnteredUseToken,
            Duration,
        )> = async {
'''
    text = replace_once(text, old, new, "Attempt<crate::runtime_codex_attempt::OwnerCommitted>")

    old = '''            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            Ok((entered_use, send_budget))
'''
    new = '''            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let attempt = attempt
                .prepare_durable(request_receipt.request_digest)?
                .commit_owner(
                    intelligence_revision.unwrap_or(prepared_revision),
                    request_receipt.request_digest,
                )?;
            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            Ok((attempt, entered_use, send_budget))
'''
    text = replace_once(text, old, new, "Ok((attempt, entered_use, send_budget))")

    old = '''        let (entered_use, send_budget) = match preparation {
'''
    new = '''        let (attempt, entered_use, send_budget) = match preparation {
'''
    text = replace_once(text, old, new, "let (attempt, entered_use, send_budget)")

    old = '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        let attempt = attempt
            .prepare_durable(request_receipt.request_digest)?
            .commit_owner(
                intelligence_revision.unwrap_or(prepared_revision),
                request_receipt.request_digest,
            )?;
        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let attempt = attempt.enter_effect();
'''
    new = '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate either the local abort proof or the linear send permit.
        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let (attempt, send_permit) = attempt.enter_effect_with_permit();
'''
    text = replace_once(text, old, new, "let (attempt, send_permit) = attempt.enter_effect_with_permit()")

    old = '''            send_authorized_turn_start(&mut client, entered_use, turn_params),
'''
    new = '''            send_authorized_turn_start(
                &mut client,
                entered_use,
                send_permit,
                turn_params,
            ),
'''
    return replace_once(text, old, new, "send_permit,")


def app_server(text: str) -> str:
    old = '''async fn send_authorized_turn_start(
    client: &mut RemoteAppServerClient,
    _entered: EnteredUseToken,
    params: TurnStartParams,
) -> std::result::Result<TurnStartResponse, RemoteObservedTypedRequestError> {
'''
    new = '''async fn send_authorized_turn_start(
    client: &mut RemoteAppServerClient,
    _entered: EnteredUseToken,
    _permit: crate::runtime_codex_attempt::AppServerSendPermit,
    params: TurnStartParams,
) -> std::result::Result<TurnStartResponse, RemoteObservedTypedRequestError> {
'''
    return replace_once(text, old, new, "AppServerSendPermit")


def deadline_tests(text: str) -> str:
    if "absolute_owner_deadline_cannot_be_extended_by_worker_timeout" in text:
        return text
    return text + r'''

#[test]
fn absolute_owner_deadline_cannot_be_extended_by_worker_timeout() {
    let deadline = NativeDeadline::from_absolute(
        1_000,
        1_500,
        Duration::from_secs(60),
    )
    .unwrap();
    assert_eq!(
        deadline.remaining_at(Duration::from_millis(100), 1_100).unwrap(),
        Duration::from_millis(400)
    );
}

#[test]
fn absolute_owner_deadline_must_fit_the_worker_profile_ceiling() {
    assert!(NativeDeadline::from_absolute(
        1_000,
        11_001,
        Duration::from_secs(10),
    )
    .is_err());
    assert!(NativeDeadline::from_absolute(
        1_000,
        1_000,
        Duration::from_secs(10),
    )
    .is_err());
}
'''


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/native_run_control.rs", native_run_control)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_deadline.rs", native_deadline)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_deadline_tests.rs", deadline_tests)
    rewrite("codex-rs/hepta-infer-worker-host/src/runtime_codex_attempt.rs", attempt)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_execution.rs", execution)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", app_server)


if __name__ == "__main__":
    main()
