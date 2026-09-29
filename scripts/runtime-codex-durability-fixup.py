#!/usr/bin/env python3
"""Small idempotent corrections applied after the durable-owner migration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / "codex-rs/hepta-agentd/src/lane_b_runtime.rs"
    text = path.read_text(encoding="utf-8")
    old = '''        if !matches!(record.phase, RunPhase::Admitted)
            && record.context_digest.is_none()
        {
            return Err(AgentRunError::Persistence(
                "durable post-admission run omitted context binding".to_string(),
            ));
        }
'''
    new = '''        if matches!(
            record.phase,
            RunPhase::ContextAttached
                | RunPhase::Dispatched
                | RunPhase::AbortedBeforeEffect
                | RunPhase::Cancelling
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate
        ) && record.context_digest.is_none()
        {
            return Err(AgentRunError::Persistence(
                "durable post-context run omitted context binding".to_string(),
            ));
        }
'''
    if old in text:
        text = text.replace(old, new, 1)
    elif "durable post-context run omitted context binding" not in text:
        raise RuntimeError("durable context invariant block missing")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
