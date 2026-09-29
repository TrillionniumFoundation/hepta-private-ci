# platform.types qualification integrity — 2026-09-29

This continuation stays on PR #1001 and preserves its source history. It does
not change Prompt V1/V2 bytes, HPTC limits, registry generations, numeric
rounding, immutable lookup indexes, owner final-use policy, dependencies or
compiler versions. The preceding optimization layers remain the implementation
baseline; they are not reimplemented here.

## Resource attempt publication

`run_platform_types_resource_qualification.sh` now owns one attempt at a time
within its output directory. A directory lock prevents concurrent publishers
from mixing samples and reports. A lock surviving an interrupted process is a
reconciliation requirement, not permission to steal the output directory.

Before admission to an attempt, baseline/output path and hard-link aliases
reject without modifying the baseline or another active attempt. After taking
the lock, the runner invalidates its previous report, raw samples and logs. It
runs the real verifier tests and real native benchmark, writes the gate result
to a temporary report, and publishes `report.json` only after final head/tree
and tracked-worktree checks. A failed admitted attempt removes its success
report and retains `status.json` with the failing stage and nonzero exit code.
Earlier diagnostics are not a current qualification receipt.

Optional baseline comparison now binds the complete interpretation and
publication method, not only the benchmark executable. The report names and
hashes the benchmark executable, allocation observer, Python gate and shell
runner. A change to sample interpretation, threshold enforcement, source
fencing or report publication therefore invalidates an older baseline even
when the measured Rust workload is unchanged.

This output lock is an evidence-publication guard, not a product lock or runtime
owner. Nothing here authenticates a registry snapshot, qualifies a host, mints
an approval, or grants execution/activation authority.

## Consumer execution evidence

All 24 consumer commands remain mandatory and continue after an individual
failure so later diagnostics survive. The evidence builder validates their
exact names and order instead of trusting a count of 24 rows alone.

The eight native-test commands additionally require a nonempty completed libtest
summary. Quoted summary text, compiler-only output and zero-test success are not
execution evidence. The final builder independently recomputes each passed-test
count from the retained log, compares it with the count file, and commits both
hashes into the existing V2 execution record. A stale, missing, boolean or altered
count cannot turn successful command exits into `qualified=true`.

The evidence-builder's own positive fixture uses the same paired `running N
tests` marker and terminal summary required from retained command logs. A
separate orphan-summary regression proves that an otherwise plausible terminal
line without its active execution marker cannot qualify. Guard tests therefore
exercise the rule they assert instead of succeeding through an obsolete fixture.

The existing runner tests now execute the real parser and evidence builder over
isolated Git fixtures. Their native command stand-ins emit real-shaped zero-test
success, compiler-only success and tampered-count cases. They do not substitute
a prearranged error exit for the behavior under test. These are runner/verifier
regressions, not executions of the Rust consumer suites.

## Existing qualification lanes

The existing deep workflow runs the schema entrypoint separately for source-head
and deterministic synthetic merge. That entrypoint now executes consumer,
nonempty-test and resource-guard regressions before native code generation and
retains `qualification-guards.log` in the schema receipt's hash inventory.
All previous schema, semantic-capacity, native, consumer, rustdoc, MSRV, Miri,
fuzz, provenance and final-outcome requirements remain. No alternative success
workflow or author-issued qualification path is introduced.

The native bounded-capacity regression covers oversized owned reservations,
ordinary owned allocation reuse, borrowed construction and cloned accepted
values. It proves the Rust-visible retained `String`/`Vec` capacity remains
within the declared logical maximum; it is not a claim about allocator
bookkeeping, physical heap footprint or process RSS.

Reproduce the non-native guards from the repository root:

```sh
python3 -m unittest discover -s scripts -p 'test_platform_types_consumer*.py' -v
python3 -m unittest discover -s scripts -p test_platform_types_nonempty_tests.py -v
python3 -m unittest discover -s scripts -p 'test_platform_types_resource*.py' -v
```

The resource tests contain synthetic measurements. Their success does not prove
an allocation improvement or a latency ratio. The actual release-mode benchmark,
full final-head and merge receipts, independent review, product-owner current-use
checks and target-host/operator acceptance remain separate evidence obligations.
