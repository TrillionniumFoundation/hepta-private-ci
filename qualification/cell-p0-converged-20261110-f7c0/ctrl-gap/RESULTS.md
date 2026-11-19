# CTRL frozen train40 candidate-gap diagnostic: native output recovered

## Result and adoption boundary

The original frozen diagnostic produced a complete, hash-verified native file bundle. Its wrapper receipt records child exit code `0`, unchanged input and source bytes, and `NoUpdate`. The current-state retained-text probes add **one** scorer-matching candidate: original availability is `86/160 = 0.5375`; availability after the frozen A/B probes is `87/160 = 0.54375`, a descriptive increase of **0.625 percentage points** on the existing training states.

Of the 74 originally uncovered states, one is assigned to numeric formatting (B) and 73 are assigned to another recorded state of the same source and field (C). C does not count toward current-state availability. It demonstrates a historical within-source difference, without establishing that the ordinary caller can reach that state, that a READ action caused it, or that a selector will choose the answer.

This is a train-only diagnostic. It contributes **zero new independent tasks**, evaluates no policy efficacy, installs no actor candidates, and admits no production update. Model inference, OCR, training, and new observation counts are all zero. See the original [RESULT.json](RESULT.json), [NATIVE_RECEIPT.json](NATIVE_RECEIPT.json), and the checked [AUDIT_VALIDATION.json](AUDIT_VALIDATION.json).

## Exact identity

