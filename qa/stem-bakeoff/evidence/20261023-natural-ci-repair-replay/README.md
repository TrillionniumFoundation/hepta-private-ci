# Historical source-pinned Python / Git repair replay

The fixed five-arm replay actually executed all 15 original target-module test
commands. Two historical failures reproduced locally. For both, no-op and the
wrong action retained the failure, while oracle, exact retrieval and TF-IDF
retrieval applied the same original repair and passed the original repaired
suite. The third incident did **not** reproduce in this environment: its original
suite already passed, so every repair-effect field remains `null`.

This is known historical development evidence for the source → authorized patch
→ actual command → observed outcome path. It is not learned debugging, new
program synthesis, an untouched heldout test, a prospective cohort, capacity
pressure, or an advantage over retrieval. No trained model was invoked.

## Fixed cases and original source evidence

All three cases are natural GitHub Actions failures followed by a direct-parent
fix and a success on the same workflow. The hosted failure completed before the
fix was committed. They share one repository, workflow and module family; three
incident IDs do not establish statistical independence across projects.

| Incident | Failed source and hosted run | Direct repair and successful run |
| --- | --- | --- |
| Newline syntax corruption | `7ff024031abfdcce7a899ee0661924c7c573ac76`, run [39822541483](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39822541483) | [b122867a494a994716c8ddd1f4c4508298c34a28](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b122867a494a994716c8ddd1f4c4508298c34a28), run [39822906539](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39822906539) |
| Hosted loader fixture isolation | `18953183bf77c81a88749c37b3a0d227ed7f03d4`, run [39829395619](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39829395619) | [8558310ba7378414ac7033431e496b1945ead164](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8558310ba7378414ac7033431e496b1945ead164), run [39830138023](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39830138023) |
| Precise Git index flag reset | `35d22ae6b900effb5866206f5e35072d90b39be6`, run [39836650124](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39836650124) | [089ffd5aa4edc8ecfd62a7024a05c062c4d2b748](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/089ffd5aa4edc8ecfd62a7024a05c062c4d2b748), run [39837269024](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39837269024) |

`evidence/<incident>/github.json` retains source URLs, commit parents, original
patch bodies, changed-file Git blob SHA-1, run metadata and job metadata. Adjacent
`failure.log` and `success.log` retain the decoded original hosted job logs.
Their hashes bind UTF-8 log text returned by the GitHub connector, not the
original compressed GitHub log archive.

`source_bundle/<commit>/` retains exact before/after UTF-8 files for:

- `scripts/run_hepta_local_closeout.py` — original production runner;
- `scripts/test_run_hepta_local_closeout.py` — original failing or fixed tests;
- `.github/workflows/hepta-p6-codex-native-parity.yml` — original workflow read by the tests.

The 18 retained source members occupy 253,570 bytes. For each repair, the fixed
test file's calculated Git blob SHA-1 matches the real GitHub commit metadata.
Every member also has a SHA-256 in `protocol-001/plan.json`. This is the minimal
target-module closure; the full repository and complete hosted workflow were not
reconstructed or executed. The tests exercise real temporary Git repositories
and Python processes, but their original mocked Cargo/check fixtures remain
fixtures. No production acceptance claim follows from these test passes.

## Frozen protocol and same action library

Plan SHA-256, recorded before the first replay command:

`42b47342a3c62bff6b273dd1b6a06c23b1968babd4109f6dfff98b64f0abf700`

The plan pins both runnable modules, all 27 source/evidence inputs, action
patches, case order, original command, limits, observer, and selector recipes.
No source, case, action, selector or threshold changed after results were seen.

Each arm gets a fresh original source copy. The library contains exactly the
three genuine repair patches. The no-op arm selects none. Wrong-action selects
the next action cyclically in the frozen case order. Oracle receives the correct
case index. Exact and TF-IDF receive only the diagnostic lines extracted from
the original hosted failure log. Their library documents are those same known
failure diagnostics. Exact lookup and cosine TF-IDF therefore measure retrieval
of already stored incidents, without a paraphrase or unseen-task claim.

