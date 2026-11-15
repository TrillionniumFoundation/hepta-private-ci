# Reviewed small legacy source integrations

Each incoming tip is merged normally after a fresh preview against the current
local head. Small/clean deltas are reviewed as code; historical PASS records do
not establish results for the combined source. Remote and protected HIA refs
are not changed by this local work.

## Independent v1 scorer

Incoming `0f8091d6f27b1f81eac08f1a1f3383a952a4ab80` adds the standalone model-free
audit, tests, explanation and a historical receipt. Review covered the complete
scorer, bounded reference-subset matching, exact frozen episode/method roster,
PNG bytes, score and cost reconciliation. No model/network job is introduced.

A concrete cache bug was reproduced: after accepting a 20x20 PNG, the auditor
accepted the same digest against a later 21x20 reference. The cache had stored a
reference-specific validity flag. It now stores only the pinned PNG's intrinsic
digest, format and dimensions, and rechecks each reference. Decoding uses the
same bytes that were hashed. Positive-to-negative and negative-to-positive cache
regressions both pass. The complete focused suite passes 13 tests without skips.

The original source-pinned historical receipt remains unchanged; its private
evidence archive was not supplied or rerun. The new checks do not revise the
frozen scientific result or authorize promotion. Exact hashes/test logs are in
`legacy-small/independent-v1-audit.json` and its companion log.

## NDU v2 confirmatory statistics

Incoming `f5a605255bca5a300a6c524e8206e8f0cc13d6c3`. Reviewed complete production module and tests. Requires fixed 12-method roster, at least three seeds, full source/seed/method denominator, score/cost completeness, pinned registration and cohort firewall. Uses fractional CVaR and 15 paired source-cluster bootstrap contrasts with Bonferroni intervals. Missing/over-budget observations retain zero quality and severe loss; all paths keep model_promotion_authorized false. CLI defaults retain 128 sources and 2000 bootstrap draws; synthetic unit overrides are not production results.

The fresh preview against `a6b77d82aba0d0f85c99e72910e4184ecec09262` has the exact reviewed source delta;
all incoming files retain their bytes. The focused suite passes 10 tests.
Hashes, command and log are retained under `legacy-small/confirmatory-v2`.

## NDU v2 historical source exclusions

Incoming `ec23a433bfa9b47f8c9a6c5fa892dda313569cd5`. Reviewed complete immutable exclusion assembler and both test modules. Fixed external SHA pins and exact 384+256 roster, original IDs, file/RGB digests and dHash distance reject reused sources. Existing nonidentical output is never replaced. Image fixture invokes existing cohort builder with download_images=False and local temporary JPEGs. No weights, outcomes, historical image payloads, model training or real new cohort were executed.

The fresh preview against `94909bc9f0a0bbd906c3d375b9f4decda7e50ffb` has the exact reviewed source delta;
all incoming files retain their bytes. The focused suite passes 15 tests.
Hashes, command and log are retained under `legacy-small/v2-exclusions`.

## Retention-reader evidence shapes

Incoming `4157c319f6031f8a431c13d5254a1f332c6cd6c8` strengthens nested
object/list checks and per-episode error handling. Missing evidence stays UNKNOWN;
malformed evidence, symlinks and unreadable nonmissing artifacts are REJECTED.
The authoritative roster and failed-row denominators remain intact, while later
valid episodes continue to be scored. Original source-plan pins are still checked
before and after reading; an incompatible original plan is refused. All incoming
source and evidence bytes are retained. Four historical test-stream size/SHA pins
were independently checked, mapping the older metadata's original stream names
to the retained `tests-before-oserror` files. That old run remains historical.

The complete focused reader suite passes 13 tests, including recursive shape
substitutions and later-episode real fixture pixel scoring. No real actor campaign
or production adoption occurred. Details and the actual combined-source test log
are retained under `legacy-small/retention-reader-shapes`.

## Bounded NDU worker deadline boundary

Incoming `d1a4caa4cbc50f5a7e2fd3d6063bf296f4b3c75d` adds a future warm-worker
supervisor and model-free tests. Review found no current production Python caller
in `qa`, `scripts` or `qualification`. Its original pickle transport could run
result reconstruction in the parent: a permitted result with a 600 ms restoration
caused a 50 ms deadline to return only after 603 ms. The result was correctly
marked timeout, but the waiting-time claim was not supported.

The merge retains worker reuse, measured startup, failure accounting, timeout
termination/replacement and unreaped-worker refusal. IPC now accepts bounded
builtin data (including bytes/tuples/null), with no reconstruction callbacks:
1 MiB wire, 4096 values, depth 32, finite floats and integers up to 256 bits.
The same-interpreter marshal framing is internal IPC, not an artifact format.
Custom objects require callers to export bounded data explicitly; the factory
remains importable/pickleable for spawn. Transfer, validation and cleanup are
charged, while OS scheduling latency and grandchildren remain outside the claim.

All 12 focused tests pass. New regressions cover the slow custom result, exact
builtin/null round trips, oversized progress/results and invalid payload bounds,
including cycles. No model work or external campaign was run. The preserved
reproducer, compatibility note, exact source hashes and test log are under
`legacy-small/hard-deadline`.
