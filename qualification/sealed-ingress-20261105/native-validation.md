# Sealed qualification ingress: native source and execution record

## Exact tested and current source

The current implementation is `0766fc4d5feabea9569d48e7eca4e0a3431bd0f5`,
tree `1cfb78c47f636a60dcfa9968ffd7e44a054d58cc`. It adds only one reviewed
mechanical test-file change from the final scoped fix, with sole parent E below.
The 805/805 result belongs to E; it is not relabelled as a test run on this
post-fix source or a later documentation commit.

The tested candidate E is `eed6541df0add428add8e2d9ab2cbd54a961abeb`, tree
`b8ce8b96a759f522cb7db60027d4844f1b3ad974`. Its ordered merge parents are
`e0b522cd437af1362f8be23f601886b46ec1b063` and the reviewed post-fix
first-wave `432421d0d9ca9d82c5e3401fe3425af29131505a`. At E, all 14 ingress Rust blobs
remain identical to 06ad. The e0b merge retained three reviewed desktop
production repairs; the eed merge adds only the two reviewed mechanical
Clippy changes in existing Agentd tests.

The source-only four-stage handoff remains historical evidence in the original
patches and manifests. Later native formatting is commit
`2516a2d5fe3f7a3778dba3cce4b146c78a84eb80`; the additional current-trust
regression is commit `06ad4a9b48aa28ef6edfc537243f069e2d48eb40`.
The final test blob is `fc084ad5d2f02709f663f95240737860a05a7c9f`.
[native-source-manifest.json](native-source-manifest.json) records all final
14 source blobs, SHA-256 values and the unchanged production-contract blob.
The [pre-fix source manifest](native/source-manifest-before-scoped-fix.json)
preserves the exact 14 tested blobs. The separate
[scoped-fix review](second-scoped-fix-root-review.json) binds the one changed
test blob in the current source; the other 13 remain unchanged.

All four isolated mutation controls have compiled and produced their specified
behavioral assertion failures, with the positive source fully restored after
each control. Q3's first attempt failed compilation and is not behavioral RED;
the same frozen control succeeded after a separately reviewed package-cache
repair. The unmodified full three-package suite and scoped fix are recorded
separately below. The runner binds the successful facba named/full-suite receipts and
the exact original Clippy command result plus independently reviewed two-file
source adoption before using the shared native build target. The earlier
first-wave 812/813 result failed its full gate and cannot satisfy that
precondition.

## Native formatting and complete source inventory

The initial exact source-next checkout verified 5,314 tracked Rust blobs before
and after the caller inventory. Rust 1.96.0 then ran `just fmt` with the explicit
first-wave comparison base, its check, and whitespace checks. Eight ingress
source files changed only formatting. The legal current-trust regression was
subsequently applied and formatted. An additional check against the complete
R3 delta passed, including the inherited Windows PTY repair. There was no extra
full-stack formatting diff.

Actual formatter/source receipts are
[initial source](native/ai395-next-source-receipt.json),
[final trust/format check](native/ai395-next-receipt.json), and
[06ad head alignment](native/ai395-next-head-alignment-receipt.json).
The last receipt records a clean exact 06ad checkout; its identity is not
rewritten to pretend that it ran on the later e0b merge. Exact later e0b and eed source
preparations are separate receipts. The post-fix source adoption preserves
the original `fix-blocked` wrapper result and requires exact clean F/E
checkouts; it never relabels the old 813/813 result as a run on the new first head.

The actual final tracked-Rust caller scan has 83 matching lines in 20 paths.
The original-pattern subset has 72 lines and the extended pattern adds exactly
11 helper matches. The earlier derived 81-line inventory preceded the added
trust regression and used a different expanded pattern; its count is not a
compilation result or an unexplained missing-caller claim. The actual outputs
are [original pattern](native/ai395-next-caller-original.stdout) and
[extended pattern](native/ai395-next-caller-extended.stdout).
Generic V2 uses remain inside the eval crate; the old v1 Agentd use-signing and
selector-signing call sites are migrated. These scans support lexical coverage,
not native execution or physical product acceptance.

