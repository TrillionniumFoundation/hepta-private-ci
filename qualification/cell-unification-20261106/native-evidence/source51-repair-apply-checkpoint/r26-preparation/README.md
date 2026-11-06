# Source51 r26 native project gate preparation

This is an inert execution plan, not a native qualification result. The current
candidate is `native-run-r26-template-v2.py`. FROZEN is False and all 15 future
source51/apply identity and closure bindings are None. The original source50 r24
full project result remains failed100 (1,561 PASS, 3 FAIL, 0 TIMEOUT; 3 reported
skips); source50's r25 workspace preparation was never started.

## Execution order

After the separately reviewed source50-to-source51 apply-only job has naturally
closed at zero, the runner validates the new root manifest and all native source
bytes/Git blobs/modes/tree/dual locks. It then executes the original Python32
runner suite, the original strict gate for CLI/exec-server/network-proxy/external
agent migration, and the original full four-package test command with retries0.
The complete 1,564 previous binary/name IDs are an acceptance check after the
full original test run, never a filter. Default features, original inner budgets,
two build jobs/two test threads, existing debug0 profile and >20 GiB threshold
remain. The outer native project watchdog remains the separately bound 9600s.

## Source50 lock inheritance

The original seven lock artifacts and natural successful controller terminal
remain pinned to source50 commit 1fdd647b0ecb235530e8b88bbea45b3d3762906f/tree
ea48acf562499192a25e05ae28926a32632dee62. The generated historical manifest keeps
source_commit:null. It is checked against the separate source50 root manifest,
not against source51. Inheritance requires an exact Git tree delta containing
only the already reviewed fake_bwrap.rs and http_proxy.rs existing Rust files,
unchanged Git modes, unchanged all other Git tree entries, and byte-identical
Cargo.lock and MODULE.bazel.lock. No source51 Bazel invocation is claimed.

## Apply input contract

The apply-only complete schema is hepta.source51-apply-complete.v1. It must bind
the source_before_commit/tree, new source_commit/tree, complete source manifest,
delta manifest, source postguard, natural zero outer terminal and unchanged
dual locks. Its Rust/Bazel/fixfmt execution flags must be false. The full root
manifest also identifies source_parent_commit. The delta schema is
hepta.source51-apply-delta.v1, with two before/after five-field source rows and a
candidate.patch pin relative to the archived input directory. The template
resolves this into an evidence-relative pin without rewriting the delta bytes.

## Preservation and review

The complete original r24 run_phase/environment/source guards and 16 common
functions are unchanged. Python/test readers differ only in schema labels;
Starting/Summary/status parsing is unchanged from the corrected r24 parser.
Original return codes are persisted before log/resource hashes and derived
acceptance. Source mismatch or readback failure cannot create completion or
start the next phase. There is no patch application, staging, dependency
regeneration, workspace, formatter or automatic retry in this runner.

The first inert preparation is retained. V2 corrects the delta patch's relative
input path, adds the exact source_parent_commit contract and disables external
diff/textconv in the new tree-delta query. No version has been imported/executed.
Unknown bindings must be filled only from actual closed artifacts, then undergo
an exact binding review before FROZEN can be changed. The next workspace gate
is r27 and remains a separate future command.
