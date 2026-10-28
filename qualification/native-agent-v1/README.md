# Native agent and shared-runtime qualification

The completed 0.165.0 comparison, measured limits and engineering status are in
[REPORT.md](REPORT.md). Both formal rounds and their failures remain in the
evidence directory. Use [FORMAL_PLAN_V2.json](FORMAL_PLAN_V2.json) and the V2
measurement entry point below for the final recorded sampling configuration.

This directory exercises a bounded native agent against the same real
`hepta-runtime` tool implementation used by two Codex comparison lanes. The
native path is a complete model/tool conversation for a fixed read-only task:
user input, persisted session state, context assembly, Responses streaming,
tool admission and execution, observed output, model feedback and a final
answer.

The qualification does not replace production agentd. Its session owner is
restricted to a three-operation fixture and does not compose production
FinalUse, lease issuance, revocation or physical-entry authority. Results and
gate status belong in the recorded evidence for each build; this README does
not declare a test count, a performance winner or production readiness.

## Components

| Component | Responsibility |
| --- | --- |
| `codex-hepta-native-agent` | Bounded model/tool loop, in-memory turn state and transport; calls the host's admission and checkpoint interfaces |
| `runner/src/owner.rs` | Qualification session identity, immutable model/tool admissions, exact compiled fixture requests and manifest validation |
| `runner/src/persist.rs` and `snapshot.rs` | Private single-writer session storage, durable checkpoints and recovery against the original admissions |
| `runner/src/runtime_bridge.rs` and `runtime_bridge_wire.rs` | Existing runtime API calls, original request/host binding, bounded lossless output reads and validated terminal observations |
| `runner/src/tool_session.rs` | The same runtime tool path exposed to Codex through a persistent helper |
| `runner/src/main.rs` | Persistent JSON-lines qualification interface and cancellation input |
| `model_gateway.py` | Shared fixed-response replay or live Responses boundary, bounded requests and captured model evidence |
| `protocol_driver.py` | Codex thread/turn correlation and delivery of dynamic tool calls to the shared runtime helper |
| `benchmark_v2.py` and `process_metrics_v2.py` | Final scoped process sampling, 500 ms post-sample wait, one resident executor per lane and explicit detached-job coverage |
| `benchmark.py` and `process_metrics.py` | Preserved first-round source, including the measured observer overhead; not silently replaced by V2 |

The native loop uses the shared Cell/runtime DTOs from `codex-hepta-types`.
The canonical conversion seam and its authority limits are described in
[CONTRACT_CONVERGENCE.md](CONTRACT_CONVERGENCE.md). In particular,
`canonical_runtime_intent_v1` is a pure correlation projection into the existing
execution-core ABI. It neither creates a checked execution handle nor grants
permission to dispatch.

## Identity and state ownership

| Identity or state | Authoritative owner in this qualification | Recovery rule |
| --- | --- | --- |
| Native thread, turn and root operation | `SessionOwner`, deterministically derived from the caller's session identifier | Reopen the same session and immutable manifest; changed input, fixture, model policy or mode is rejected |
| Codex thread and turn | The pinned official App Server or in-process facade | The driver retains the actual returned IDs and rejects tool, answer or usage events belonging to another active scope |
| Model operation | Session owner, using the original root operation and admitted model-call sequence | Keep the exact request bytes and original operation; an ambiguous POST is not replayed |
| Tool operation and idempotency key | Session owner, derived from its original operation and the original model call ID | Reload the immutable admission and compiled request; a changed proposal cannot reuse the same call ID |
| Generation | Session owner; fixed at generation 1 for this isolated experiment | Every restore and admission checks the original binding; this fixture does not exercise production generation rollover |
| Context, queued calls, call budgets, pending markers and final answer | Agent/session owner | Persist checkpoints before effects; restore the latest intact checkpoint chain without silently rolling back |
| Runtime job ID, physical host/request binding, process state and output | Existing runtime jobs owner | Observe or cancel the same original request/job; the agent does not create a second jobs registry |
| Terminal receipt projection | Bridge, from the original runtime's validated terminal publication and lossless output | Recheck the original request after output retrieval; reject inconsistent bindings, incomplete logs or changed terminal evidence |
| Production principal, policy, signed FinalUse, leases and live revocation | Existing production authorities, outside this qualification owner | They must be composed and rechecked at physical entry before a production cutover |

