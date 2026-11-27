# C2 terminal auditor bootstrap — new post-reset preparation v3

This is a new implementation prepared after the scratch reset. It is not a
source-exact recovery of the lost earlier bootstrap, and it does not inherit
that bootstrap's fourteen-test claim or recreate its missing logs. Actual input
assembly, deployment, audit execution, model reads and E access remain
unauthorized by the included templates. All six real C2 attempts must first
reach a durable terminal state; a later root decision must bind the exact input
bytes, output locations and this source.

The auditor itself is unchanged: `auditor-core.zip` is 73,473 bytes, SHA256
`87bedabde7f37ec8d70a80305691f1116e80493174a5cd33bf7058f635230b3a`.
Its manifest is `4cc126ad4cf11e12c80408a868f8c673be70bccdce95a02228fda9d1543ef8d2`
and its plan is `1fc0d941bc9d96544c8caa5740aaba130685fed74b620f6e62dc22bec4a715ad`.
There is no new training, oracle, E evaluation or LR selection in this bootstrap.

## Two separately authorized phases

**Assemble:** use a new exclusive directory, an explicit assembly authorization
and a complete native envelope of at most 120 seconds and 256 MiB. The script
only reads byte-bound metadata, source archives and `/proc`. It binds the exact
published original launch ACK and first twelve command rows, including job
`1a1c74f3308-be2a-75`, key `hcsn-c2-native-execution-c385-v1` and the original
request digest. It rejects ambiguous/error response wrappers. Python parses
the exact MCP `content.text`; no rounded JavaScript fingerprint is used.

The future actual durable status must show complete, durable, synchronized,
untruncated stdout and stderr. Every supplied raw `h_process_read` page must
belong to that job and form an exact cursor/hex-byte chain ending at both stream
lengths. A unique original bootstrap ready print binds the same-PID controller
exec witness. The first dispatch supplies the six original worker PIDs. All
seven known PIDs must currently be absent or zombie; unreadable process state
rejects assembly. A same-UID scan additionally checks the exact Python script
tokens used by the frozen producer, without confusing arbitrary path mentions
in read-only helper commands with worker execution.

Only after those observations does the script read the pinned final controller
result and command journal. The full journal must retain the original prefix,
contain exactly the six names and end in the exact terminal records. The pinned
auditor's unchanged terminal-barrier helper checks the actual launch and return
records. The original C2 decision, ready receipt and source identity are also
bound. `NATIVE-TERMINAL.json` preserves the exact inner daemon JSON text bytes;
it is not a caller-written success flag. `BINDING.json` is the auditor's existing
schema. The assembly receipt contains all input identities and before/after
process observations. It grants no fit, quality or numerical admission.

**Execute:** a later, separate root authorization must bind that assembly receipt,
the exact binding, core manifest/plan and source files. Both phases require the
output path in the authorization; output may not contain, lie within or equal
the original C2 source, output, bootstrap, original campaign, model source or
prepared-data root. Existing output is never overwritten. Source extraction is
create-only, checks all names/CRC/member hashes and does not alter the capsule.

Execution uses the original native Python path. Its setup receives at most 120
seconds. The unchanged core's 28 software tests receive at most 90 seconds within
that setup allowance. These are future native tests, not tests executed during
this preparation. A failure stops without launching the audit. The original
core launch then receives its own complete Popen-to-wait4 limit of **1,800
seconds and 2 GiB RSS**. Its internal 360-second metadata allowance, six replay
limits of 210 seconds, 60-second reserve and one-worker/thread policy remain
unchanged. The bootstrap adds no model work or retry.

## Complete exit and cost evidence

`os_processes.py` is an exact copy of recovered supervisor helper v2, SHA256
`f58ca60428d3abafea377ca64e1d71040df98c4f149adce88436951187c990d6`.
It uses Linux subreaping, raw `/proc` ancestry/start identities and actual
`wait4`, including workers that create a new session. Timeout, unreadable
processes, late adopted children, cleanup errors, excess RSS or an unknown CPU
scope cannot pass its process gate. Known waited CPU and failures are retained.
The old helper test outputs lost in the reset are not recreated; this package
records only the new validation described below.

