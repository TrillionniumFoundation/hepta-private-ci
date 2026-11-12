# Exact Cell data-reader native attempts on the recovered cloud executor

These two attempts ran as actual UID 1000 on cloud executor `74d784910ce8`,
with rustc 1.96.0, cargo-nextest 0.9.151 and just 1.51.0. They exercise Neuron
physical data-reading components; they do not run Root service parents or a
complete ordinary learning iteration.

## Source and observed results

| Source / tree | Actual result |
| --- | --- |
| `847269df0a0bf746fd52e82208acbec3917482fb` / `17237f4ef9318afa0226a2919d4de8415818c466` | Test compilation failed with E0425 at `cell_queue_cost_journal_tests.rs:203`: the existing fixture did not import the mechanically extracted `cell_journal_codec::apply_record`. Native command exit 101; 0 tests; no JUnit. |
| `cf73d06e1a20664f428980efe23e299d7b52a78d` / `2b65d34c4855243cd7aa3154bbf7ab3af33002c1` | The one-line fixture import repair compiled. The original command exited 0 and all nine selected tests passed with zero retries. The fresh JUnit has 9 tests, 0 failures, 0 errors and 0 skipped cases. |

Both source snapshots were clean and unchanged before and after their actual
commands. `fixture-import.patch` is the complete one-line repair; no assertion,
product behavior, lock boundary or operation deadline changed. Actual
`just fmt --base 847269df0a0bf746fd52e82208acbec3917482fb` and
`git diff --check` passed before committing the repair.

Both invocations used:

```sh
just test -p codex-hepta-neuron --lib --locked \
  -E 'test(original_cell_data_) | test(published_feature_readonly_)' \
  --retries 0 --no-tests fail --test-threads 2 \
  --success-output final --failure-output final
```

Seven `original_cell_data_*` cases exercised physical history after current
authority is unavailable, actual writer-lock release, corruption without
repair, torn tails and witness lag, scope/request/record bounds, descriptor
aliasing/unlinking, and empty original files. Two existing
`published_feature_readonly_*` cases exercised exact acknowledged readback
and refusal of unacknowledged or empty state. The 221 other Neuron tests were
outside this explicit filter; they are not counted as executed or qualified.

## Original collector failure and subsequent read-only reconciliation

The first collector guessed that Nextest's JUnit would be under the configured
`CARGO_TARGET_DIR`. This invocation instead wrote it under the source
workspace's `codex-rs/target/nextest/local/junit.xml`. Thus the initial
collector exited 1 even though the actual native command had exited 0.
The original collector record, including `junit: null`, remains unchanged.

The existing fresh report was then copied without rerunning any test or
changing the source. Its filesystem modification timestamp falls inside the
recorded native invocation. Its UUID
`ce3b0d80-afd7-414c-a5d1-c325a7805abf` matches the command log. Its exact nine
test names equal the selected source set, with no failed or skipped cases.
The report is 2,549 bytes, SHA256
`f808f9a30c52294727b37246ad79b7eb157292e260e2bb49e7b63720ab46df4b`.
`collection-reconciliation.json` records this later observation separately
from the original recorder result. No new test invocation substitutes for a
failed run.

## Retained originals and limits

`original-records.tar.gz` preserves both complete command logs, both original
run manifests, the recovered JUnit and reconciliation, the exact second-run
recorder script, and the task-local tool-install records. Every member and
the archive have byte counts and SHA256 in `original-records-inventory.json`;
every member was extracted and compared with its original bytes.

`source.bundle` retains the actual repaired Git source and requires the
original local 82 commit. The earlier evidence directory contains the
bundles needed to restore that prerequisite. `source.json` records its exact
head, tree, prerequisite, size and SHA256. The evidence commit is not the
executed source.

The physical reader supplies data, not new publisher authority, an Observer
signature or Root's independent ACK. This component result does not prove a
persistent fence across arbitrary rollback of all Root storage. The complete
ordinary positive, NoUpdate and daemon-plus-Root cold-restart counts remain
**0 / 0 / 0**.
