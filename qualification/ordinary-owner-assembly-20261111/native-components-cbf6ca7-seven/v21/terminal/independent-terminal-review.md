# V46 terminal evidence — bounded independent review

## Conclusion

The original result 39644ad60327fbcc4c5841e126e0e2a5b827a153 is consistent
with the inspected executions, original JUnit summaries, terminal receipt and
failure stderr: **FAILED_NATIVE_COMPONENTS**, ordinary **1997 passed / 0
failed**, Root **16 passed / 1 failed**. This is component qualification only.
The business counts remain **0 / 0 / 0**, independent consumer false and actual
daemon plus Root OS restart false.

Full review/byte proof:
4add4c2ee251827be6092da045d4425218ef0801
(15,988 bytes; SHA256
2faa636a0181ab7bd75758f6d5bcc264a2dccd250b8b495b5d6a221817e05f94).

This review concerns the fixed 9002c7fc3097aad111e902cde6597042e0fc4869
candidate index and its original evidence. It does not certify a later index,
tree, the future source assembly, or any new native execution.

## Actual terminal and counts

- Source before/after remains cbf6ca7dd619589be3e9e98755f185d34d0f7413,
  tree c3c131a738f99022bfb5e72bb53ef44c064ad350, clean; maintenance patch is empty.
- Caller execution d1a3709ed007608deb09dff58e4d5b15ec4a4078 is the exact
  unfiltered python3 scripts/verify_hepta_callers.py verify, exit 0.
- Ordinary execution d9e383f75e1a9eafb7fe808b185e7c67dc47a26c contains all seven
  original packages and retries 0. Its JUnit summary has 1,997 cases, no failures,
  errors or skips, and binds the exact execution SHA.
- Root execution 107f25db317630c6105f2a1ea1ccfd644be1fc1b contains 17 unique exact
  parent tests and retries 0. Execution exit is 100, JUnit collector exit is 1;
  the summary retains 17 cases, one failure, no errors or skips.
- All three execution records explicitly have timed_out=false and
  output_limit_exceeded=false. No timeout or exemption is substituted.
- The original final terminal read 5c2c9cdfb8d1664c0318f463974c00aacf8703ba
  reports process exited, exit 1, output_complete=true, capture_error=null.
  Its exact 6,452..17,965 byte suffix matches the complete retained terminal.
- Nine cleanup entries passed, source and reference identities remain equal.
  Four original QA steps exited 0; the RESULT's 236 count was not independently
  recounted from all QA log contents in this bounded review.

The failed parent is the initial-publication/read-only-recovery test. The
nested dedicated child failure is part of that parent, not an extra Root case.

## First-error boundary

Original stderr 5cdf146c78b850c4bd779e4697616e7b00b837e6 shows RetiredSession
opening original inputs, then frontier.read-prefix reporting Unavailable with
transport_error Some(Closed), followed by live-retained-final-use refusal.
The child context is reading the original published Feature. The parent then
reports PeerDenied while awaiting RETIRE_READY, with EAGAIN 11.

Fixed-source child 2115df57da689a3a2a6328fc432ad22b41d0d3e7 confirms the error
propagates from initial.recover_feature before task.require_bundle,
RETIRE_READY, parent RETIRE, drop_original_production_after_idle and its later
retirement assertions. Therefore this attempt did not reach that RetiredSession
drop-helper check. The earlier V45 callback/cache-age diagnosis is not this
attempt's established cause.

These records do **not** establish the initiating Root server leaf error.
PeerDenied/Closed and the capped timing records must not be promoted to a
unique server-cause conclusion. No product fix or successful retirement is
inferred here.

## Text archive versus binary originals

All five original base64 blobs were fetched and checked against their exact
Git/UTF-8 byte length/SHA256. Each was independently decoded, checked against
its decoded SHA256, then concatenated at the exact continuous offsets.

The complete transferred text archive is:

- 268,708 bytes
- SHA256 defff527e6da8ee14f410acbdc66532a0abe49bf8559ce337a763e2aa59cd3c6
- computed binary Git blob d091aa2990dd0d42bd27a71e8c4ac07722e8e106

No decompression or tar member reparse was performed. Original index and text
index agree exactly: **124 original records = 121 text originals + 3 binary
originals**. The text archive has **122 entries**, because it also includes
ARCHIVE_INDEX.json. Execution/log/JUnit lengths and hashes match those indexes.

The three excluded binaries are hepta-joint-propose and the before/final
compressed source inventories. The original host receipt records them in the
1,838,228-byte complete tar.xz and 3,836,827-byte complete zip, with exact hashes.
This review did not transfer or independently hash those complete binary-inclusive
archives. Text-archive verification must not be described as complete binary
custody in Git.

## Publication conditions already acknowledged by Root

The original 9002 index has 195 future Rust snapshot paths ending in .rs.
Root acknowledged changing all source evidence copies to <actual path>.txt
before tree/ref creation, retaining original source paths in SOURCE_MANIFEST
and preserving every blob's bytes. The old index must not be published as-is.

The planned result-execution.json to ordinary.execution.json rename matches
the original JUnit execution_file. The native_qualification_launches wording
properly distinguishes zero new qualification runs from separate archival
operations. These are representation corrections; this reviewer changed no
original artifact and has not yet inspected their replacement index.

Original nanosecond fields remain in their exact raw JSON blobs. They were not
reserialized through rounded JavaScript numbers. The derived RESULT and current
candidate index contain no unsafe integer values.

All work was Git read plus pure V8 verification and creation of this review:
**no h, PTY, native, original checker, test, ref or product mutation**.
