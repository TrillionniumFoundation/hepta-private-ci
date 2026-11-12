# VERIFY-7 repair and remaining gates

The new engineering repairs are implemented and locally validated. Scientific
and product blockers are **not all closed**; `BLOCKERS.json` preserves each
remaining requirement and prohibits an all-closed declaration.

## Repaired defects

- Checker reports now bind the actual goal, checker/version, property,
  assumptions, frontier, state version and authority. A rehashed outer label
  cannot hide a forged report. Reconciliation cannot replay effects.
- Sequential v1 metered wall durations must fit the corresponding event,
  phase and run spans, including the train fit. The old auditor accepted zero
  elapsed time despite 5,723,063,662 ns of original metered wall charges.
- The matched scorer isolates its own state and each authenticator boundary.
  A retained alias attack formerly changed one cluster/p=0.5 into eight
  clusters/p=0.00390625 and a reviewable gate while canonical bytes stayed
  unchanged. The repaired scorer refuses it; the valid one-cluster value is 0.5.
- Record rereads and iterable projections apply byte/row limits before
  materializing inputs, including post-audit replacements and generators.
- A bounded provider adapter binds frozen source/run/attempt/job identities,
  preserves original API hashes, excludes names/conclusions from forecast
  features and retains every UNKNOWN outcome.

Original and repaired source, complete reproduction output, counterexamples
and raw targeted tests are retained in the corresponding ZIP archives.

## Executed verification

The final combined working source passed **284 tests**. All ten changed Python
source hashes stayed unchanged through those tests and three original-data
CLIs. The CLIs validate the original 132 trajectories/1,033 events/1,034 costs,
repeat the saved-label information decomposition, and admit the real frozen
provider capture. They add no actor, model fit, prediction or SQL query.

Repository `just fmt`, scoped Ruff and diff checks passed. All ten changed
Python ASTs match their retained executed bytes after final formatting; per
repository instructions no local tests reran after formatting. Source binding
and full stdout are retained in `FINAL_LOCAL_VALIDATION.zip` and readable
`SOURCE_BINDING.json`. This is not an exact-commit full-CI assertion.

The new source stack is #6120 (integrity), #6121 (callbacks) and #6122 (provider).
Each source needs its own CI. All added files obey the unchanged 512,000-byte
blob limit; no policy or allowlist was weakened.

## Actual provider evidence and limits

Complete Windows logs now confirm 242/255/260 tests at the earlier distinct
packaging/auditor/attribution heads. The original Windows artifact at source
`b4717e6` was downloaded and independently checked. Its real remote attribution
report confirms paid conditional increment 1/120 in train/cal/confirm and zero
under shift, with 60 probes. These old-head results are not transferred to the
new repairs. Full original logs, artifact bytes and hash review are retained.

The new prospective roster freezes **12 actual queued jobs**, with actual
run_attempt=1 and source/head/run/job fields read from the full GitHub API.
Initial bytes precede a separate follow-up capture; both are retained unchanged.
The follow-up has **0 known terminal labels and 12 UNKNOWN**. Query elapsed
cost was not measured and stays null; capture UTC timestamps do not replace it.
No job or rerun was launched to manufacture results. Capture order is retained
metadata, not authenticated chronological or independent-source proof.

CI-property labels are same-provider observations, not independently adjudicated
business labels. Independent business tasks remain **0**. No accepting default
verifier, artificial trust key or source-cluster claim supplies missing custody.

Still required: new-head platform/blocking CI, exact frozen natural terminal
receipts, independently sourced business trajectories and terminal adjudication,
current evaluator trust, full physical cost, fair four-policy execution, and
held-out calibration/net benefit after input/model changes. HOLD / NoUpdate /
NONE remains the only supported decision.


## New exact-source macOS CI

Original logs retained in `NEW_SOURCE_CI_ORIGINALS.zip` bind integrity head
`3c2a347` to 269 passing tests and combined provider head `e23e343` to 284
passing tests. Both complete the observation study and print
CONSISTENT_COMPLETE_RECORDS; the attribution command also completes. These are
new source-specific macOS results, not a full blocking/platform-matrix pass.
Original decoded bytes are reconstructed from the retained connector response
content without adding or removing log newlines. The snapshot in
`NEW_HEAD_JOBS.json` remains historical and unchanged.
