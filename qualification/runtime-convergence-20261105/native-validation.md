# Runtime convergence: native validation and source boundaries

## Current composition

The tested first-wave implementation is `facba0d32c1cd0e8163a6186d7ba91fa311f2e2e`,
tree `38f3e6e9f2e3fa3605e720a4a287bbd75d25695b`. The current reviewed source
is `432421d0d9ca9d82c5e3401fe3425af29131505a`, tree
`d93136bb5e318ea4131bfb5cb0b9ac9310f27d1d`, retaining the two mechanical
Clippy changes described below under a separate identity. It retains the R3/R2
integration, the three native formatter changes and the source-only Windows
ConPTY conversion repair, then adds the reviewed desktop issuer/writer fix.
The original desktop revocation test is unchanged at blob
`a8c7698a8bf6a58f35d6bcec57470df0efee6f55`.

The exact facba checkout verified all 5,309 tracked Rust files. Repository
`just fmt --base 4e31abc907f09740d402d1ddef7a1d2fe0a366a6`, its check,
and whitespace checking all passed with no source diff. See
[native-source-manifest.json](native-source-manifest.json) and the actual
[source receipt](native/ai395-desktop-source-attempt2-receipt.json).

The repaired original desktop regression passed 1/1. The unchanged full
four-package suite then passed 813/813, with one slow test and the original
66 skips. All 14 required targets appear as actual passes. The final scoped
Clippy command returned zero. Its scope-checking wrapper stopped on two extra
test paths; that raw blocked receipt is preserved and the exact changes were
reviewed and committed separately. The earlier full-suite failure remains
in this record under its original source identity.

## Execution environment and interpretation

The native work uses the task-owned AI395 checkout and repository-pinned
Rust 1.96.0, just 1.58.0 and cargo-nextest 0.9.143. Commands use the original
`just test` recipe, default features, the unchanged local nextest profile,
two Cargo build jobs, and the original test timeout and one-retry policy.
One retry means at most two executions of a failed test, not two additional
retries or independent experimental trials. An outer job lifetime limit does
not replace a test's timeout.

Missing Clang resource headers and OpenSSL development files were repaired
inside the task directory with matching verified packages. The OpenSSL
runtime files match the installed runtime byte-for-byte. No dependency,
lockfile, TLS backend, feature set, signer requirement, assertion or admission
threshold changed. The prerequisite receipts are
[Clang](native-clang-environment-repair.json) and
[OpenSSL](native-openssl-environment-repair.json).

Each negative control changed only its stated production behavior, retained
the positive tests, and restored the candidate afterward. The first controls
ran on exact `1d87082c0d5afd2b474a2c453ea98005fd540dea` plus the recorded
three-file formatter patch. Each receipt binds the actual positive blobs
and negative variant. Those observations do not silently become tests of the
later Windows or desktop repair. The raw receipts distinguish the harness
exit code from the actual `just test` exit code.

## Four observed negative-control families

| Control | Actual executed result | What the assertion established |
| --- | --- | --- |
| A: restore R3 Agentd transition ordering | Eight selected tests; six failures and two valid-boundary passes | Revision/deadline rejection leaked terminal, context, cancellation or failed-record state |
| B1: remove both complete plan checks | One named failure | Final-holdout owner record count became 1 where 0 was required |
| B2: restore incomplete decision encoding/seal | Two named failures | An altered decision passed integrity; a relabelled signed ineligible receipt reached seven shadow ports and appended Decision sequence 1 |
| C: remove both public lifecycle guards | Two named failures | Public apply/recovery returned topology receipts with generation 1 advancing to 2 |

All four actual test commands returned 100, with behavioral assertion failures
rather than compilation failure. The restored candidate is recorded in every
accepted control receipt. The artifacts are:

- A: [receipt](native/ai395-red-a-attempt3-receipt.json) and
  [raw stderr](native/ai395-red-a-attempt3.stderr).
- B1: [receipt](native/ai395-red-b1-attempt1-receipt.json) and
  [raw stderr](native/ai395-red-b1-attempt1-just-test.stderr).