The actual [pre-native alignment receipt](native/ai395-reviewed-postfix-alignment-receipt.json)
verifies the clean tested eed checkout: all 5,314 tracked Rust files
(80,662,751 bytes), 14 ingress blobs, two lint test blobs and three desktop
repair blobs match. Its full-R3 formatter check passed. The separate first
checkout is clean 432421; its old test receipts still name facba.

## Current-trust regression and what it isolates

The new first negative case in
`product_runner_binds_estimator_receipts_and_persists_signed_decision` creates
a legal new generator-controller identity while keeping generator and evaluator
distinct. The original principals, keys, evaluation payload and metric roles
remain. Because the signatures bind host trust, the test produces fresh valid
signatures under the new trust and verifies that raw V2 admission succeeds.

The inner decision stays equal to the original published decision, while trust
and authentication identities change. Revalidating the old sealed qualification
must therefore reject the substitution under current trust. The old verifier's
positive control and unchanged publication/release counts remain. This tests
the complete signed-decision equality boundary, not the isolated necessity of
only the trust-digest field. The independent source review is
[current-trust-identity-review.json](current-trust-identity-review.json).

## Frozen execution plan and first-wave handoff

The actual execution plan is [native-round2-gate-v2/plan.json](native-round2-gate-v2/plan.json),
with [runner](native-round2-gate-v2/run_native_round2.py) SHA-256
`46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df`.
The frozen 29-file transport bundle is SHA-256
`1f0301d0c78a9d0d20703c09bf8d2f4cf1591af307cb3faf5f75da50809927f0`.
The earlier `native-round2/` directory preserves the original e0b plan, which
was not executed; it cannot satisfy the reviewed post-fix handoff.

The current runner pins the three original facba receipt hashes and schemas,
actual full four-package command, 813/813 count and fixed 14-name pass set. It
retains the original `fix-blocked`/wrapper exit 1 and Clippy exit zero, and
accepts only the exact reviewed two-file diff under the separate adoption
record. It rechecks both current source trees, ordered commit parents, clean
status and before/after blobs. Parent headers are read directly from Git commit
objects so a shallow checkout cannot hide a real parent. No fetch or history
change is required by the runner.

The [independent gate review](post-fix-native-gate-review.json) is a source and
harness review, not a Rust test result. Runtime receipts below must retain the
tested facba identity, native first F identity and tested second E identity
separately from the later S source and documentation commits.

The frozen preparation inputs retain their original `NOT_RUN`,
`runner_executed=false` and 06ad manifest identities. The
[historical provenance map](historical-provenance.md) resolves original
handoff/caller filenames and records the unavailable exact inputs of the early
semantic plan review. That review does not establish the later executed
bundle's identity; the current independent gate review binds the actual runner
and plan. Current execution observations remain separately recorded below.

## Four isolated mutation controls

Every mutation starts from the final positive source, changes one production
binding, preserves all tests and fixtures, and restores the positive bytes in a
finally path. Native formatting changed the shared helper layout, so Q1's patch
was regenerated with identical mutation semantics; the other three patches
retain their original bytes. Final hashes are in
[negative-controls/manifest.json](negative-controls/manifest.json).

| Control | Removed production binding | Required actual behavioral failures |
| --- | --- | --- |
| Q1 | Complete `SignedEvaluationDecisionV1` equality in shared revalidation | Product runner, Agentd changed metrics, plasticity changed metrics, self-evolution valid V3 substitution |
| Q2 | Qualification evidence/publication IDs in Agentd use-signing bytes | Old use signature must fail for a different legitimate publication |
| Q3 | Qualification identities in the durable per-candidate plasticity commitment | Distinct legitimate publications must not collapse to one proposal commitment |
| Q4 | Qualification identities in selector-signing bytes | Old selector signature must fail for a different legitimate publication |

