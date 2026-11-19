# Ledger test helper compile repair

The current integration tree contained two byte-identical, unconditional module-level definitions of `closed_ledger_bytes`. This source fix removes the first definition only. All original tests, assertions and helper call sites are preserved.

The exact postimage passed the existing Rust 1.96 formatter/parser with no changes. This receipt is not a claim of native compilation or test-suite success. Required CI must evaluate the resulting published head before any main update or branch deletion.

This commit has one ordinary integration parent. No HIA ref, main ref or branch deletion is part of this change. The ca77 batch remains separately under review.
