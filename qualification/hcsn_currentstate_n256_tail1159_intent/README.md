# Authentic N256 index1159 output-bound admission

Status: **SOURCE-ONLY / RESOURCE HOLD / all_closed=false**.

This separately frozen v12 candidate strengthens the source-only admission on
top of #6989. It consumes the ten byte-exact index537 full-state
originals from #6957/#6959 and defines the unchanged exact continuation to
index1159. Each lane would apply exactly 622 row actions and one signed
ratio-bound tail check. The ten-lane cap is 6,220 row actions, ten tail checks,
and at most 5,180 exact binary64 rounding calls. It permits zero provider,
dynamic, exponential, Torch, optimizer, model, or training calls.

The source preserves the complete exact iterate, coefficient, growth
coefficient, exponential sum, partial vector, parent identity, and signed
content. It does not infer index537 state from M/H/R/A or reconstruct a missing
trajectory. The tail test and roundTiesToEven primitive are unchanged from the
completed negative #6957 run.

No authentic checkpoint is decoded by this stage. `REQUEST.json` deliberately
leaves the host observation, allocation, calendar, runtime and concurrency
originals null, and `admit_runtime()` refuses before any authentic input read.
Admission also requires the explicit authorization bit to be exactly `true`, so
filling runtime digests alone cannot authorize an execution. Each future
original must be a byte-verified JSON file under `runtime_originals/` and must
cross-bind the candidate identity, same execution key, intent source head,
exact source-manifest digest, authentic input digest and desktop host.
The request and all four originals must be single-link regular files no larger
than 64 KiB. The reader binds the pre-open path identity to the opened file
descriptor, performs two bounded reads from that descriptor, and rechecks the
descriptor and path identity after reading. Symbolic links, hard links, path
replacement and concurrent content changes are rejected. Parsing rejects
duplicate keys, nonfinite constants, numeric overflow, non-object roots and
invalid UTF-8 before any authentic input read.
Admission also restores the exact `SOURCE_FREEZE.json` bytes through the same
descriptor-bound reader and byte-verifies every listed source/workflow file
before any authentic checkpoint read. Binding an original to the manifest
digest is therefore insufficient if the executing source tree has drifted.
Allocation concurrency and memory,
the currently valid calendar, observation expiry and ancestor-cgroup headroom,
plus the Python executable and dependency-manifest digests are checked before
any authentic checkpoint read.
The runtime digest fields are compared against the resolved executing Python
binary and a canonical sorted JSON list of every installed distribution name
and version (`importlib-name-version-json-v1`); they are not accepted as
unverified claims from the runtime original.
The future host observation must now also bind the exact cgroup v2 relative
path and leaf device/inode. Admission reads `/proc/self/cgroup` twice through
one stable descriptor, resolves the live leaf under `/sys/fs/cgroup`, and reads
every leaf-to-root `memory.current`/`memory.max` pair twice. It rejects a
different hierarchy identity, an unbounded hierarchy, malformed counters, or
live tightest-ancestor headroom below the frozen allocation. The observation's
earlier headroom claim remains required but can no longer substitute for this
live recomputation.
After that admission succeeds, the validated cgroup identity and allocation
memory are retained only in process memory. Every one of the ten future lane
launches then independently repeats the live hierarchy and tightest-ancestor
headroom read immediately before `Popen`. A changed leaf/path identity or
headroom that has fallen below the frozen allocation refuses that lane before
it can read an authentic checkpoint and leaves an explicit pre-spawn refusal
in the process ledger instead of losing already-started sibling statuses. The frozen denominator is therefore
eleven live cgroup reads: one admission read and ten pre-spawn reads.

The first local v11 test invocation is preserved as RED: the source verifiers
passed, but the normal 36-test pass reported four failures and one error because
the synthetic authorized fixture replaced `runtime_admission` without carrying
the new `require_live_cgroup_v2` field. It executed zero authentic input or
numerical work. The repair changes only that fixture constructor; the next
normal and optimized 36-test passes both completed successfully.
The current #6966 observation is only a time-point observation, not an
allocation. The earlier static #6964 byte projection is not a bound.