All selected actions use the same full-file preimage hash contract. A mismatch
rejects the action; the original test command still runs. An admitted action
executes `git apply --check` and then real `git apply` in an isolated local Git
directory. The postimage must exactly match the original repaired file.
Consequently the wrong-action control checks rejected preconditions; it is not
an experiment in executing an arbitrarily corrupting patch.

Every arm runs the unchanged original target command:

```bash
python3 -m unittest discover -v -s scripts -p test_run_hepta_local_closeout.py
```

Only `PYTHONDONTWRITEBYTECODE=1`, already present in the original workflow, is
set for the child. Other environment variables are inherited. No loader paths
were injected and no guard was weakened to manufacture a failure. The observed
environment had none of the production runner's blocked environment names set.
Each process has a 120-second timeout and a 1 MiB retained output bound; neither
limit was reached. The observer reads the actual exit code and raw log, checks
the original failure signature, and rechecks source bytes after execution.

## Actual results and test-change audit

| Case | No-op | Wrong action | Oracle | Exact retrieval | TF-IDF | Local repair effect |
| --- | --- | --- | --- | --- | --- | --- |
| Newline | SyntaxError, exit 1 | Rejected preimage; same SyntaxError | 15 tests pass | 15 tests pass | 15 tests pass | Reproduced; each successful selector repairs 1/1 |
| Hosted loader | 21 tests pass | Rejected preimage; 21 tests pass | 22 tests pass | 22 tests pass | 22 tests pass | **Nonreproduced**, all effects `null` |
| Git index reset | 29 tests, one failure | Rejected preimage; same failure | 29 tests pass | 29 tests pass | 29 tests pass | Reproduced; each successful selector repairs 1/1 |

All 15 processes completed: 11 passing suites and four failing suites. The
reported unittest counts sum to 300 with repetition, including two failed-import
placeholder tests. These are not 300 independent incidents. Oracle, exact and
TF-IDF each repair the two reproduced cases; there is no learned-policy arm or
advantage. `learned_route.status` is `unavailable`, not an oracle substitute.

Every real repair changes the test module. Newline restores a malformed line
without deleting any of its 15 test names. Loader adds a test-process fixture
baseline and one regression test rejecting a changed loader path (21→22 tests);
the production guard is untouched. Git reset changes the real test cleanup
command from clearing two flags together to clearing the specific flag under
test (29→29). The audit retains exact patches and test-name/AST differences.
All arms preserve production runner and workflow bytes. Every admitted action
ends at the exact historical fixed test-file hash, with no test-source mutation
during execution.

## Receipts, costs and reproducibility

`run-001/<incident>/<arm>/` retains the source copy, original command log, patch
command logs where executed, actual diff and a complete `receipt.json`. All four
failing suites remain in the archive. `run-001/result.json` has SHA-256:

`e2d543736073958e25c2804ac865bf384d14568f9d8bbcdec3be0fbff32a0287`

The run executed 15 test processes and 27 patch setup/check/apply commands,
including nine actual patch applications. Measured execution-stage wall time was
35.691 seconds. All spawned commands together used 12.510 user CPU seconds and
6.850 system CPU seconds; maximum per-command `wait4` peak RSS was 19,660 KiB.
Retrieval index construction took 0.000213 wall seconds. Raw local logs total
54,621 bytes; the patch library is 4,155 bytes. Model calls and training updates
are both zero. These local timings are not a controlled hardware benchmark.

Driver total CPU and peak RSS were not instrumented. The wall time includes
copying and recording inside the execution loop; per-command metrics include
the original tests' waited child processes. Original hosted-CI expenditure is
not inferred. Stored source including all arm copies and the two new modules is
911,340 bytes; all artifacts before the audit/README totaled 1,582,977 bytes.
`archive-audit.json` checks all retained source, diff and raw-log hashes without
rerunning any command. It is local archive consistency, not independent signed
execution provenance.

Run the pinned plan again into a fresh directory:

