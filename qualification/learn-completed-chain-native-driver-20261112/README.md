# Complete ordinary-path native driver template

This is an uninstantiated execution template. It has not been run on H, and it
does not contain a native or whole-path qualification result.

The reference is the actual `root_448f9bd3_native_tests_v1.py`. The exact parent
roster and nextest configuration were read from source commit
`27bbd027bf02e134755cadb98ccd20d320364ce0`.

## Instantiation

Copy the template to a new immutable driver file, then replace all five markers:

| Marker | Required value |
| --- | --- |
| `__FROZEN_REPO_ABSOLUTE__` | The independent clean H checkout containing the frozen source |
| `__SOURCE_HEAD_40_HEX__` | Its exact Git commit |
| `__SOURCE_TREE_40_HEX__` | Its exact Git tree |
| `__MATCHING_SCOPED_FIX_RESULT_JSON__` | The completed successful scoped-fix record for that same clean source and full tracked-file digest |
| `__NEW_UNIQUE_RUN_ID__` | A new short name such as `root-full-<head8>-v1`; never reuse an earlier output, public-binary, or mount namespace |

The target remains `/home/qq/hepta-learn-ff41-target-f73704ac-v1`. The driver
requires actual UID1000, takes the original exclusive target lock, probes the
Cargo lock without blocking, and refuses a dirty or mismatched source. Its
uninstantiated form refuses before creating an output directory. Source identity
or target-lock failures are failed preconditions, not passed or skipped tests.

The original task environment comes from
`/home/qq/hepta-learn-ff41-tools/env.json`. The driver preserves Rust 1.96.0,
one build job, incremental compilation disabled, offline dependencies, and no
`CARGO_PROFILE_*` override. It records the relevant actual environment and the
environment-file hash.

## Preparation and execution order

Preparation uses actual UID1000. The repository helper builder and its verifier
pin the inference helper; Cargo executable metadata pins both product binaries
to this attempt. A `cargo nextest list --lib --list-type binaries-only` stage
builds the seven library binaries without executing tests. This preparation is
recorded separately and cannot count as native qualification.

Each subsequent Root stage uses `sudo -n env -i`, asserts actual effective UID0,
and invokes the repository's original `just test` recipe through
`scripts/hepta_ci_exec.py`. Ordinary A and both post-A parents each have their
own report, independent of the Root roster.

| Order | Stage | Required coverage |
| --- | --- | --- |
| 1 | `ordinary-a` | Exact ordinary A parent |
| 2 | `ordinary-post-a-adopt` | Exact actual independent-B Adopt parent |
| 3 | `ordinary-post-a-no-update` | Exact completed independent-B NoUpdate parent; not TrainingNoUpdate |
| 4 | `ordinary-whole-cold` | Exact whole daemon and Root cold-recovery parent |
| 5 | `root47` | Every original workflow45 parent plus both missing-acceptance/missing-lock negatives, exactly once |
| 6 | `seven-libs` | All nonignored library tests in the seven explicit packages under UID1000 |
| 7 | `fullsource` | `python3 -m unittest discover -s qa/b4-no-bypass -p test_*.py -v` |
| 8 | `fullcallers` | `python3 scripts/verify_hepta_callers.py verify --root REPO` |

The whole-cold exact ID is:

```text
neuron_generation_current::initial_root_tests::ordinary::cold_process::ordinary_main_cold_recovers_completed_c_after_actual_daemon_and_root_retirement
```

The two additional Root IDs are:

```text
authority_host_service::generation_publication::refusal::tests::acceptance::root_completed_publication_missing_acceptance_cannot_be_backfilled
authority_host_service::generation_publication::refusal::tests::acceptance::root_completed_publication_missing_lock_is_not_repaired
```

The template compares the actual workflow45 list with the complete embedded
reviewed list. An equal-size replacement list fails. Its whole-cold configuration
check requires the original 30-second times 16 watchdog and zero retries. It
does not change repository nextest settings, product deadlines, 500ms frames,
or request budgets. Every native invocation has `--retries 0 --no-tests fail`;
the original execution-recorder watchdog remains 7200 seconds per invocation.

## Failure and evidence handling

A failed build, test, report collection, QA command, or caller check is retained
and does not suppress later stages. A helper preparation failure leaves explicit
unavailable binary paths; it never selects an old prepared binary environment.
Raw helper Cargo logs are copied even when preparation fails.

Before every native round, existing JUnit files are renamed as excluded prior
reports. Fresh raw reports are retained even when collection rejects them.
Missing or ambiguous fresh reports cannot pass. Root-parent coverage requires
exact names and counts with no skipped or extra cases. The actual repository
collector additionally checks the clean source execution record, timestamps,
runner counts, and XML. Synthetic files from template validation are never
provided as native evidence.

Each stage records its command, exit status, timestamps, raw stdout/stderr, and
source identity. The final manifest hashes all retained records. Cleanup is
limited to this attempt's mounts and ownership restoration of task target,
records, and nextest output. Existing evidence and source are not deleted.

`all_stages_passed` requires every stage plus source identity and cleanup to
pass. A successful compile or test-binary listing cannot make that value true.
The stage records remain the source for qualification scope and failure
classification; nothing here reclassifies a signal, I/O error, or missing report
as a timeout.

## Validation performed locally

The companion Python validator performed 58 driver checks, including exact
roster comparison, phase order, failure continuation, prior-report exclusion,
wrong/duplicate/skipped parents, missing/ambiguous reports, failed-report
retention, and source mutation. It invoked only local read-only `git show`
commands; process launching was blocked during the synthetic checks. No H,
Cargo, Rust, nextest, sudo, or product executable ran. Temporary synthetic XML
was deleted. Native and whole-path counters remain zero for this template.