- Frozen diagnostic implementation: [`13de10b55b0f16cf1548dab193fbb8ac11d3b4cd`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/13de10b55b0f16cf1548dab193fbb8ac11d3b4cd), PR [#5767](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5767).
- Evidence parent: [`602cd5695092a82f876fd122243b971b5b88eee8`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/602cd5695092a82f876fd122243b971b5b88eee8), PR [#5772](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5772).
- Diagnostic operation: `ctrl-fit40-gap-20261111-f7c0ded86bcc-v1`, on host `ai395`.
- Native stage: `/home/qq/ctrl-fit40-gap-20261111-f7c0ded86bcc-v1`.
- The three frozen modules are `scripts/ndu_real_runtime/candidate_coverage.py`, `candidate_coverage_legacy.py`, and `candidate_gap_diagnostic.py`. Their exact byte hashes are in the native receipt and result. The executed carrier is preserved as [EXECUTION_WRAPPER.py](EXECUTION_WRAPPER.py), SHA256 `9ae984d4a1764c1e211391cd67c03db779a72adcd35238f7f7cf3950047f20c9`.
- The native result is 7,920 bytes, SHA256 `bb6a773d3f6403e68662a3f26c0b86e7571a578334aa3de6c91862a471409309`; the native receipt is 4,357 bytes, SHA256 `32f2bd60f1ea5a61c3a581947f70a804eec6a85185fafb35e9dc67a86a9b5f7d`.

The original request, collection, and records were checked before and after the native invocation with equal size, SHA256, and filesystem version tokens. The records remain the pinned 9,496,351-byte file with SHA256 `43f1c63fe378a783cc57d475ad1841c4235b7d1eaa335c2e0fdd2126f73d1a85`. The three diagnostic source files likewise have equal before/after size, hash, and version. The frozen legacy validator performed two rounds, each validating all 60 original source files before and after its own analysis. The raw input content and dispatch payload are excluded from this bundle.

## Observed categories and denominators

| Scope | Registered sources | Observed sources | Missing sources | Unique states | Already covered | A frozen regex | B numeric format | C other recorded state | D insufficient evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 40 | 40 | 0 | 160 | 86 | 0 | 1 | 73 | 0 |
| Date | 40 | 17 | 23 | 68 | 34 | 0 | 0 | 34 | 0 |
| Total | 40 | 23 | 17 | 92 | 52 | 0 | 1 | 39 | 0 |

There are 200 original rows and 160 unique states, including 40 duplicate state rows. Every registered source has four distinct states. Consequently the overall source-equal mean happens to equal the raw state proportion: the mean of 40 source-level rates is `0.5375` before the probes and `0.54375` after retaining A/B proposals. This arithmetic does not make the 160 states independent tasks.

The registered denominator remains **40 sources** for every field. Date has only 17 observed sources and total only 23; their full-40 source-equal rates are correctly `null`. No missing-source denominator was removed or replaced with an observed-only denominator. Company and address have no observed states in the original baseline. They were not evaluated by this date/amount diagnostic.

Categories use the frozen priority `covered → A → B → C → D`. A and B proposals are generated from public candidate text, boxes, origin, and field before the reference is accessed. The only new match is B, meaning the fixed numeric projection produces a canonical scorer match. The diagnostic does not establish semantic correctness or successful selection. C contains 73 states after higher-priority categories are assigned; the report does not provide a B-versus-C overlap count. D being zero is not evidence that original pixels or a complete OCR inventory were available.

Historical producer identity remains unauthenticated. The state inventory is derived from source group and the raw feature-state digest inside the frozen file, rather than an independently preregistered state list. These 40 registered training source groups support a development diagnosis; they are not a new sealed confirmation set.

## Budget and truncation accounting

The frozen probes retain the original candidate prefix. They have a 64-proposal limit, a 128-total-candidate limit, a per-state 4,096-scanned-match limit, and an 8,192-character input bound. Their deterministic order is family, original candidate index, then regex match order.

| Count across all 160 states | Date | Total | Overall |
| --- | ---: | ---: | ---: |
| Scanned matches | 242 | 6,559 | 6,801 |
| Unique proposals encountered | 6 | 2,313 | 2,319 |
| Retained proposals | 6 | 1,807 | 1,813 |
| Known proposals dropped by the proposal limit | 0 | 356 | 356 |
| Known proposals dropped by the total-candidate cap | 0 | 150 | 150 |
| States with any diagnostic budget censoring | 0 | 13 | 13 |

The proposal accounting closes: `2,319 = 1,813 + 356 + 150`. No scan-censored flag was recorded. The 6,801 scanned matches are summed over states and do not indicate a violation of the per-state 4,096 limit. Proposal counts are metadata proposals summed over states, not independent task counts.

All 13 budget-censored states belong to the total field. The report does not cross-tabulate those states against original coverage, so it does not support a claim that 13 originally uncovered states were truncated. `D_with_budget_censoring = 0` follows from D being zero; it does not make the probe exhaustive. The baseline's **historical generator truncation remains unknown for all 160 states**, separately from these 13 observed probe-budget events.

## Baseline and file verification

The exact native [BASELINE_BEFORE.json](BASELINE_BEFORE.json) and [BASELINE_AFTER.json](BASELINE_AFTER.json) differ only in `execution.cpu_seconds` and `execution.wall_seconds`. After excluding those two timing values, all parsed content is identical, including input pins, source hash identifiers, registered and observed state counts, per-source coverage, and the source-equal baseline `0.5375`.

The result binds both exact baseline file hashes. The wrapper receipt also binds the result, both baselines, stdout, and stderr by full SHA256 and size. Each of those files was recovered as a complete single binary chunk, with EOF, chunk hash, size, and local SHA256 checked. The result and receipt reads additionally supplied their previously observed immutable-read version tokens. [READBACK_BINDINGS.json](READBACK_BINDINGS.json) records all six returned file versions and distinguishes these two read modes. Stdout reports completion with the same categories as the JSON result; stderr is empty.

## Two transport timeouts and the recovered native evidence

There were two `h_process_start` API calls for **one** idempotency key: the initial submission and one exact same-key, identical-parameter reconciliation. Both API responses were `MCP request timed out`. A bounded inventory query returned a pending, incomplete snapshot; its continuation exceeded the observation deadline without a partial authoritative inventory. No durable job ID or authoritative process-terminal status was recovered.

The immutable historical snapshots are [TRANSPORT_ATTEMPT_1.json](TRANSPORT_ATTEMPT_1.json) and [TRANSPORT_RECONCILIATION_2.json](TRANSPORT_RECONCILIATION_2.json). Their `UNKNOWN` fields describe the observations available when they were written. Initial file probes had found no output at that moment. The second snapshot already contains a positive receipt metadata probe, but its generic interpretation text still mentions absence; that sentence is not a later absence claim. This report and the recovered bytes supply the completed file evidence without rewriting either historical snapshot.

The wrapper receipt records native start `2026-11-11T00:08:27.580328Z` and finish `2026-11-11T00:08:28.510100Z`. Its own status is `completed` and its child exit code is `0`. Thus **native diagnostic file completion is observed; authoritative durable process-terminal status remains unknown**. The transport responses alone neither prove failure nor establish terminal completion. No new execution key was introduced after uncertainty, and the separate V4 business operation `ctrl-native-macro-collect-e802-20261110-v4` was never replayed.

During transport uncertainty, a read-only local recovery reached 36 verified 65,536-byte chunks, totaling 2,359,296 of 9,496,351 record bytes. The full original record file was not recovered locally, and no local diagnostic invocation occurred. Further recovery stopped when the native file bundle was found; already-issued reads settled. [RECOVERY_STATUS.json](RECOVERY_STATUS.json) keeps that incomplete recovery distinct from the native result. Its chunk bytes, original training text, private request/collection content, and dispatch payload are excluded from the publication bundle.

## Costs and next engineering target

The diagnostic entry reports 0.8713547510560602 wall seconds and 0.866136647 CPU seconds, excluding imports, launcher, final serialization, and transport. The wrapper reports 0.9297721888870001 wall seconds and 0.013945428999999999 CPU seconds; wrapper CPU covers only the parent process and excludes the child. Baseline timings are already inside the diagnostic entry scope and must not be summed as independent costs. Full physical cost, communication/recovery cost, and billing remain unmeasured. Zero model/OCR/training calls does not mean zero total cost.

The frozen proposal implementation has now been run without modification. Its result supports prioritizing an owner-bound observation-transition experiment: a source/field-matched current state, an explicitly recorded information-acquisition action, its reachable successor state and candidate inventory, and a fixed scorer and selection baseline. Such an experiment would test whether the 73 C assignments can become available through the ordinary runtime. This remains a hypothesis and was not launched in this run.

The single B match can motivate a later fixed, reviewed normalization integration with semantic collision and candidate-budget checks. The current result does not justify promoting the proposals or claiming net task benefit. The present adoption action is **NoUpdate**.