Q1 must produce four actual named assertion failures, including the legal
current-trust substitution at the first runner assertion. Q2, Q3 and Q4 each
require their one named assertion failure. A failed build, timeout, unrelated
panic, empty selection or setup failure is not an accepted mutation result.
The runner records command exit codes and raw logs separately from its own
success/failure classification, then verifies restoration before the next phase.

A Q1 self-evolution panic at changed metrics does not also observe its later
changed-time-policy case. A Q3 panic at the first unequal-digest assertion
demonstrates commitment collapse, but does not observe the later replay
assertion. Failed cases and the unchanged nextest retry policy are not counted
as additional independent experimental samples.

### Actual Q1 result

The [Q1 receipt](native/ai395-sealed-q1-receipt.json) is SHA-256
`a7fc0b3cf48abeb3d66bd124c553d606c7555f9a63f4c9a679c9a269ed4d88b6`.
Its original `just test` returned 100 after 257.572 seconds including cold
compilation; nextest reported four tests run, zero passed, four failed and
867 skipped by the named selection/profile. The original one-retry policy
remained unchanged. [Raw stderr](native/ai395-sealed-q1-just-test.stderr)
is 53,229 bytes, SHA-256
`eb5ed0ded6dd107295efdc201e20eed43f23ddbb2e200c6c5696f9825556cfd5`.

The four first panics occur at the planned runner current-trust assertion,
Agentd qualification-binding assertion, plasticity qualification-binding
assertion and self-evolution first changed-metrics assertion. The legal raw
trust/metrics admission assertions that precede those points succeeded. Later
time-policy, no-append, counter or correct-signature assertions after each
panic are not counted as observed negative evidence. The receipt records
restoration of all 14 positive blobs, the lockfile and clean exact E source.
The separate [independent Q1 review](q1-native-independent-review.json) accepts
those exact behavioral failures and restoration while retaining the raw
receipt's original review-required state. Default assert expressions do not
print every returned Result; unprinted downstream values are not presented
as direct log observations.

### Actual Q2, Q3 and Q4 results

| Control | Actual original command result | First observed assertion | Restoration |
| --- | --- | --- | --- |
| Q2, attempt 1 | Exit 100; 1 run, 0 passed, 1 failed, 663 skipped | Agentd test line 460 no longer observes the required `Evidence` rejection when the qualification publication changes | All 14 positive source blobs, lockfile, clean exact E HEAD/tree restored |
| Q3, attempt 2 | Exit 100; 1 run, 0 passed, 1 failed, 84 skipped | Plasticity test line 713 prints equal evaluation digests where `assert_ne!` requires distinct publication commitments | All 14 positive source blobs, lockfile, clean exact E HEAD/tree restored |
| Q4, attempt 1 | Exit 100; 1 run, 0 passed, 1 failed, 121 skipped | Selector test line 474 no longer observes the required `Evidence` rejection for another legitimate publication | All 14 positive source blobs, lockfile, clean exact E HEAD/tree restored |

The original receipts are [Q2](native/ai395-sealed-q2-receipt.json),
[Q3 attempt 2](native/ai395-sealed-q3-attempt2-receipt.json), and
[Q4](native/ai395-sealed-q4-receipt.json). Their `just test` elapsed times,
including compilation/startup, are 137.230, 5.533 and 3.143 seconds; nextest
execution summaries are 0.401, 0.415 and 0.543 seconds respectively. Every
control retains the original one-retry policy. The repeated failure is not a
second independent experimental sample. The runner exits zero only after the
expected failure set and source restoration are established; the raw receipts
retain `named-test-failures-observed-review-required`.