Codex's real thread/turn identities and the helper's qualification identities
are distinct. The driver correlates a Codex call with its dedicated helper
session; it does not pretend that both systems minted the same identifiers.
The child tool operation is likewise distinct from the parent conversation
operation and from the runtime's physical job ID.

The session manifest binds the input, fixture and policy. Model admissions
store the original request body. Tool admissions store the original proposal,
the compiled `ProcessStartParams`, deadline and complete intent digest. The
compiled bytes include the actual host, executable, arguments, resource limits
and idempotency key; the model's proposed JSON is not the executed payload.

Session directories must be private, current-user-owned directories. Records
must be private, single-link regular files. Checkpoints form a numbered hash
chain, with file and directory sync before acknowledgement. Concurrent owners,
gaps, corrupted records and changed immutable admissions are rejected. This
is qualification conversation storage, not a distributed or authenticated
production authority ledger.

## Admission, acceptance and real completion

These states must remain distinct:

| Observation | What it establishes | What it does not establish |
| --- | --- | --- |
| Durable model/tool admission | The session owner saved the exact request and identity | The provider or runtime physically started it |
| `submission_attempted` | The owner checkpointed that a tool submission may cross the boundary | That a job exists, or that absence in a local registry proves no effect |
| `ToolObservation::Accepted` | No validated terminal receipt is available yet | Successful completion; the bridge also uses this waiting state when the original request cannot yet be found |
| Validated terminal tool observation | The original runtime publication, exit outcome and complete retained output have been observed and bound to the original intent | A permission grant, or success when the terminal exit outcome is failure |
| `RunOutcome::Completed` | The model produced a final answer after the loop's required observations | General task correctness or successful performance qualification; the benchmark grades these separately |
| `PendingModel` / `PendingTool` | The original operation still requires observation or reconciliation | Permission to create a replacement operation or report a successful final answer |

The bridge requires the pinned runtime's durable terminal-publication witness,
matching job identity and launch nonce, consistent exit/cancellation/timeout
state, and complete, untruncated, synced stdout and stderr. It reads bounded
pages using independent byte cursors and lossless bytes, then observes the
same full original request again. The resulting existing `RuntimeReceiptV1`
has `AuthorityPosture::DENY_ALL`; it is an observed outcome, not authority for
another action.

### Lost acknowledgements and streams

A tool's exact intent and compiled parameters survive a timeout, lost
acknowledgement or process restart. `observe_request` and cancellation operate
on that original request. A missing local record is not proof of
non-admission. The loop keeps the attempted marker and does not call start
again to discover whether a job exists.

For a model, the loop persists the exact body and operation before POST. It
also checkpoints a provider response ID once observed. A repeated run may
perform GET reconciliation of that same response through `ResponsesModel`;
it never substitutes another POST or a new model operation for an uncertain
one. A matching completed response obtained by the transport is required to
apply reconciled output. No response ID, a missing retained response or an
unavailable observer leaves the operation pending.

Response retention is a provider capability, not an assumption about the
`Idempotency-Key` header. Replay retains its original responses for GET. The
current live gateway does not proxy upstream retained-response GETs, so a
live stream-loss run cannot by itself qualify provider recovery. The header
preserves correlation and does not establish provider deduplication.

## Streaming, cancellation and budgets

The native transport consumes actual Responses SSE incrementally, including
split UTF-8 frames and CRLF framing, within a total byte bound. It validates
created/completed response identity and stages completed output items. Partial
function-call arguments do not authorize a tool: the loop applies items only
after a completed model response. The qualification JSON-lines interface
emits a final result rather than token-by-token user-visible output; parsing
text deltas internally is not a claim that a streaming UI has been built.

Cancellation is checked before new work and participates in in-flight waits.
Cancellation-first select ordering prevents an already-ready cancellation
from being polled after a first model POST or tool dispatch when it became
ready during a durable checkpoint. A cancelled tool admission remains
observation-only after recovery, even if cancellation happened before its
first submission. Cancellation acknowledgements are not terminal receipts.
Unknown model/tool outcomes remain pending with the original identities.
Physical process cancellation remains the runtime owner's responsibility.

The native core bounds assembled model-request bytes, requested output tokens,
model and tool call counts, retained tool-output bytes, model observation
time, tool observation time and polling intervals. The transport separately
bounds response bytes and idle/header waits. Runtime process time/resource
limits and the original admission deadline are part of the compiled tool
request. Observation after an uncertain effect may continue with the same
identity; it does not refresh the original permission or create another job.

