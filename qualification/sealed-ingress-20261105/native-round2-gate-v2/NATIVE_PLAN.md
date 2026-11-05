# Second-wave native validation with reviewed fix adoption

Status: **prepared; second-wave native tests not executed**. This file and
`plan.json` describe the explicitly published second candidate and the limited
reviewed adoption of two first-wave test-source edits. The runner never writes
the first native worktree.

The preserved 14-file checkpoint was published at
`06ad4a9b48aa28ef6edfc537243f069e2d48eb40`, tree
`5b01b96997762e6059827bfb18dc7280a21c4f7e`. All 14 ingress bytes remain
unchanged through the later desktop repair and the reviewed test-source fix.

The first named test and complete four-package suite passed on
`facba0d32c1cd0e8163a6186d7ba91fa311f2e2e`. Scoped Clippy then returned command
exit 0 but changed two test files outside the original 13-file tracking list.
Its actual wrapper result remains `fix-blocked`, exit 1. Root and an independent
reviewer accepted the exact mechanical diff in a separate source-adoption
record; the blocked native receipt was not rewritten.

Root has explicitly supplied current first source
`432421d0d9ca9d82c5e3401fe3425af29131505a`, tree
`d93136bb5e318ea4131bfb5cb0b9ac9310f27d1d`, and second merge
`eed6541df0add428add8e2d9ab2cbd54a961abeb`, tree
`b8ce8b96a759f522cb7db60027d4844f1b3ad974`. The latter's ordered parents are
the earlier second candidate `e0b522cd437af1362f8be23f601886b46ec1b063` and
the new first source.

The [immutable adoption record](first-wave/post-fix-source-adoption.json) is
SHA-256 `1e74cb96735d026305f25cd5991d8e3dcedcd27644b063b8668503c0a6be3442`.
The [actual alignment receipt](native-format/reviewed-postfix-alignment-receipt.json),
SHA-256 `64be8b15396564e49ac3b6f4dd6ecd7b9c623a40c113e45d4f1b742779f6a42e`,
verified 5,309 and 5,314 tracked Rust files respectively, exact clean HEAD/tree,
the unchanged 13/14 file sets, and full-R3 formatting checks. It did not rerun
first-wave tests or fix. The runner rechecks the actual live source before
every second phase; historical alignment alone cannot substitute.

The old 813-pass result remains facba-only. No second-wave Cargo process has
been launched by this work. The original failed `native-green-v1` and the
original scope-blocked fix remain preserved as actual outcomes. The prior
`native-round2` runner/plan bundle is historical; this separate gate-v2 bundle
adds exact schema, command, pass-count and reviewed-source-adoption checks.

## Fixed inputs and execution order

- Initial published PR head: `9f010aae1ae7f7447adc0660748878f6cce9efd3`.
- Initial tree: `1183de36c51ca9ec561b0775a17d783414d60c0f`.
- Native formatting base: `ebdf792c076c1d516ae9f96eec079921ccd1588f`.
- Second worktree: `/home/qq/work/hepta-convergence-20261105-0c901b/source-next`.
- First worktree `/home/qq/work/hepta-convergence-20261105-0c901b/source` and its
  repaired native pipeline must remain untouched. Do not start another Cargo or
  Clippy invocation until root/lifecycle assigns the serial native slot.
- The separately reviewed current-trust test patch has joined the second
  candidate through its actual formatter output. Its original
  patch is `current-trust-identity-regression.patch`, SHA-256
  `d0d305632f7ba71ef88ad9b4f738617b58c5b3902dade922776c57676c731dcd`.
  The applicable patch against the actual native formatter output is
  `current-trust-identity-after-native-format.patch`, SHA-256
  `cf7ff0f8bb48d9d3a939dee971f634add11e370e7190c2150ea8ebdcf62e3e01`.
  Its added and removed source lines are byte-identical to the reviewed patch.
  The subsequent native formatter changed only whitespace in that addition;
  final test blob is `fc084ad5d2f02709f663f95240737860a05a7c9f`. The already
  formatted delta is `current-trust-identity-final-format.patch`, SHA-256
  `d2a944692b42715f0465fbcb708f3fa3e0543638f6ef6488d49317aabba27caa`.

The required order is:

1. Native format/check; apply the reviewed tests-only trust regression against
   actual formatted source; format/check again and freeze the positive bytes.
   These preparation steps are complete in the referenced receipts.
2. Apply and execute each of the four negative controls separately, restoring
   and verifying exact positive bytes after each.
3. Run the complete, unfiltered tests for the three affected packages on the
   restored positive source.
4. Run scoped `just fix` last. Record any changes and their new source hashes;
   format resulting edits if needed, and do not rerun tests after fix/format.

