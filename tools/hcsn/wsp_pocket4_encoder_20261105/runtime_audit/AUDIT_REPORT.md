# Independent HeptaRuntime WSP review, 2026-11-05

## Result

The exact source head `bc38fb82244b946907886704b3c677bf00761cb9` has now passed
both an independent review of its retained native-certificate records and
official complete exact-head CI. These were pending in PR #94's creation text.
The source remains an open draft stacked on #93; this review does not establish
merged-main behavior, model efficacy, actual trading value, or production admission.

No production model, admission guard, service or order was changed. Existing
source worktrees were read-only. No new Rust patch was invented in the absence
of a demonstrated contract violation.

## Source and execution identity

| Item | Observed value |
| --- | --- |
| PR #92 | open draft, `e7a2688acc5504412d45160a08d2bf864be6b650` |
| PR #93 | open draft, `990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7` |
| PR #94 | open draft, `bc38fb82244b946907886704b3c677bf00761cb9` |
| #94 parent | #93's exact source head |
| Certificate protocol | `7a361d5a451f9eba6b1d722e9596a4b30ba0b03fbf2aba057207c0a867b8dbd8` |
| Local qualified binary | `692ea01fa5dd3a6e33cb343aee4d7c41a6ae4f015a352b2d2c42afd4655532ec` |
| Live binary size | 382,495,848 bytes |

A fresh read-only Desktop job compared all 270 `src/`, Cargo and rustfmt source
files against their Git blob hashes from the remote #94 tree. There were zero
differences and zero extra source files. The actual binary retained the same
complete SHA256. This confirms current artifact/source identity; it is not a
reproducible-build proof or a complete compiler/OS/dependency closure.

The remote readback is retained in `PR94_BUILD_READBACK.json` and references
durable job `1a1aa2113ac-fc05-3dbd`, which completed with exit 0. It cost
1.322954846 CPU seconds and 1.323988725 wall seconds within the remote script;
dispatch and tool latency are outside that interval.

## Independent record review

`verify_native_records.py` verified 112 retained evidence-file hashes and the
519 source entries bound between build and execution manifests. It verified
all command log hashes and both focused weight test summaries: 87 passed,
zero failed, two pre-existing ignored entries in each configuration.

For each of fits 11, 23, 37, 53 and 71, the reviewer reexecuted the frozen
Fraction reference from every original supplied witness row. It compared
the fresh result with the frozen reference and actual native MCP reply.
Every exact rational scalar/vector and all 735 center F64 encodings match.

| Fit | Complete witness rows | Native and recomputed verdict |
| --- | ---: | --- |
| 11 | 4,437 | F64_NECESSARY_SYSTEM_INFEASIBLE |
| 23 | 4,427 | F64_NECESSARY_SYSTEM_INFEASIBLE |
| 37 | 4,146 | F64_NECESSARY_SYSTEM_INFEASIBLE |
| 53 | 3,776 | F64_NECESSARY_SYSTEM_INFEASIBLE |
| 71 | 4,672 | F64_NECESSARY_SYSTEM_INFEASIBLE |
| Total | 21,458 | All match |

All 21 retained control RPCs were inspected directly. Positive, equality,
wrong-sign, subnormal, zero-multiplier and malformed-input outcomes match their
frozen contracts. The review reuses the previously independent Fraction
algorithm; it does not claim a new independent mathematical implementation,
new native execution, hidden-feature recomputation, or new scientific sample.

The review cost 8.695100011 CPU seconds, 8.698478773 wall seconds and 47,640 KiB
process peak RSS. Its own source digest and all read record digests are retained
in `PR94_RECORD_REVIEW.json`. It did not modify the reviewed records.

## Official exact-head CI

[Run 41966037157](https://github.com/TrillionniumFoundation/hepta-runtime/actions/runs/41966037157)
completed successfully on its first attempt at 04:45:12 UTC, validating #94's
exact head. The independent reviewer fetched the complete decoded job log and
verified `SOURCE_HEAD_SHA` rather than inheriting #92 or #93's pass status.

| Configuration | Passed | Skipped |
| --- | ---: | ---: |
| All features | 1,816 | 41 |
| No default features | 1,796 | 29 |

All 22 executed job steps succeeded, including both check/Clippy
configurations, format, descriptor-relative safety, control-plane and X230
regressions, release build and release parser/ZIP checks. The
prospective-merge job was conditionally skipped and is not qualified here.

Decoded UTF-8 log: 844,833 bytes; SHA256
`fc235b118bb45a28bf2ea21a599af588f6deaf6ce733ec5fbc81028343f001f8`.
The log digest includes the leading BOM and original escape sequences.
The compact readback is retained in `PR94_CI_AUDIT.json`.

## Bounded code findings and remaining risks

1. **Exact update budget:** the F32 budget checks represented original/replacement
   bytes with an exact integer square and finite F64 radius decomposition.
   Source authentication remains a separate artifact-layer check. The qualified
   radius applies to one patch, excluding bias, environment changes and a chain
   of cumulative updates. No new contradiction was found in the bounded review.

2. **Exact continuation proof:** positive separation is checked before squaring.
   The roundoff-relaxed system is separately distinguished from ideal-real
   infeasibility. Finite inputs, row/byte limits, two-worker admission and an
   asynchronous cancellation-safe worker permit are present. The result rules
   out copying all supplied continuation orderings in one original 147-weight
   ball. It does not rule out useful partial changes or other representations.

3. **Semantic provenance remains open:** hashing a supplied hidden state or
   teacher table does not authenticate the program that produced it. The native
   tool deliberately reports `hidden_or_teacher_program_reexecuted=false` and
   `external_source_authentication=false`. A production agent needs the actual
   encoder/cell-state/teacher replay or an authenticated equivalent provenance
   boundary before treating this certificate as a fact about another checkpoint.

4. **Bellman scope:** the native planner handles a finite, topologically ordered,
   risk-neutral additive DAG. It has first-maximum action semantics and explicit
   branch fees. It neither discovers the environment law nor proves a global
   neural optimum, general NDU/FBSDE optimization, or utility under unknown
   correlated costs. Matching an exposed finite graph is software equivalence.

5. **Recovery scope:** the journal writes durable intent before isolated edits,
   reruns the complete guard on completed retries, and forces rejection plus
   exact parent reconstruction for interrupted requests. This is immutable
   artifact recovery, with no live pointer activation. Source loss or tampering
   explicitly leaves recovery unverified. The existing qualified scenarios
   include process SIGKILL, not host power loss. Background recovery,
   cross-version reconciliation and distributed production cutover need their
   own contracts and evidence.

6. **No model-repair pass:** software CI and this arithmetic record review cannot
   reverse the separately failed anchored five-fit IID/OOD efficacy gate. They
   support rejecting one infeasible full-copy objective and safely evaluating
   future candidates, not stopping traditional training on the claim that an
   autonomous weight-space optimizer already replaces it.

## Concrete update justified now

The creation-time pending claims for #94's no-default gate, full local native
corpus, independent final record review and complete official exact-head CI
can be replaced with these source-bound outcomes. Keep the PR draft and retain
the mathematical, scientific and production limitations. No merge or deployment
is justified by this review alone.