Q2 and Q4 default assertion messages do not print the returned `Result`.
The direct observation is the missing expected `Evidence` rejection, not a
printed success or a deployed effect. Q3 reaches the unequal-digest assertion
after both fixture proposal calls return successfully, but its later proposal
comparison, replay, count and owner-anchor assertions are not executed after
the panic. Q2/Q4 later correct-signature positive assertions are likewise not
negative-control observations. Raw stderr and the independent reviews preserve
these limits instead of crediting every assertion in a failed test.
The accepted source/log reviews are [Q2](q2-native-independent-review.json),
[Q3](q3-native-independent-review.json), and [Q4](q4-native-independent-review.json).

### Preserved Q3 build failure and bounded cache repair

[Q3 attempt 1](native/ai395-sealed-q3-attempt1-receipt.json) returned 101 in
2.288 seconds with unresolved import E0432 before any test ran. The frozen
positive E source contains the unconditional helper module and export. The
[cache diagnostic](native/ai395-q3-cache-diagnostic-v1.json) found an older eval
unit whose dep-info omitted that helper and whose cached warning matched the
earlier first-wave source. A retained successful consumer fingerprint is
historical provenance, not a captured current rustc `--extern` invocation.
The compile failure and full positive restoration remain recorded as their own
failed attempt; the original remaining-pipeline invocation stopped there.

The first repair invocation stopped before backup or cleaning because its
initial process guard treated another experiment on the same host as a
conflict. Its [blocked receipt](native/ai395-eval-cache-repair-attempt1-receipt.json)
is unchanged. The independently reviewed second guard resolves the task's
exact target directory: explicitly different targets may continue, while
unknown or overlapping targets still stop the repair. It reads only the
necessary target/cwd information and does not stop other jobs.

The [actual repair receipt](native/ai395-eval-cache-repair-attempt2-receipt.json)
records eight archived old unit artifacts with verified hashes and the sole
cache mutation `cargo clean -p codex-hepta-intelligence-eval` in the explicit
task target. E's source, tree, clean status, Cargo.lock and all pinned original
failure evidence remain unchanged. The repair changes no source, dependency,
feature, profile, timeout, retry, test assertion or frozen negative patch.
The backup manifest, original clean output and independent target/cache
reviews are retained alongside the receipt.

Q3 attempt 2 runs the same frozen runner and plan with only its attempt identity
advanced. Its stderr shows fresh eval compilation from `source-next`, the old
cached warning is absent, and the new
[dep-info](native/ai395-q3-fresh-eval-fcbed-depinfo.d) contains the helper.
The original line-713 behavioral failure is then reached. This separates the
resolved build-cache problem from the actual publication-commitment mutation
result. Q1 and Q2 had already compiled eval from `source-next`; they were not
rerun merely because a different cached unit required repair.

## Positive package gate and final scoped fix

After all four mutations restored successfully, the actual positive command was:

```sh
just test --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
```

The [actual green receipt](native/ai395-sealed-green-receipt.json), SHA-256
`ab6da7188d4354a088025ec0202533c025436d6f7fcf70196913ef24deb82488`,
records command exit zero on exact E. Nextest reports **805 tests run, 805
passed, one slow, 66 skipped** in 36.514 seconds; the command took 131.693
seconds including compilation/startup. The complete
[stderr](native/ai395-sealed-green-just-green.stderr) is 145,782 bytes,
SHA-256 `e2d5640765ed22e4b7b4def6ac2129a4d537e1f3373a098a162acdce3e1a195a`.
It contains 805 actual PASS lines, all seven critical ingress regressions once,
and no failure/retry lines. The original default features, profile, timeout,
retry and skip selection remain unchanged.

The actual final command was:

```sh
just fix --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
```

The [fix receipt](native/ai395-sealed-fix-receipt.json), SHA-256
`cb1f12c6d7e4c09f3e5c6df4a9f9f337d28540bc4e81c7d5c2c9b45ee2b5504c`,
records scoped Clippy exit zero in 46.187 seconds and subsequent formatter
exit zero. The raw state is `fix-complete`, with
`post_fix_source_changed=true` and `tests_rerun_after_fix=false`.
The full tracked changed-path output names only
`codex-rs/hepta-intelligence/src/plasticity_product_tests.rs`.