This order supersedes the earlier archived README command block that placed
fix before tests. It follows root's current instruction and repository AGENTS.
If fix changes source, the preceding green result belongs to the recorded
pre-fix bytes. Keep the post-fix identity distinct; never silently attribute
the old green result to new bytes. Exact-head and ordered-parent merge CI
requirements remain unchanged.

## Original entry point, features and budgets

Invoke commands from the second repository root. Its `justfile` sets the
working directory to `codex-rs`. The unchanged `just test` recipe supplies
`RUST_MIN_STACK=8388608` and `NEXTEST_PROFILE=local`; its existing Python runner
invokes nextest with `--no-fail-fast`. Do not substitute direct `cargo test`.

Preserve the first-wave native environment exactly:

- Rust/Cargo `1.96.0`, task-owned `rustup-home-1.96.0`, tool paths and binaries;
- `CARGO_BUILD_JOBS=2` and the shared task `target` directory, with serial Cargo
  ownership across the two worktrees;
- the verified task-local Clang resource-header and matching OpenSSL repair
  environments, including their recorded header/library SHA-256 identities;
- existing inherited Rust flags, wrappers and Cargo profile variables, with
  their values recorded in each receipt.

Do not add or remove features, targets, backend choices, profiles, retries,
test threads or watchdog overrides. The seven new filtered cases inherit the
existing local/default 30-second period, terminate-after 2 and one retry. All
existing overrides for other tests remain in force during the full-package
run. The existing outer durable-job limit is 21,600 seconds; it is a whole-job
bound and does not extend individual test budgets.

Exact source contracts were fetched at the initial published head and saved
under `source-contracts/`. Their Git blobs are:

| Contract | Git blob |
|---|---|
| `justfile` | `a215a76cf407ace9715bca39c20497014e7dd4dc` |
| `scripts/run-nextest.py` | `1ed63abe84267b320cbfb0123a70aac5507f4595` |
| `codex-rs/.config/nextest.toml` | `5e43111fc8a7a79848f00c1838582edde60bd680` |
| `AGENTS.md` | `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a` |

## Formatting and positive snapshot

```sh
just fmt --base ebdf792c076c1d516ae9f96eec079921ccd1588f
just fmt --base ebdf792c076c1d516ae9f96eec079921ccd1588f --check
```

The explicit base is required on a clean published checkout. Preserve the
actual formatter diff and per-file before/after hashes. After the trust test
is integrated and formatting is complete, record the explicit current HEAD,
the complete positive source/fixture hashes, the `Cargo.lock` hash and the
entry/profile contract hashes. The new trust regression must precede the
other negative assertions in the product-runner binding test.

Run `git apply --check` for each control against that actual positive source.
The active native control patch paths and hashes are in
`negative-controls/manifest.json`; the machine-readable commands and failure
witnesses are in `plan.json`. All four controls passed application checks on
the actual 14-file native formatter export plus the reviewed trust insertion.
The complete-decision control was rebased for the formatter's multiline
`Binding` error; its active SHA-256 is
`73dd589ff130e162de3209c67246bfbbbccec4e09d1b08e85e5cea11ddddb7bd`.
The other three patch files retain their original bytes. Recheck all four
immediately before native execution. All four have now also passed independent
apply/check against the final native formatter output, with unchanged tests,
fixtures and inline test suffixes. `final-positive-manifest.json` binds those
14 exact files; its SHA-256 is
`e652b430cf2af22ce8f421288bad0687cb6ba332fa31da696034f1ed9bf7c7da`.
An old unformatted-candidate apply check is insufficient. If context changes,
regenerate only the specified production deletion from the real positive
bytes, inspect the complete diff and record the new patch hash.
Do not use a partial apply, reject hunks, relax assertions or change fixtures.

## Four separate negative controls

### Q1: complete signed-decision binding

Apply `negative-complete-decision-binding.patch`. It deletes only the shared
helper's complete SignedDecision equality guard. Seals, public context,
current signature verification, roles and timing remain intact.

```sh
just test --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence -E 'test(/(^|::)(product_runner_binds_estimator_receipts_and_persists_signed_decision|independently_resigned_metrics_cannot_replace_the_qualified_estimator_evidence|signed_generic_metrics_cannot_replace_the_product_qualification_before_append|valid_v3_resignatures_cannot_replace_published_metrics_or_time_policy)$/)'
```

Require four named behavioral failures. The product-runner case must first
prove valid V2 under the noncolliding new verifier, complete inner decision
equality and changed trust/authentication digests, then fail at:

`reissued current trust must not rebind a published qualification`

The Agentd and plasticity cases must fail because the expected qualification
binding error is absent for validly re-signed changed metrics. The
self-evolution case must fail at the first changed-metrics rejection. That
panic does not independently execute its later minimum-window substitution;
do not claim otherwise. Restore and verify positive bytes before Q2.