```bash
python3 -B /workspace/scratch/12ef9c5bdc23/procedural-replay-work/replay_run.py \
  --plan /workspace/scratch/12ef9c5bdc23/procedural-replay-work/protocol-001/plan.json \
  --expected-plan-sha256 42b47342a3c62bff6b273dd1b6a06c23b1968babd4109f6dfff98b64f0abf700 \
  --output /workspace/scratch/12ef9c5bdc23/procedural-replay-work/run-002
```

`replay_bundle.py` (178 lines) freezes the validated bundle and original patches;
`replay_run.py` (280 lines) executes selectors/actions/observers. Neither imports
the memory model/trainer or writes to the frozen memorycell repository. Sources
and original logs were acquired through read-only GitHub calls; no remote
repository mutation or push occurred. Changing the current runtime/environment
can change reproduction, which must be reported as observed.

## Relationship to existing evidence and remaining blockers

The repository already has 1,803 actual artificial file-transform executions in
`qa/stem-bakeoff/evidence/20261022-procedural-memory-replay/README.md`. Its trained
Granite task head did not beat frozen nearest-neighbor/centroid under forced
selection (all 64/64), and at the fixed threshold covered only 20–21/64 versus
57/64 and 59/64. This historical natural-source replay does not replace that
negative result or claim to be the first executed procedure experiment.

The adjacent candidate inventory records eight previously inspected historical
direct-parent chronological pairs and two paired-only repairs whose commits
predated completion of the hosted failure. They remain finite development
material. There is no untouched prospective cohort, no demonstrated capacity
pressure, and no learned selection for these repair IDs. Natural future-task
generalization and learned procedural advantage remain open scientific gates.

## Separate domain416 input chronology

These are the three **domain experiment inputs**, not the three Python/Git
procedural replay cases above. This read-only audit uses their original commit
and hosted-run timestamps, without consulting training scores or changing their
data, partition, protocol or source. All times below are UTC on 2026-10-23.

| Domain input | Failed test exit / failed-run completion | Fix commit time | Successful-run completion | Permitted historical interpretation |
| --- | --- | --- | --- | --- |
| Bound fixture evidence (`e9ecf9c50877b58879e1b3d61a766cf512466d5f`) | 09:41:09.841 / 09:41:12 | 09:40:56 | 09:41:38 | Paired historical replay only: fix predates hosted failure |
| Covariance diagnostic order (`455e16648ce7069400f5a8e679e4fd0c1a1da613`) | 10:42:39.538 / 10:42:41 | 10:44:42 | 10:45:24 | Strict historical failure-completion → fix → success order |
| Exception-message order (`8ab132fce55be881a1410639d4db96e4eee8b1b1`) | 10:50:20.755 / 10:50:23 | 10:49:36 | 10:50:31 | Paired historical replay only: fix predates hosted failure |

Direct-parent relationships and later successful verification do not establish
that a developer observed a hosted failure before making the fix. Even the
strictly ordered case's timestamps establish order, not the developer's internal
decision process. The domain producer verifies direct-parent/same-workflow and
failure-before-success ordering, but does not require the fix commit to follow
failure completion. Its existing finite-development label remains appropriate;
none of these inputs becomes prospective through this audit.

The compact publication bundle includes original input files and exact source
hashes in `related/domain-inputs/` and `domain-chronology.json`. The already
tracked domain source remains in `scripts/memory_cell_domain/` at local `a26aeb74`.

## Published evidence bundle

`hepta-ci-repair-replay-20261023.tar.gz` is the deterministic reduced evidence
archive. Check `SHA256SUMS` before extraction. It retains the exact executed
drivers, source bundle, original hosted evidence, frozen protocol and all local
command receipts/logs. `packaging-audit.json` at the extracted bundle root
reconstructs the omitted disposable work copies from retained original bytes
and actual diffs, and verifies all before/after hashes. The original full-worktree
audit remains labelled with its original scope.

Readable driver copies live under `scripts/memory_cell_procedure_replay/`.
Their formatting preserved the AST, as recorded in `source-format-equivalence.json`;
the original plan intentionally admits only the unformatted bytes in the archive.
After extraction, run the archived driver with explicit paths to the archived
`protocol-001/plan.json` and a fresh output directory. This supersedes the example
workspace prefix above without changing the original plan or its code pins.