The benchmark currently supplies these common ceilings:

| Budget | Configured value |
| --- | ---: |
| Model request bytes | 65,536 |
| Requested output tokens per model call | 256 |
| Model calls per case | 4 |
| Tool calls per case | 3 |
| Retained tool-output bytes | 32,768 |
| Model observation timeout | 120 seconds |
| Tool observation/process timeout | 60 seconds |
| Outer case timeout | 240 seconds by default |

The gateway enforces the common request/call ceilings and caps the output-token
request sent upstream. Requested token limits and observed usage must still
be reported separately. A byte budget is not a tokenizer-independent token
budget. Native and Codex context assembly can differ; captured model requests
make that overhead inspectable rather than assuming identical prompts.

## The bounded real tool fixture

`hepta_probe` accepts only `sum`, `lines` or `digest`. The owner compiles those
choices into a fixed Python script and data file, with artifact digests checked
before admission. The script reads the fixed file and emits a JSON value. The
model cannot choose an arbitrary command, path or destination.

All lanes use the same compiled runtime backend and fixture policy. The native
lane calls the backend in process. The Codex lanes deliver their dynamic tool
calls to the same persistent qualification helper. The helper's IPC overhead
is part of the measured composition and must be disclosed.

The generated runtime configuration uses an isolated state directory and
loopback SSH to `localhost`. It requires Linux, a functioning user systemd
session, noninteractive loopback SSH, Python and the pinned runtime behavior.
The fixture is read-only by construction. Its runtime host uses operator
execution mode; this must not be described as an operating-system read-only
command sandbox or a completed production security boundary. Existing
production runtime configuration is not changed.

## Three resident comparison lanes

| `--lane` | Executor composition |
| --- | --- |
| `native` | Resident qualification executable, native model/tool loop and in-process runtime backend |
| `app-server` | Resident official `codex app-server`, the Codex protocol driver and persistent shared runtime helper |
| `facade` | Resident wrapper around the official in-process App Server facade, the same driver and persistent shared runtime helper |

Both Codex lanes must use the same pinned official release and documented
source/build inputs. The facade keeps upstream agent behavior and typed
internal channels, but the qualification wrapper still has an outer JSON-lines
interface. Its measured cost is not a zero-serialization embedding estimate.
Store wrapper/bootstrap and any necessary lockfile changes with build
provenance; do not silently upgrade unrelated dependencies to obtain a build.

Each executor stays alive across cases. A case creates a fresh conversation
thread/session; timing includes that creation. Process initialization is
reported separately. A pending operation, lost protocol correlation or
exception aborts the lane and closes the process. The next case must not
consume stale messages and be counted as a clean warm sample.

`--mode replay` returns the same fixed model events to each executor. The
second response is produced only after feedback identifies the original tool
call and contains the exact real stdout, empty stderr and integer exit code
zero. A bad tool result cannot be replaced with a canned correct answer.
Replay's usage values are synthetic and do not measure model token cost.

`--mode live` forwards through the same gateway to the same model endpoint.
The current benchmark model identifier is `qwen38-flash-next-uc`. Record the
actual provider/model deployment when running; a model alias is not an
immutable weights digest. The small fixture tests a bounded conversation and
tool path, not broad coding-agent capability.

Actual captured request inventories determine tool parity. Configuration flags
alone do not establish that Codex sent only the shared dynamic tool. Inspect
`only_shared_tool_inventory` and `valid_equal_tool_comparison` before using
results in an equal-tool comparison. Task grading must establish actual tool
success as well as the requested final answer; process exit and benchmark
completion are not substitutes for task correctness.

## Reproduction entry points

Build the runner against the recorded native/core/runtime revisions and the
checked-in runner lockfile. From the repository's `codex-rs` directory, use
the repository test entry point and build the standalone qualification runner:

```sh
just test -p codex-execution-core -p codex-hepta-types -p codex-hepta-native-agent --lib
just test --manifest-path ../qualification/native-agent-v1/runner/Cargo.toml --all-targets
cargo build --release --locked --manifest-path ../qualification/native-agent-v1/runner/Cargo.toml
```

Supply absolute paths to the runner, pinned official CLI and compiled facade.
All three path arguments are currently required by the benchmark CLI, including
when a particular lane does not launch one of them. The fixture path is the
directory containing this README, `fixture_tool.py` and `fixture.txt`.

