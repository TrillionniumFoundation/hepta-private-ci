# VERIFY-6: retained evidence and incremental information

The original study's initial ACK and later combined readback differ in both
time and available ACKs. Most of the observed conditional-probability resolution
in that fixture is already available from the later free ACKs. Buying resource
presence adds a smaller sample increment; no causal policy benefit follows.

| Original probe cohort | First ACK | All three free ACKs | ACKs plus paid presence | Paid conditional increment |
| --- | ---: | ---: | ---: | ---: |
| Train / calibration / confirmation | 0 | 4/45 | 7/72 | 1/120 |
| Declared mixture shift | 0 | 0 | 0 | 0 |

These are empirical conditional-probability variances from the original saved
labels, not new Brier scores, trained comparisons, p-values or population bounds.
Only the 60 probe trajectories enter attribution; the 72 repeated policy-arm
trajectories are not extra samples. Ten template groups share one generator.
Independent business tasks added: **0**. HOLD / NoUpdate / NONE.

## Reviewable changes

- Parent #6061 packaging repair: `4a08232dbf90f4cbfa995dcaa29607cbd097762e`.
  The 683,590-byte original ZIP is losslessly split into bounded parts; original
  hash `941750dfede43cbf37706191d7c870ba0a9a4c67967eb6a150589ed2366faffb`
  and all 337 member CRCs match. The blob policy and allowlist are unchanged.
- Auditor #6102: `3ace899a1c61bfda1a46074a5dacc655dda22b09`. The original
  132 trajectories / 1,033 events / 1,034 costs pass internal consistency checks.
- Attribution #6103: `b4717e6db7dbb933abb473752ca8f6223638e8a8`. Exact rational
  decomposition separates the later free ACKs from paid resource presence.

Both new modules only read saved records. The original-run audit/attribution
performed **0 actor/checker/model executions, fits, predictions or SQL queries**.
Matching records do not authenticate feature provenance, clocks, source
independence, host/goal authority or terminal business truth. An incomplete
archive refuses analysis. The deterministic acceptance predicate remains intact.

## Validation and originals

The final targeted working-source call passed **18 tests** (13 audit + 5
attribution); the four executed Python files are retained in
`LOCAL_VALIDATION.zip`, with published-byte/AST binding in `SOURCE_BINDING.json`.
An earlier 259-test combined working-candidate run is preserved separately;
later audit edits and the fifth attribution test mean it is not a final-head
whole-suite claim. Counts overlap. Repository `just fmt`, scoped Ruff and diff
checks pass; all four Python ASTs survive formatting unchanged. Per repository
instructions, local tests did not rerun after final formatting.

`final-original-audit.json` and `final-original-attribution.json` are complete
read-only outputs on the unchanged original run. `VALIDATION.json` records
commands, source scope, initial setup failure, rejected force-push attempt,
ordinary Git credential failure and subsequent successful ordinary connector
publication. No rejected action was silently retried unchanged.

`PARENT_CI_ORIGINALS.zip.part-*` and `CI_ARCHIVE_PARTS.json` retain complete
original API payloads/logs from the parent source `d0570e5d...`. Concatenate
parts in manifest order and verify every part and whole-archive byte/hash before
opening. The same reconstruction pattern is documented in the parent's README.
All part blobs remain within the unchanged 512,000-byte repository limit.

Those original parent logs verify 242 tests and the same 132-trajectory study
on Windows, macOS and Ubuntu. They are platform repetitions, not independent
source datasets. Whole-repository CI still has original failures. Direct jobs
show terminal failures despite the parent run-list wrapper's stale queued
status; both snapshots are retained. The blob-size rejection is repaired by
the packaging commit; baseline merge/native failures and a cargo-deny log
retrieval error are separately retained without invented causes.

Every new source head needs its own CI; prior platform results are not inherited.
No production activation or scientific promotion is requested. Remaining gates
include independently sourced prospective business trajectories, complete
terminal adjudication, full physical cost, and source-level held-out calibration
and policy benefit under input/model changes.


## New-source macOS CI checkpoint

Complete original logs in `NEW_SOURCE_CI_ORIGINALS.zip` verify the packaging
head `4a08232` passed 242 tests, auditor head `3ace899` passed 255 tests plus
CONSISTENT_COMPLETE_RECORDS, and attribution head `b4717e6` passed 260 tests
plus the auditor and attribution commands. These are distinct source-bound
macOS executions. Other platforms/full blocking CI are not qualified by them.
The attribution report is written as an artifact, not printed into its job log;
its separate original-run result is retained above. No fixture repetition is
counted as new independently adjudicated tasks. At the latest direct reads the
packaging blocking workflow returned no jobs, so no remote blob-policy pass is
inferred; the local unchanged blob checker passes.