### Q2: Agentd publication in the use signature

Apply `negative-agentd-publication-signature.patch`. It deletes only the two
qualification identity appends from the use-signing payload. The later
consumption digest still includes both identities.

```sh
just test --locked -p codex-hepta-agentd -E 'test(/(^|::)(current_use_attestation_binds_the_exact_sealed_publication)$/)'
```

Require the named test to fail at actual evaluate admission: the old use
signature incorrectly accepts another valid sealed publication, so the
expected `AgentdIntelligenceEvaluationError::Evidence` is absent. Restore and
verify positive bytes before Q3.

### Q3: plasticity publication in the durable commitment

Apply `negative-plasticity-publication-commitment.patch`. It deletes only the
two qualification identity appends from the per-candidate evaluation
commitment. Receipt admission and all signatures remain required.

```sh
just test --locked -p codex-hepta-intelligence -E 'test(/(^|::)(durable_proposal_identity_commits_the_exact_qualification_publication)$/)'
```

Require the named test to fail at the first `assert_ne!` on the evaluation
digests after both proposal calls succeeded. The mutation incorrectly
collapses two legitimate publication identities. This panic precedes the
later same-registry replay assertion: it proves the commitment regression,
not an observed replay result from that later branch. Restore and verify
positive bytes before Q4.

### Q4: publication in the independent selector signature

Apply `negative-selector-publication-signature.patch`. It deletes only the
two qualification identity entries from selector signing bytes; receipt
fields, nonzero validation and admission remain.

```sh
just test --locked -p codex-hepta-intelligence-eval -E 'test(/(^|::)(selector_signature_commits_the_exact_qualification_publication)$/)'
```

Require the named test to fail at actual selector admission: another
publication is accepted under the old signature, so the expected
`SelfEvolutionSelectionError::Evidence` is absent. Restore and verify
positive bytes before the full green run.

## Restoration and proof requirements

For each mutation, use the existing native runner's guarded backup/finally
pattern. Save the actual positive production bytes before applying. Capture
the applied diff and require exactly the designated production deletion;
all other bytes, including inline test sections in a production file, remain
identical. Hash all candidate test and fixture files before and after.

After execution, restore the saved bytes only if the current production file
still matches either the known mutated bytes or the original backup. If it
changed unexpectedly, stop and report the conflict rather than overwriting
another change. Do not use generic `git checkout`/`git restore` as the restoration mechanism:
restore only the saved positive bytes after the guarded identity check. The
runner requires an exact clean published candidate before each phase. Verify
positive source/fixture hashes and unchanged
`Cargo.lock` before proceeding to the next mutation.

A nonzero exit alone is never red proof. Require compilation and execution
of every named test, its final named failure, and the asserted behavioral
witness. Compilation/dependency failures, timeouts, zero selected tests and
setup panics do not qualify. Preserve full stdout/stderr, final failure
summary and any emitted JUnit report. Inspect the actual assertion location;
do not count a transient retry line as a final failure.

These controls are deliberate single-deletion mutations of the new positive
implementation, not literal builds of the old baseline. A first assertion
panic does not establish all later subcases in the same test.

## Full green and final scoped fix

After all four restores, run the full three-package tests with no test filter:

```sh
just test --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
```

This must pass the actual restored candidate, including the trust regression,
all seven mutation-targeted tests, NoAdmissibleUpdate coverage, existing role
separation checks and shared signed integration fixtures. The whole-source
caller inventory is separately reviewed; it is not a replacement for native
compilation. Keep package/test totals and actual source hashes in the receipt.

Finally run:

```sh
just fix --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
```

The existing recipe is `cargo clippy --fix --tests --allow-dirty`; keep it
unchanged. Preserve the before/after source hashes and any patch. Follow the
repository instruction not to rerun tests after fix/format. A post-fix source
change must be described as such and retains the original exact-head and
synthetic-merge CI obligations.

## Trust regression scope

The old evidence cannot pass a different current trust verifier unchanged:
SignedLearningEvidence includes its trust digest. The new regression therefore
retains the original bundle/evidence variables, creates a distinct verifier
with a different but still independent generator controller, and produces
separate valid G/E signatures under that new trust. It first proves raw V2
success and full inner-decision equality before requiring the sealed helper
to reject substitution. Original verifier/evidence still succeed, and
publication/release counts remain unchanged.

Both trust and authentication digests change. This tests exact current
trust/authentication identity replacement, not the isolated necessity of one
individual field comparison. It adds no production writer, holdout consume,
provider/sink integration or live efficacy claim.

## Prepared runner, no automatic launch

`run_native_round2.py` executes exactly one phase. Copy it, `plan.json`,
`final-positive-manifest.json` and the four active `negative-controls/*.patch`
files into one task-owned bundle outside the source checkout. The supplied
bundle SHA-256 values are mandatory arguments. The runner checks the original
four entry/profile contract blobs, the exact 14 positive files, a clean
explicit HEAD/tree and a Cargo.lock matching that committed HEAD.