- B2: [receipt](native/ai395-red-b2-attempt2-receipt.json),
  [raw stderr](native/ai395-red-b2-attempt2-just-test.stderr) and
  [corrected mutation](native/negative-decision-seal-keep-test-import.patch).
- C: [receipt](native/ai395-c-receipt.json) and
  [raw stderr](native/ai395-c-just-test.stderr).

These are native test and fixture observations. The seven ports are shadow
ports; Decision persistence does not establish an external physical effect.
The C failure occurs at the unexpected successful apply receipt, before later
callback/grant assertions. Those unreached assertions are not additional
observed failures. A loop's first panic does not prove that later cases ran.
The stopped-host recovery fixture is an in-process fixture, not a physical
restart qualification.

### Attempts that are not behavioral evidence

A1 stopped while compiling `aws-lc-sys` because Clang's `stddef.h` was missing.
A2 stopped while compiling `openssl-sys` because development files were absent.
Neither ran a test. The first B2 mutation also stopped during compilation:
it removed an import used by the unchanged tests. The corrected mutation
retains the import and removes the same production seal binding. Its later
two assertion failures, rather than the earlier compile error, are the B2
negative evidence. All attempts remain separately recorded under `native/`.

## First complete positive run: real failure retained

The original command was:

```sh
just test --locked -p codex-hepta-agentd -p codex-hepta-runtime -p codex-hepta-intelligence-eval -p codex-hepta-intelligence
```

The exact initial source plus formatter patch ran 813 tests:
**812 passed, one failed, 66 were skipped**. The complete command elapsed
94.95 seconds, including build and startup; the nextest summary elapsed
36.312 seconds. All 13 A/B/C target tests passed,
as individually indexed in
[positive observations](native/first-green-control-positive-observations.json).
The entire package gate nevertheless failed with actual test exit 100.
The [receipt](native/ai395-green-attempt1-receipt.json) and
[complete stderr](native/ai395-green-attempt1-just-green.stderr) retain that
result. The stderr SHA-256 is
`12c6f807607f5716935b70ba01b71a2d887c69733d406045afa8f0964c0b78dd`.

The only failure was the existing
`desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair`.
Revoking the original issuer lease while the successor writer remained live
still allowed desktop policy replacement. Both executions failed the same
original assertion. This exposed a production authority boundary defect;
it was not removed from the suite or converted into an expected failure.

## Desktop repair and required repaired sequence

Exact donor `65f0ad816ffa4724626db3f1c36a20eb7faab61f` changes only
`deployment_desktop.rs`, `deployment_issuer_root.rs` and `deployment_writer.rs`.
Their base blobs and the original test match the failed candidate. The adopted
commit is facba above; unrelated donor history was not imported.

The repair reuses the existing same-owner joint lease boundary. It re-reads the
pinned issuer, checks the current issuer and writer under the same registry
lock, and checks both leases' times and the state epoch before and after the
policy CAS. Existing key ownership, revision, epoch, payload and CAS checks
remain. No new writer, cached-issuer fallback or authority issuer is introduced.
Post-I/O failure still requires reconciliation of the exact durable policy
pair; the repair does not promise rollback of an already completed store.

Source review and exact patch/blob checks are recorded in the
[primary review](desktop-issuer-fence-review.json),
[independent review](desktop-issuer-fence-independent-review.json), and
[source patch](desktop-issuer-joint-fence.patch).
The explicit no-lease helper error changes from `PermissionDenied` to
`Other("no protected lease")` but continues to reject before mutation; the
public root protection checks are unchanged.

The repaired pipeline uses job `1a1aae7d2bc-fc05-488d` and runs:

1. The unchanged original desktop revocation regression on exact facba.
2. The unchanged full four-package command above, including the 13 repaired
   A/B/C targets and the original desktop test.
3. `just fix --locked` scoped to the same four packages, last.

The runner records a separate receipt and raw logs for each attempted stage;
a nonzero stage stops the pipeline. Any fix diff must be reviewed under its own source identity. Tests
are not automatically rerun after formatting or fix, in accordance with the
repository guidance. A genuine new defect or a separately required gate needs
its own explicit evidence record.

### Repaired test results

