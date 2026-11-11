# Frozen-credit raw feedback budget gate — 2026-11-11

**Reference-only fix; scientific/production status: HOLD_NO_GO / DENY_ALL.**

## Exact audited source (CI source before this evidence-only archival commit)

- PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6025
- Parent PR #6024: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6024
- Tested commit: `376909580dc090f016bb87ae38e4773c1d27f921`
- Tested Git tree: `52a5ca2dd44df5ba6a0f8a954c5b2320a1ce03e5`
- Original study.py blob: `2fe1a41b99b3b4a081267655da76e2eb36416ae9`
- Patched study.py blob: `6ed7bd52aab7483475d375780f6e33de86cdc635`
- New test blob: `20bfbbb7cfe22da4e6f1b840332d2ef7feff38d0`

## Fault and exact change

`frozen_credit_from_prefix` previously filtered declared post-cutoff feedback without charging the size limit on **raw scanned entries**. Repeating future-only receipts arbitrarily many times could cause an unbounded iterator traversal while the later forensic validator saw zero entries. The changed loop refuses on raw feedback index 65,536, matching the 65,536 forensic feedback and memory-prefix caps. It does **not** authenticate the timestamps or guarantee suffix isolation for arbitrary over-budget traffic: exceeding the resource envelope is an explicit refusal, not an efficacy decision.

## New deterministic test matrix and hosted evidence

- 65,536 future-only entries equal the empty observed prefix.
- 65,537 future-only entries are rejected after precisely 65,537 yielded items; a longer lazy iterator is not exhausted.
- One valid in-window feedback + 65,535 future-only entries preserves the exact credit view.
- One valid in-window feedback + 65,536 future-only entries fails closed.
- No synthetic test measures live Source/Action/Feedback ownership, real downstream utility or model learning.

Original action: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43113372212
- Python job: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43113372212/job/130834954054, **76/76 tests passed**, unit test runner measured 0.041 s; GitHub job elapsed approx. NaN s. Full original log: `FROZEN_CREDIT_RAW_BUDGET_PYTHON_CI.log`.
- Native Q24 reference job: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43113372212/job/130834953648, **101/101 tests passed**, Cargo test runner measured 0.29 s; GitHub job elapsed approx. NaN s. Full original log: `FROZEN_CREDIT_RAW_BUDGET_Q24_CI.log`.
- Those hosted job durations include runner overhead and cannot be used as model-training speed or full resource cost. CPU seconds, RSS, GPU/energy, inference, model storage, remote Owner work, and real task costs were **not measured**. Model/data/config/seed: no external neural model, model dataset, or training seed; the deterministic 1-action reference test config fixes cutoff=10, decay=1, max_lag=10, and 65,536 max raw feedback records.

## Remaining gates

The fix is limited to a shadow reference API and the native Q24 regression suite. Production owner-attested source and time, full action effects, future independent B, real NoUpdate/Adopt and subsequent task C, cold recovery, full seven-lineage costs, MEM service deletion and Core×NDU 2×2 all remain **HOLD_NO_GO**. The broader blocking-ci includes an independently failing Blob-size policy setup; a success from this focused workflow does not waive it. Do not auto-merge, deploy, select weights or grant production owner authority.