The collector no longer accepts lane-authored metadata as proof of output. It
reads each result, tail and compact checkpoint through a descriptor-bound,
single-link regular-file reader; rejects ambiguous JSON and schema drift;
recomputes every byte count and digest; decodes each compact checkpoint once to
verify the raw digest and raw cap; parses that raw target into the complete
exact checkpoint state; requires its lane to equal the result stem; and
re-encodes the exact state to require byte-for-byte canonical equality. It also
reconstructs the tail denominator,
uniqueness, rounding digest and work ledger; and requires ten safe lane stems.
These ten collector decodes raise the complete planned decode denominator from
20 to 30. The new source-only collector work is separately bounded at ten
semantic checkpoint parses and ten canonical raw re-encodes without changing
recurrence, tail, rounding or model work.

This target semantic binding is deliberately not an independent numerical
oracle. It does not restore an index537 parent, replay the 622 row actions, or
recompute the signed tail from the parsed target. Those parent/recurrence/tail
cross-bindings require a separately frozen execution and budget. Passing this
collector therefore cannot establish recurrence correctness, tail termination,
N256 qualification, arbitrary resume, N512 scalability, full-state migration,
or production readiness. The final record keeps a separate
`candidate_tail_output_all_unique` observation while
`tail_termination_closed` remains false.

Each future lane stdout and stderr stream is now drained concurrently with
constant memory and retained under a separately frozen 1 MiB per-stream cap.
The collector no longer uses `capture_output=True`, which could accumulate ten
unbounded pairs of logs in memory. A stream that exceeds its cap terminates and
fails that lane, while both pipes continue to be drained so a child cannot
deadlock on a full pipe. The final ledger records produced byte counts, caps and
overflowing lane ordinals; the aggregate retained log bound is 20 MiB.

Every future lane now starts in its own POSIX session. The owner freezes the
same 6,900-second per-lane command bound used by the authoritative index537
lineage and a five-second termination grace. A deadline or log overflow sends
SIGTERM to the owned process group, escalates to SIGKILL when needed, reaps the
direct child, and records whether the process group remains alive. A direct
child that exits while descendants remain is also detected, cleaned, and
rejected. Result validation is joined to this process status: a result can
enter the aggregate only after exit zero, no overflow, no timeout, no residual
descendant, and no live group after cleanup.

The final collector ledger now preserves every validated lane's wall time, CPU
time and process peak RSS alongside the collector's own wall time, CPU time and
peak RSS. It also records every child return code and, separately for stdout
and stderr, both produced and retained bytes. Concurrent process peak RSS is
reported as a maximum rather than summed into a fictitious simultaneous peak;
lane wall and CPU sums remain explicit derived quantities. A failed or missing
lane remains absent from `validated_lane_costs` and present in the process and
failure ledgers, so incomplete work cannot be reported as a complete cost.
The process ledger separately preserves timeout, descendant, TERM/KILL, and
post-cleanup group observations. This is process-group containment, not a
cgroup: a child that deliberately creates a new session, kernel-level
uninterruptible work, host power loss, and machine-wide simultaneous RSS or
energy remain outside this source-only stage.

The next execution commit must bind all four runtime originals to this exact
source and the same execution key, preserve attempt `001`, set an explicit
bounded concurrency, and independently review the actual memory/cgroup and
calendar envelope. A new key must not be used to evade a timeout or unknown
outcome.

#6939/#6950 remain RED; #6942 remains RED_TIMEOUT with completed actions
UNKNOWN; #6901 remains UNKNOWN. #6957 remains the authoritative 0/2,585
non-unique result. Tail termination, N256 qualification, C2 full replay (0/6),
HPCA external custody/equal-budget benefit, cgroup process containment,
cgroup-wide simultaneous RSS/energy, and production adoption remain open.
The pre-spawn recheck narrows, but cannot eliminate, the interval between the
last headroom observation and kernel process creation. It is not a reservation,
does not place lanes in dedicated cgroups, and does not close deliberate
new-session or cgroup-migration escape.
Global state remains **HOLD / NoUpdate / all_closed=false**.