`PREFLIGHT-OS.json` and `AUDIT-OS.json` are separate complete child observations.
The latter must have a successful exact exit, complete direct CPU, no unknown
total-CPU flag, no adopted child wait4 rows and clean recorded process scans.
The unchanged core receipt, archive CRC/manifest, six-entry roster and final
source are also checked. The final metadata allowance is at most 30 seconds
after the core wait4 observation; this reserve does not guarantee completion.

The execute phase must itself be enclosed by a separately bound complete native
envelope of **1,950 seconds**. Its source/request, durable terminal, complete
stdout/stderr and complete OS/GNU timing remain required external evidence.
The assembly phase's corresponding outer limit is 120 seconds. The bootstrap's
`whole_bootstrap_wall_prefix_seconds` and `own_CPU_prefix_seconds` stop before
receipt writing and process exit. They must never be renamed complete native
costs. Core child, bootstrap prefix and native wrapper overlap and are not added
as if independent. Download/transport costs are outside these execution clocks
and must be separately retained. There is no download or network call here.

Any uncertain launch uses the original future stable key for reconciliation;
there is no new-key retry. A missing native terminal, missing artifact, source
change or unfinished stage remains HOLD. The external wrapper's eventual
source-bound 1,950-second completion still needs a consumer-side gate before a
resource analysis can admit the audit; this preparation does not supply a
substitute boolean for that future evidence.

## New software validation and preserved history

V3 preserves the complete v2 capsule and its measured results. Its sole runtime
change is the setup boundary: the core observer receives the original absolute
setup deadline, and `setup_wall_seconds` is calculated from the observer's actual
Popen-start timestamp minus bootstrap entry. Missing, negative or greater-than-120
values reject admission. Thus the initial process scan before Popen cannot turn
a late launch into an admitted setup. The core and native limits remain 1,800
and 1,950 seconds. `DIFF-v2-to-v3.patch` records the source change.


The two runtime files have 499 lines in total. New tests use explicit synthetic
metadata and two short actual standard-library children, one normal and one
timed out. They check raw log continuity, job/source/PID identities, corrupt and
ambiguous metadata, changed inputs, the precharged read bound, unknown process
state, output isolation, assembly RSS and cost retention. They do not import
Torch, read real C2 inputs, run the original auditor or load a model.

Attempt 01: 16 tests passed, complete child wall 1.391514504 seconds and wait4 CPU
0.399358 seconds. Attempt 02: 18 tests passed, complete child wall 0.610471297
seconds and wait4 CPU 0.394091 seconds. Those immutable snapshots remain preserved.
They predate the final assembly memory/output guards and are not relabelled as
tests of the final bytes.

V2 attempt 03: **21 tests passed**, source before equals source after for the v2
source. These are not represented as a rerun of all twenty-one on v3. The complete
test child wall was 1.314479290 seconds, wait4 CPU 0.464424 seconds and peak RSS
21,270,528 bytes. `v2-VALIDATION.json`, `v2-validation.stdout` and `v2-validation.stderr`
are byte copies of that v2 actual receipt and logs. Its child timings include
the nested short fixture children, so those costs are not added again. Parent
validation-driver finalization and general preparation/tool costs were not
measured as a complete OS account. Native software validation, real assembly,
audit execution and scientific adoption are still pending.

The previous attempt's independent training-agent static review is retained
separately and identifies its exact source. The final mode-specific changes
respond to the root review and have fresh tests; they do not rewrite that earlier
review. Numerical qualification, sufficient training, E confirmation and
scientific benefit remain distinct downstream judgments, all HOLD here.

V3 targeted validation: **four new metadata checks passed** on the final v3
source. They cover a positive complete-setup observation, late setup despite a
mock successful child, absent Popen, and the actual helper's expired deadline
preventing Popen. Core/preflight results in these tests are explicitly synthetic;
no core, model, Torch test suite or training workload runs. The complete test
child wall was 1.188352170 seconds, wait4 CPU 0.475198 seconds and peak RSS
20,553,728 bytes. Current `VALIDATION.json`, `validation.stdout` and
`validation.stderr` preserve that new run. The helper's real `/proc` preparation
was exercised, with Popen explicitly prohibited. Actual assembly and execution
remain unauthorized. This narrow closure does not replace or relabel v2
validation, the lost original bootstrap tests, or the original core's tests.
