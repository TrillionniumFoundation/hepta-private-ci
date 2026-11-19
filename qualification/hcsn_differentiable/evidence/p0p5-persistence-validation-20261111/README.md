# Persistence successor: exact-source software validation

This appendix binds the new persistence candidate to its actual native test
source and complete process records. **65 distinct final-source tests passed**:
22 atomic/journal/materializer/Torch runtime tests, 15 terminal-evidence tests,
and 28 inherited execution/protocol/reporting/trace tests. This is a software
result. Original C2 terminal status, numerical admission and scientific benefit
remain separate gates.

## Source and execution chain

The [tested-source manifest](SOURCE-MANIFEST.json) identifies all ten proposal
Python files by size and SHA256. The [source capsule](TESTED-SOURCE.zip) preserves
those bytes; the [independent identity check](FINAL-SOURCE-IDENTITY-VERIFICATION.json)
confirms that the current proposal files match them without rerunning tests.

The source base is commit `4ed61beacd9e8cf08cd1f7f8c938b75d747149e4`.
The [materializer and reproduction instructions](../../../../proposals/hcsn_persistence_v1/README.md)
bind the archived C2 v4 ZIP and its nested tested-source ZIP, retain original
model/boundary/recording code and construct a separately identified source.
The materializer does not start training or issue an execution decision.
Its source-manifest change prevents reuse of the old C2 decision.

| Native job | Actual result | Credit to final candidate |
| --- | --- | --- |
| `1a1c8ff5808-135c4-368` | Earlier prototype: 21 tests, exit 0 | None; different source |
| `1a1c906f6e7-135c4-395` | 22 tests passed; source materialized; 15 tests passed; fourth command raised ImportError; wrapper exit 1 | 22 + 15 only |
| `1a1c90894e4-135c4-39c` | Corrected module invocation: 28 tests, exit 0 | Remaining 28 |

The first final wrapper's [stdout](native-first/STDOUT.txt),
[result](native-first/RESULT.json), [command](native-first/COMMAND.sh),
[launch receipt](native-first/LAUNCH-RECEIPT.json) and
[terminal status](native-first/STATUS.json) preserve the failure. It invoked
`run_successor_tests.py` directly, which failed its relative import before
collecting the inherited suite. The corrected invocation was
`python -m proposals.hcsn_persistence_v1.run_successor_tests`. Its
[result](native-inherited/RESULT.json), [stderr](native-inherited/STDERR.txt),
[launch receipt](native-inherited/LAUNCH-RECEIPT.json) and
[terminal status](native-inherited/STATUS.json) establish all 28 inherited
tests, zero failures/errors/skips, and identical before/after imported source.
Both process records confirm complete, durable logs and no automatic retry.

The final wrapper reports Python 3.14.4 and executable
`/home/qq/.venvs/rocm10/bin/python` on ai395. Commands force one CPU thread.
Torch integration uses synthetic CPU tensors/checkpoints. This native result
is separate from the workflow's pinned runtime and from hosted CI; it is not
an all-green repository claim.

## What the tests establish

The candidate publishes validated immutable checkpoints through same-directory
temporary files, flush/fsync and a no-clobber hard link. Complete tensor,
optimizer and RNG structures survive safe-load comparison before publication.
A hash-linked receipt journal is authoritative; the JSONL view and final index
are derived after verification. Owner PID, Linux boot ID and process start
ticks are bound to the actual child process observed by the controller.

A closed prefix alone is insufficient. Terminal admission requires one unique
last `finished` event with the exact report status, a known integer exit,
a matching process identity and valid original source/artifact evidence.
Tests preserve costs for failures and discarded work; they do not infer
adequate training merely from exit zero.

The [independent earlier review](INDEPENDENT-TERMINAL-REVIEW.json) retains
counterexamples that motivated the strict final terminal checks. It describes
an earlier source and is not credited as a final-source pass. The final tests
reproduce the relevant empty/running-only/wrong-status/unknown-exit/owner
counterexamples. The [earlier prototype source transfer](earlier-prototype/TRANSFER.json),
[command](earlier-prototype/COMMAND.sh), [test log](earlier-prototype/STDERR.txt)
and [status](earlier-prototype/STATUS.json) are preserved separately.

Original terminal test methods and assertions remain unchanged; the new
fixture supplies the successor's receipt/process envelope. Reporting uses the
same adapted fixture. The suites do not double-count the historical terminal
class. The final inherited result explicitly records the 11/8/4/5 class
counts and exact module source identities.

## First hosted-head spelling failure

For source head `f7897539897eb01c332346654e4635e94ad1312f`, Codespell job
`130342749006` in blocking run `42965840400` failed on two encoded payload
fragments. Its checkout was merge `b8afcd2d65d0128446dd931558010a952d70452b`;
the GitHub commit response confirms tree
`2b7d1574ed78d2e4eaaa062dc505f09891c933df`, identical to the published source
tree. The [failure and fix archive](ci-first-head/CODESPELL-FAILURE-AND-FIX.zip)
preserves the original log response, run observation, merge identity and
configuration validation, with an explicit size/SHA256 manifest inside a
deterministic ZIP. The overall blocking run was still queued at the last
recorded observation; the failed Codespell job is not a whole-run terminal.

The follow-up configuration adds only the exact paths for
[native-first/COMMAND.sh](native-first/COMMAND.sh) and
[native-first/LAUNCH-RECEIPT.json](native-first/LAUNCH-RECEIPT.json) to the
existing Codespell exclusions. Neither raw file nor the word allowlist changes;
no directory is broadly excluded. Both raw identities remain checked by this
appendix's manifest. The saved fix validation precedes this manifest's extension
to bind the new ZIP and README. No hosted result for the corrected head had been
observed when this section was recorded; the original failure remains intact.

## Cost and limits

The [summary](SUMMARY.json) separates measured software overhead from unknown
campaign costs. The first final wrapper reports a 3.578765-second wall lower
bound through report construction, 3.398604 seconds of child CPU and
961,273,856 B peak child RSS. The corrected inherited wrapper reports
2.633542 seconds. These are partial process observations with different
boundaries, not total research costs or a fair training budget. Energy was not
measured. The failing fourth command and earlier prototype are retained;
unmeasured overhead is not assigned zero.

The 3,000-event journal fixture on the native final source measured 0.247704
seconds of append time and 0.375359 seconds including close/verification.
This is a local synthetic durability exercise, not power-loss qualification
or a training-throughput benchmark. The runner/controller sample report
clocks after journal close and artifact identity work; outer process envelopes
are still necessary to include final publication tails.

No new optimizer step, original C2 resume, all-six terminal reconstruction,
full training-domain numerical qualification, independent held-out scientific
benefit or production adoption is established here. The four original fits'
independent development replays are documented in the separate
[P2 recovery appendix](../p2-c2-independent-recovery-20261111/README.md).
The other two original fits and the original controller remain unresolved.