Root/lifecycle supplies only the task-owned bundle location and phase/attempt.
The reviewed source identities and first-wave gate paths are fixed below and
also checked against `plan.json`:

```sh
python3 "$HEPTA_NATIVE_BUNDLE/run_native_round2.py" red-q-decision \
  --bundle "$HEPTA_NATIVE_BUNDLE" \
  --head eed6541df0add428add8e2d9ab2cbd54a961abeb \
  --tree b8ce8b96a759f522cb7db60027d4844f1b3ad974 \
  --plan-sha256 00b4d289a635ae36865dc70732a1a10a03a8fb81575be5b5eba0b21fce7027fe \
  --positive-manifest-sha256 e652b430cf2af22ce8f421288bad0687cb6ba332fa31da696034f1ed9bf7c7da \
  --first-wave-head facba0d32c1cd0e8163a6186d7ba91fa311f2e2e \
  --first-wave-desktop-receipt /home/qq/work/hepta-convergence-20261105-0c901b/evidence/native-desktop-regression-v1/receipt.json \
  --first-wave-green-receipt /home/qq/work/hepta-convergence-20261105-0c901b/evidence/native-green-v2/receipt.json \
  --first-wave-fix-receipt /home/qq/work/hepta-convergence-20261105-0c901b/evidence/native-fix-v1/receipt.json \
  --attempt 1
```

Then invoke the same runner, serially, for `red-q-agentd`,
`red-q-plasticity`, `red-q-selector`, `green` and `fix`. Each phase requires
successful matching receipts for its predecessors. Each attempt writes its
own `task/evidence/native-sealed-PHASE-vATTEMPT/` directory and will not
overwrite existing evidence. Use a new explicit attempt number after a
diagnosed failure. There is no automatic test retry outside nextest's existing
configured retry, and no automatic `green-after-fix` phase.

`--first-wave-head` identifies the historical tested facba source. It is
deliberately distinct from the current first source in the adoption record.
All three original receipts retain facba and their exact SHA-256 identities.
The named and full-green gates require the original schema, exact phase and
success state, original recorded command step and argv, and both zero exits.
The named desktop regression must run exactly its original test and pass 1/1.
The full four-package command must run and pass 813/813 with the exact 14
required critical tests. A receipt-declared subset cannot reduce that gate.

The fix gate requires its original `fix-blocked`, wrapper exit 1 and Clippy
command exit 0. The unexpected path list must be exactly the two reviewed
test files. Its before/after lists must preserve all 13 original source
identities; `source_changed_by_fix=false` is understood to cover only those
13 files. The recorded full-tree path output must hash to
`d2791edc02a9dc3aad3602a5e55fc8a40e2909aa14048b067ce98c202738bda8`,
and the actual [native fix patch](first-wave/native-fix.patch) to
`8226534cf866dd0be0ed94099bef18ca7a1cd64d701ae4d48df0427f63248d07`.
The original successful formatter step is also required. The pinned adoption
record accepts this exact scope blocker; it does not transform it into a native
success record or transfer the 813-pass result to a new source.

Using only read-only Git commands with optional locks disabled, the runner
verifies the current first commit's sole parent facba and the second commit's
exact ordered merge parents. Parent order is read from `git cat-file -p HEAD`
commit headers; a shallow checkout's `rev-list` traversal would incorrectly
hide those real parent entries. No unshallow or repository mutation is used.
Each full-tree delta must contain precisely the same two reviewed test paths,
with the declared before/after blobs. Both worktrees must have their explicit
current HEAD/tree and be clean. The first tree retains the original 13 source
identities. The second independently retains all 14 ingress identities and
both adopted test files. Future HEADs, receipt attempts or adoption decisions
require a new reviewed plan hash; branch tips are never followed implicitly.

A task-local lock additionally prevents
two second-wave runners from sharing the Cargo target concurrently; it does
not replace lifecycle's serial ownership of the first-wave job.

The result parser uses final nextest summaries and final failure lines. It
requires every requested red test, exact filtered run/failure counts and the
new trust witness for Q1. Compiler failures, missing tests, timeout lines or
a failed first retry followed by success do not count. Its local Python
checks used the actual first-wave C/B2 output formats and rejection examples;
these parser checks are not second-wave Rust execution.

Normal exceptions and completion restore the exact saved production bytes
and re-hash all 14 files in `finally`; an unexpected intervening production
change is never overwritten. A forcibly killed process cannot execute
`finally`. In that case its saved positive file and expected mutation blob
remain in the attempt evidence, and the next phase refuses to run against
the altered or dirty tree until lifecycle performs a verified restoration.