Run one lane at a time after build/test workloads have finished, under matched
machine conditions and resource quotas. Use a new output directory for every
invocation. The benchmark refuses to reuse an existing run directory.

```sh
HEPTA_QUAL_ROOT=/absolute/repository/qualification/native-agent-v1
HEPTA_NATIVE_BIN=/absolute/repository/qualification/native-agent-v1/runner/target/release/hepta-native-qualification
HEPTA_CODEX_BIN=/absolute/pinned/codex
HEPTA_FACADE_BIN=/absolute/pinned/hepta_facade
HEPTA_QUAL_OUTPUT=/absolute/new-qualification-series

for qual_lane in native app-server facade; do
  python3 "$HEPTA_QUAL_ROOT/benchmark_v2.py" \
    --lane "$qual_lane" --mode replay --warmup --repeats 3 \
    --output "$HEPTA_QUAL_OUTPUT/replay-$qual_lane" \
    --fixture "$HEPTA_QUAL_ROOT" --native "$HEPTA_NATIVE_BIN" \
    --codex "$HEPTA_CODEX_BIN" --facade "$HEPTA_FACADE_BIN"
done
```

Use `--tasks sum --repeats 1` for a narrow integration smoke check. For the live
layer, use the same arguments with `--mode live`, a new output directory and
an explicit `--upstream http://127.0.0.1:PORT/v1` pointing to the already
configured common Responses service. The gateway does not provision a model
service or copy production credentials.

The recorded live order is `facade app-server native`, with two repeats per
lane. Each recorded lane used a fresh operator job requesting CPUQuota 400%,
MemoryMax 8 GiB and nice 10. Reports verify the CPU and memory limits, not the
effective cpuset or nice value. The illustrative loop above does not itself create
those resource limits. Reproduce the frozen plan and limits explicitly.

The command above is a reproduction entry point, not a sufficient statistical
performance study. Preserve run order and machine conditions; repeated and
counterbalanced lane orders help distinguish executor effects from cache,
provider and host-load changes. Keep failures and aborted cases in the report.

## Evidence and resource accounting

Each run writes `REPORT.json`, model request/SSE captures, protocol logs and
private owner/runtime state. The report includes executor/helper and fixture
digests, common budgets, startup time, per-case time, observed usage, tool
inventory, attempted/correct counts, abort information and process metrics.
Read the recorded build/revision provenance together with those artifacts.

Sampling covers the benchmark, gateway and resident executor/helper process
tree. Runtime jobs can detach into user systemd units, so the collector also
discovers only this run's jobs from its isolated controller registry and
samples the corresponding cgroups. It records PID identity with process start
time, distinguishes RSS from PSS, and exposes missing measurements and cgroup
coverage gaps. Overlapping process and cgroup CPU counters must not be added
as if they were disjoint work.

Fast exited processes or disappearing cgroups may leave incomplete samples.
RSS sums can double-count shared pages; unavailable PSS is not zero memory.
Live upstream model-service compute and process memory are outside this
measurement boundary. These reports therefore must not be described as total
system memory or CPU, and they cannot establish an overall lightweight-agent
claim by comparing main-process RSS alone.

## What remains outside this qualification

The core/owner/bridge tests exercise original-operation recovery, lost stream
and acknowledgement handling, binding drift, stale generation rejection,
checkpoint corruption, cancellation before/during submission, retained-output
validation and budget boundaries. Their executed status belongs to the
recorded gate run for the exact source revision.

Production replacement still requires composition with existing authority
owners and checked execution ports, real physical-entry currentness and
revocation checks, broader tool/session paths, and independent same-model task
and failure qualification. Neither successful fixture execution nor a pure
canonical DTO projection establishes those properties. This experiment also
does not establish adaptive Cell utility or emergent general intelligence;
those need separate, fixed-executor capability evidence.

The new generic `ModelPort` and ThreadStore-owned checkpoint API are tested
integration seams. This runner still uses its qualification `SessionOwner`,
and does not consume the ThreadStore sidecar or production FinalUse writer.
See [OWNERSHIP_BOUNDARIES.md](OWNERSHIP_BOUNDARIES.md) for this distinction and
[CODEX_RECOVERY_BOUNDARY.md](CODEX_RECOVERY_BOUNDARY.md) for the different fault
targets in the native and Codex experiments.
