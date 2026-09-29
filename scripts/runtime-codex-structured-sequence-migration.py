#!/usr/bin/env python3
"""Replace textual ordering checks with a structured runtime.codex attempt sequence."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def attempt(text: str) -> str:
    marker = "structured_attempt_stage_sequence_matches_effect_protocol"
    if marker in text:
        return text
    state_anchor = '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AbortedBeforeEffect;
'''
    stage_model = state_anchor + '''
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AttemptStage {
    Admitted,
    PayloadFrozen,
    Authorized,
    DurablePrepared,
    OwnerCommitted,
    EffectEntered,
    Started,
    Terminal,
    Quarantined,
    AbortedBeforeEffect,
}

pub trait AttemptState {
    const STAGE: AttemptStage;
}

macro_rules! attempt_states {
    ($($state:ty => $stage:ident),+ $(,)?) => {
        $(
            impl AttemptState for $state {
                const STAGE: AttemptStage = AttemptStage::$stage;
            }
        )+
    };
}

attempt_states!(
    Admitted => Admitted,
    PayloadFrozen => PayloadFrozen,
    Authorized => Authorized,
    DurablePrepared => DurablePrepared,
    OwnerCommitted => OwnerCommitted,
    EffectEntered => EffectEntered,
    Started => Started,
    Terminal => Terminal,
    Quarantined => Quarantined,
    AbortedBeforeEffect => AbortedBeforeEffect,
);
'''
    if state_anchor not in text:
        raise RuntimeError("structured attempt sequence state anchor absent")
    text = text.replace(state_anchor, stage_model, 1)
    impl_anchor = '''impl<State> Attempt<State> {
    #[must_use]
    pub fn identity(&self) -> &AttemptIdentity {
'''
    stage_impl = '''impl<State: AttemptState> Attempt<State> {
    #[must_use]
    pub fn stage(&self) -> AttemptStage {
        State::STAGE
    }
}

''' + impl_anchor
    if impl_anchor not in text:
        raise RuntimeError("structured attempt sequence impl anchor absent")
    text = text.replace(impl_anchor, stage_impl, 1)
    test_anchor = '''    #[test]
    fn exact_typestate_path_binds_owner_and_terminal_identity() {
'''
    test = '''    #[test]
    fn structured_attempt_stage_sequence_matches_effect_protocol() {
        let identity = identity();
        let payload = identity.payload_digest;
        let dispatch = Digest32::of_bytes(b"dispatch");
        let admitted = Attempt::new(identity).unwrap();
        let mut stages = vec![admitted.stage()];
        let frozen = admitted.freeze_payload(payload).unwrap();
        stages.push(frozen.stage());
        let authorized = frozen
            .authorize(Digest32::of_bytes(b"authority"))
            .unwrap();
        stages.push(authorized.stage());
        let prepared = authorized.prepare_durable(dispatch).unwrap();
        stages.push(prepared.stage());
        let committed = prepared.commit_owner(7, dispatch).unwrap();
        stages.push(committed.stage());
        assert!(!committed.effect_may_have_happened());
        let entered = committed.enter_effect();
        stages.push(entered.stage());
        assert!(entered.effect_may_have_happened());
        let started = entered
            .started(StableId::new("turn-1").unwrap())
            .unwrap();
        stages.push(started.stage());
        let terminal = started
            .terminal(Digest32::of_bytes(b"terminal"))
            .unwrap();
        stages.push(terminal.stage());
        assert_eq!(
            stages,
            vec![
                AttemptStage::Admitted,
                AttemptStage::PayloadFrozen,
                AttemptStage::Authorized,
                AttemptStage::DurablePrepared,
                AttemptStage::OwnerCommitted,
                AttemptStage::EffectEntered,
                AttemptStage::Started,
                AttemptStage::Terminal,
            ]
        );
        assert_eq!(terminal.owner_revision(), Some(7));
        assert_eq!(terminal.turn_id().unwrap().as_str(), "turn-1");
    }

''' + test_anchor
    if test_anchor not in text:
        raise RuntimeError("structured attempt sequence test anchor absent")
    text = text.replace(test_anchor, test, 1)
    return text


def remove_textual_order_test(text: str) -> str:
    start = '''#[test]
fn cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start() {
'''
    if start not in text:
        return text
    begin = text.index(start)
    next_test = text.find("\n#[", begin + len(start))
    if next_test < 0:
        return text[:begin].rstrip() + "\n"
    return text[:begin] + text[next_test + 1 :]


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/runtime_codex_attempt.rs", attempt)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs", remove_textual_order_test)


if __name__ == "__main__":
    main()
