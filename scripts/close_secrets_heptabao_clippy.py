#!/usr/bin/env python3
'''Materialize deterministic strict-Clippy fixes for secrets.heptabao.

This script is development-only and is invoked after the semantic materializer.
It changes no qualification state and is intentionally idempotent.
'''
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"strict-Clippy materialization anchor missing: {label}")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        if result.is_err() {
            self.reschedule_claim(&mut claim, result.as_ref().unwrap_err())
                .await?;
        }
''',
        '''        if let Err(error) = &result {
            self.reschedule_claim(&mut claim, error).await?;
        }
''',
        "reconciliation error reschedule",
    )

    text = replace_once(
        text,
        '''    async fn consume_kv_v2_with_authbus_sqlite<E: BaoAuthBusEvidenceProvider>(
''',
        '''    #[expect(
        clippy::too_many_arguments,
        reason = "host, durable owner, exact read and evidence are separate trust inputs"
    )]
    async fn consume_kv_v2_with_authbus_sqlite<E: BaoAuthBusEvidenceProvider>(
''',
        "SQLite product ingress argument contract",
    )

    boxed_lazy = '''    historical_result(operation.clone())
        .unwrap_or_else(|| Err(BaoProductHostError::OutcomePending(Box::new(operation))))
'''
    boxed_eager = '''    historical_result(operation.clone())
        .unwrap_or(Err(BaoProductHostError::OutcomePending(Box::new(operation))))
'''
    unboxed_lazy = '''    historical_result(operation.clone())
        .unwrap_or_else(|| Err(BaoProductHostError::OutcomePending(operation)))
'''
    if boxed_lazy in text:
        text = text.replace(boxed_lazy, boxed_eager, 1)
    elif unboxed_lazy in text:
        text = text.replace(
            unboxed_lazy,
            '''    historical_result(operation.clone())
        .unwrap_or(Err(BaoProductHostError::OutcomePending(operation)))
''',
            1,
        )
    elif boxed_eager not in text:
        raise SystemExit(
            "strict-Clippy materialization anchor missing: historical pending result"
        )

    text = replace_once(
        text,
        '''    base.checked_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .unwrap_or(u64::MAX)
        .min(maximum)
''',
        '''    base.saturating_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .min(maximum)
''',
        "bounded retry delay",
    )

    TARGET.write_text(text, encoding="utf-8")
    print("materialized secrets.heptabao strict-Clippy closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