The [named regression receipt](native/ai395-desktop-regression-attempt1-receipt.json)
records actual command exit zero and 1/1 passed (661 tests excluded by its
named selection). The command elapsed 62.47 seconds, including compilation;
the selected test summary elapsed 0.065 seconds. Its SHA-256 is
`4b133f93c90f5e27910a8d729b9b89ffdffb01d0bb659e491406bde484f06c19`.

The [full repaired receipt](native/ai395-green-attempt2-receipt.json) records
actual command exit zero, 813/813 passed, one slow test and 66 skips. Command
elapsed time is 38.06 seconds; nextest summary elapsed time is 36.320 seconds.
All 13 original control targets plus the desktop regression appear in the
actual pass list. Its SHA-256 is
`f47d72c3930e2575b567fb8acaeb999f6696fab34bdcdd81ccd56b542fd81588`.

These receipts name exact facba and its new formatter/source receipt. They
qualify the tested source, not the earlier failing initial tree or a future
source diff from scoped fix.

### Scoped fix: successful command, preserved scope blocker, reviewed adoption

The [original fix receipt](native/ai395-first-scoped-fix-receipt.json) records
`just fix` exit zero after 220.736 seconds, followed by a successful formatter.
The wrapper returned 1 with state `fix-blocked` because two existing Agentd
test files outside the initial 13-file inventory changed. Its
`source_changed_by_fix=false` compares only those 13 controlled files; it is
not evidence that the complete tree stayed unchanged. The raw receipt SHA-256
remains `ae54b470fd20e079d33602f60abffc3f130816586974b297cebe2f6ea3704d3b`.

The complete [native diff](native/ai395-first-scoped-fix.patch) removes two
last-use `clone()` calls from a plain lease record and rewrites one
`match Ok/Err(no-op)` as equivalent `if let Ok`, preserving the original
assertion. No production source or assertion/fixture value changed. Root and
an independent reviewer checked exact original/after blobs and the complete
unfiltered changed-path output. The [independent review](first-scoped-fix-source-review.json)
and [source adoption record](post-fix-source-adoption.json) bind the exact two
files to commit 432421 and the true stacked merge
`eed6541df0add428add8e2d9ab2cbd54a961abeb`.

The review resolves only the known source-scope discrepancy for the next native
handoff. It does not rewrite the blocked receipt, transfer the facba 813/813
result to a new whole tree, or close release qualification. The first suite
was not rerun after fix. The separate required second-wave suite will compile
and test its explicit new merged source.

The actual [post-fix alignment receipt](native/ai395-reviewed-postfix-alignment-receipt.json)
records clean exact F and E checkouts, 5,309 and 5,314 tracked Rust blob
verifications respectively, unchanged controlled source and successful full-R3
formatter checks. Its SHA-256 is `64be8b15396564e49ac3b6f4dd6ecd7b9c623a40c113e45d4f1b742779f6a42e`. The
original blocked receipt remained byte-identical before and after alignment.

## Original platform and product gates remain separate

The original Windows run on a20 passed 22 earlier selected tests, then failed
compiling the inherited ConPTY error conversion before Agentd tests. The later
directory-acquisition attacks did not execute. The source-only repair is now
present, but a supplemental donor workflow cannot close the original workflow.
The [current-source CI snapshot](current-source-ci-observation.json), captured
at 2026-11-05 09:39:17–09:39:18 UTC, records implementation 432421 original
Windows run 41999779676 with no allocated runner and no executed steps. Its
architecture and blocking runs have no jobs yet. The independent API reads are
not an atomic snapshot; they establish no queue root cause. The prior
[original qualification](windows-original-qualification.json) and historical
[08:41 queue review](windows-runner-queue-review.json) retain their own source
identities and timestamps.

No native unit/package result here establishes the full real-provider task,
current-authority physical effect, authenticated terminal Outcome, process-loss
recovery, production receipt readback, adaptive net benefit or complete Control
lifecycle. Public topology remains DENY_ALL; failed efficacy admission retains
no-update. Original exact-head, ordered synthetic-merge, platform, stress,
cross-crate E2E and independent release gates are unchanged.
