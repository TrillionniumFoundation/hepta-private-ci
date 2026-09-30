#!/usr/bin/env python3
"""Align the send-permit migration with the product-executor hardening pass.

The product hardening pass moves the cleanup obligation to `effect_possible`
with an async durable transition before the final-use token is entered. The
following effect-guard migration still matched the older body and attempted to
reintroduce a synchronous guard call later. Update both embedded source and
replacement blocks so the linear AppServerSendPermit is added without moving or
weakening the durable cleanup fence.

This construction-only fix is removed with every source-writing migration from
the immutable candidate.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/runtime-codex-effect-guard-fixup.py"

SEND_BUDGET = '''            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
'''
SEND_BUDGET_WITH_FENCE = SEND_BUDGET + '''            thread_guard.effect_entered().await?;
'''
SYNC_FENCE = '''        thread_guard.effect_entered();
'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    total_budget_count = text.count(SEND_BUDGET)
    hardened_budget_count = text.count(SEND_BUDGET_WITH_FENCE)
    legacy_only_count = total_budget_count - hardened_budget_count
    if hardened_budget_count == 2 and legacy_only_count == 0:
        pass
    elif hardened_budget_count == 0 and legacy_only_count == 2:
        text = text.replace(SEND_BUDGET, SEND_BUDGET_WITH_FENCE)
    else:
        raise RuntimeError(
            "expected exactly two uniformly legacy or uniformly hardened "
            f"send-budget blocks; total={total_budget_count}, "
            f"hardened={hardened_budget_count}"
        )

    sync_count = text.count(SYNC_FENCE)
    if sync_count:
        if sync_count != 2:
            raise RuntimeError(
                f"expected two obsolete synchronous cleanup fences, found {sync_count}"
            )
        text = text.replace(SYNC_FENCE, "")
    elif text.count("thread_guard.effect_entered().await?;") < 2:
        raise RuntimeError("effect-guard migration omitted the durable cleanup fence")

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