Its [actual patch](native/ai395-sealed-native-fix.patch), SHA-256
`5e638cfe00ca4e1df56934c765a60089cb11e718e79c54800f2f5eda741d830c`,
removes one final-use `update_id.clone()` in favor of moving the same owned
ID. This preserves all fixture values and assertions. Root independently
applied the patch to GitHub's exact E test blob `3eb615951f7f9a542455f1814eb58ca73859be90`
and matched the actual native output blob `2b85adacb939c778b13f42177467b5959d16b50a`.
The separate S commit records only that one-line change. The other 13 ingress
source blobs and original contract remain unchanged.
The [independent positive/fix review](second-native-positive-and-fix-review.json)
recounts the full raw PASS set, verifies the required seven names, applies the
actual patch to exact E, and checks complete tracked/untracked/staged scope.

The [outer sequence receipt](native/ai395-sealed-remaining-pipeline-v2-receipt.json)
records Q3 attempt 2, Q4, full green, then fix, ending `sequence-complete`/exit
zero. Original failed attempts and cache-guard stops retain their own receipts.
No tests were rerun after fix or formatting, and E's 805/805 pass is not
transferred to S. Package validation does not establish the separate original
CI, production and release gates below.

### Final S source alignment

The [final source alignment receipt](native/ai395-second-postfix-alignment-receipt.json),
SHA-256 `72f596be257474eba63334968754a602d814ad0d18664941e003979f576812f5`,
records clean exact S and its sole E parent. Before moving the local HEAD/index,
the alignment verified that every tracked working-file byte already matched S;
the alignment itself changed no working-source byte. The full 5,314-file Rust
inventory, Cargo.lock and the exact one-file source delta then matched.
The [full Rust inventory](native/ai395-second-postfix-verified-rust-blobs.json)
retains the actual file-by-file identities.

All eleven pinned original named/full/fix/control/outer/scope receipts remain
unchanged and have exact originals in this archive or the first-wave archive.
The first native source remains clean F. The explicit full-R3 formatter check
returned zero on S; neither tests nor scoped fix were rerun. The
[alignment program](native/align_second_reviewed_fix.py) and original receipt
retain the distinction between source alignment and new test execution.

## Separate production and release obligations

The actual signed qualification fixtures, Memory CAS/publication doubles,
synthetic longitudinal windows and ledger-core membership snapshots exercise
structural admission. They do not supply a production holdout provider,
publication authority, complete persisted receipt codec or qualified readback.
Plasticity preserves a digest commitment through its existing owner; the full
returned qualifications remain in memory. No extra writer is introduced.

The default canonical Agentd still requires a durable seven-owner handoff into
the sole App Server spine, authenticated Decision/Outcome composition through
the existing LedgerWriter, and recovery of original execution identities after
process loss. Source fixes and shadow results do not close that task chain.
The broader [convergence target](convergence-target.md) states the accepted A/B/C
direction and the independent product gates; it is not runtime authority.

The contract's exact-head and ordered synthetic-merge evidence, coverage,
fenced-holdout stress, cross-crate E2E, original platform attacks and independent
release requirements remain unchanged. For implementation eed, the original Windows run is
41999788950. The [current-source CI snapshot](../runtime-convergence-20261105/current-source-ci-observation.json)
at 2026-11-05 09:39:17–09:39:18 UTC records no allocated runner and no
executed steps; its architecture and blocking runs also have no jobs yet. The baseline's old ConPTY compilation failure and a separate
supplemental donor workflow cannot be treated as completion of that gate.
There is no new adaptive efficacy admission: retain the accepted predecessor
and no-update whenever independent benefit evidence is insufficient.
