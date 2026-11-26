#!/usr/bin/env python3
"""Treat worker timeout as a stricter ceiling, never as an admission rejection."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    deadline = ROOT / "codex-rs/hepta-infer-worker-host/src/native_deadline.rs"
    text = deadline.read_text(encoding="utf-8")
    old = '''        let budget = Duration::from_millis(deadline_ms - wall_at_anchor_ms);
        if budget > maximum_budget {
            return Err("runtime.codex admitted deadline exceeds the worker profile ceiling".into());
        }
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms,
        })
'''
    new = '''        let owner_budget = Duration::from_millis(deadline_ms - wall_at_anchor_ms);
        let budget = owner_budget.min(maximum_budget);
        let effective_deadline_ms = wall_at_anchor_ms
            .checked_add(u64::try_from(budget.as_millis())?)
            .ok_or("runtime.codex effective deadline overflow")?;
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms: effective_deadline_ms,
        })
'''
    if old in text:
        text = text.replace(old, new, 1)
        deadline.write_text(text, encoding="utf-8")
    elif "let owner_budget = Duration::from_millis" not in text:
        raise RuntimeError("absolute deadline ceiling source anchor absent")

    tests = ROOT / "codex-rs/hepta-infer-worker-host/src/native_deadline_tests.rs"
    text = tests.read_text(encoding="utf-8")
    old = '''#[test]
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
    new = '''#[test]
fn worker_profile_may_shorten_but_never_extend_the_owner_deadline() {
    let capped = NativeDeadline::from_absolute(
        1_000,
        61_000,
        Duration::from_secs(10),
    )
    .unwrap();
    assert_eq!(capped.deadline_ms(), 11_000);
    assert!(NativeDeadline::from_absolute(
        1_000,
        1_000,
        Duration::from_secs(10),
    )
    .is_err());
}
'''
    if old in text:
        text = text.replace(old, new, 1)
        tests.write_text(text, encoding="utf-8")
    elif "worker_profile_may_shorten_but_never_extend" not in text:
        raise RuntimeError("absolute deadline ceiling test anchor absent")


if __name__ == "__main__":
    main()
