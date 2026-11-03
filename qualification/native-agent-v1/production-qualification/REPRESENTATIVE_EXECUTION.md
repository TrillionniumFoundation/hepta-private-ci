# Executable representative comparison

For observed results and outstanding evidence, see
[REPRESENTATIVE_STATUS_20261029.md](REPRESENTATIVE_STATUS_20261029.md).
The sections below describe the available implementations; they are not a list
of experiments that have all passed.

`representative_compare.py` executes edits, observed test-failure repair,
read/write/validation chains, and a real stdio MCP exchange through the existing
native qualification runner and runtime jobs owner. Each action has an original
admission and terminal result. The test file and other immutable inputs are
hashed and checked independently after execution.

The owner remains the qualification `SessionOwner`. These runs do not close the
registered `production_owner`, Agentd/QueueStore/FinalUse, whole-controller
recovery, or live third-party connector requirements in `corpus.json`.
They must not be fed to the older production checker as completed production
slots. The default suite contains four cases. Long output and controlled faults
have separate candidate entry points; their remote results are not established
in the status snapshot. PTY and a live third-party connector remain outside the
executed slice. The complete fourteen-case production verdict remains held.

## Replay

```sh
python3 qualification/native-agent-v1/production-qualification/representative_compare.py \
  --output /absolute/new/run-directory \
  --native /absolute/hepta-native-qualification \
  --codex /absolute/official-codex \
  --facade /absolute/official-in-process-facade \
  --codex-build-evidence /absolute/0.166-build/OFFICIAL_BUILD.json \
  --native-build-evidence /absolute/current-native-build/NATIVE_BUILD.json \
  --mode replay --group behavior_matched --repeats 3
```

All lanes receive the same response sequence for each case. The gateway refuses
to emit the next replay response unless the real original tool feedback is
present and has the expected exit status. The repair starts with an actual
failing test. A replay success proves execution/feedback compatibility, not the
model's ability to discover a repair. Usage in replay is synthetic.

Each case starts a fresh resident executor. Startup and task wall time are kept
separate. No p95, total resource-efficiency conclusion, or performance ratio is
emitted. Every attempt is retained, and a failed case is not silently retried.
The old three read-only controls and their archived reports are unchanged.

## Current native library and one runtime source

The native lane also requires an actual build record. Copy the complete tracked
representative runner from commit
`4dcc124675249efc779200e5190b3a888758d688` into the current isolated owner
worktree, then apply the current runner changes. Do not reuse the older runner
binary merely because its command name is unchanged. Its local dependency must
resolve to that worktree's `codex-rs/hepta-native-agent`, including streaming,
pending-operation handling and the current context policy.

The runner now freezes `NativeAgent::context_policy().binding_value()` together
with its original session configuration. A pending qualification session with
an absent or changed policy binding cannot be reopened as a new-policy session.
The `ready` message reports the actual derived binding. `--build-identity`
reports compiled native policy/projection versions, the source-tree digest and
the runtime base commit without opening a Hepta runtime, a session or a provider
connection. The builder checks that response from the actual output binary.

The owner workspace and standalone qualification runner had different declared
runtime git pins. The build gate therefore reads **both actual resolved Cargo
graphs**, rejects duplicate runtime packages, and requires their runtime package
identity to agree. It supports either one published exact revision or an
explicit, recorded local Cargo path patch. For a path-patched candidate, the
runtime base commit alone is not the candidate identity: all dirty paths and
runtime package source files are hashed as part of the source-tree digest.
The record labels this as a local path variant.

Use a dedicated TOML file containing only `[patch]` entries for the runtime
repository and absolute paths inside the isolated runtime worktree. Preserve
that file. Prepare and inspect the owner/runner lockfile changes under that same
patch before building; the builder uses `--locked` and never updates a lockfile.
It records the exact configuration, both metadata commands and outputs, each
local dependency's files, the dirty owner/runtime sources, the build command,
compiler information, original log, output binary and compiled identity.

```sh
python3 qualification/native-agent-v1/provenance/native-current/build_native.py \
  --source /tmp/hepta-owner-convergence-20261030 \
  --runtime-source /tmp/hepta-runtime-convergence-20261030 \
  --runtime-rev cdb0b0fb4dd25f9990d650468527f0118ae82098 \
  --cargo-config /absolute/recorded-runtime-patch.toml \
  --output /absolute/fresh-native-build \
  --target-dir /absolute/native-cargo-cache \
  --jobs 3 --profile dev --build-timeout 3600
```

That commit is the currently prepared candidate's **base**. If the candidate is
committed before building, supply its new actual HEAD rather than that older
base. All source changes must be complete before the build snapshot. Freeze the
owner worktree, runtime worktree, patch configuration and git HEAD values until
the comparison finishes. The builder verifies equal before/after snapshots;
the comparison checks them again before and after its attempts. Build timeout
terminates the original Cargo process group and records the original failure;
it does not restart compilation under a replacement identity.

Use the resulting `bin/hepta-native-qualification` together with its
`NATIVE_BUILD.json` for **all three** lanes, including the shared tool bridge for
Codex. This prevents the comparison from accidentally using an old runtime for
one lane. The evidence is an observed source/build inventory, not a claim of a
hermetic build. The benchmark still uses the qualification `SessionOwner`;
the production Core/QueueStore/FinalUse integration tests remain separate.

## Fixed Codex 0.166.0 source and adapter

The comparison now requires tag `rust-v0.166.0`, official source commit
`6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`, and the actual CLI and facade build
record. The release reference is
<https://github.com/openai/codex/releases/tag/rust-v0.166.0>. The old 0.165
artifacts and their results remain historical evidence and do not satisfy this
gate. A version string alone is insufficient: both executable byte sizes and
SHA-256 values, the source pin, original build logs and adapter patch files must
match the supplied build record.

Use an isolated, clean official Git checkout at that commit, with the release
tag fetched. The pinned source declares Rust 1.95.0. The builder requires that
installed toolchain; it does not install software or silently substitute one.

```sh
python3 qualification/native-agent-v1/provenance/official-0166/build_codex.py \
  --source /absolute/clean-codex-0166-checkout \
  --output /absolute/fresh-codex-0166-build \
  --target-dir /absolute/codex-cargo-cache \
  --jobs 3 --profile dev --build-timeout 3600
```

The release source's lock file records local workspace packages as `0.0.0`
although the workspace version is `0.166.0`. The builder repairs only those
local version entries and verifies that every external locked package is
unchanged. It first builds and copies the CLI from that source, before adding
the facade observation patch. It then applies the checked 0.166-specific patch
and builds the qualification facade as an upstream `app-server-client` example.
The patch exposes the real initialize result and passes through the caller's
original initialize parameters; the ordinary upstream start API retains its
behavior. Agent execution, model/tool handling and persistence remain upstream.

This is a source-built qualification variant. Its CLI has the disclosed local
lock repair; its facade additionally has the observed-handshake bridge. It is
not claimed to be the byte-identical published release executable. All changes,
commands, toolchain, build profile and output hashes are recorded. Build failure
leaves `BUILD_FAILED.json` and logs in the fresh output directory. Preserve that
attempt before making a new isolated build; do not relabel an old binary or
overwrite earlier evidence.

## Explicit observed-live mode when deployment identity is unavailable

`--mode live` keeps its fixed-identity evidence requirements. It never falls
back automatically. When that evidence is unavailable, an operator can
explicitly choose **`--mode observed-live`** to measure real task execution
against the currently configured endpoint. This is a separate observation
mode, not a completed fixed-model qualification slot.

```sh
python3 qualification/native-agent-v1/production-qualification/representative_compare.py \
  --output /absolute/fresh-observed-live-window \
  --native /absolute/current-native-build/bin/hepta-native-qualification \
  --native-build-evidence /absolute/current-native-build/NATIVE_BUILD.json \
  --codex /absolute/0.166-build/bin/codex \
  --facade /absolute/0.166-build/bin/hepta_facade \
  --codex-build-evidence /absolute/0.166-build/OFFICIAL_BUILD.json \
  --mode observed-live --group behavior_matched --repeats 1 \
  --upstream http://127.0.0.1:18081/v1
```

This example plans twelve original task attempts and retains every failure;
it is not an instruction to retry failed tasks. All lanes use the same selected
endpoint, requested alias, task/tool surface and budget policy within the
recorded client time window. Actual initial provider conditions are still
measured, and framework-added context may differ. Actual provider response
model fields are retained individually, including `null` when missing.
Alias equality does not establish equal weights, a stable hidden provider
revision, identical first inputs or identical subsequent trajectories.

`--model-evidence` is optional in this mode. It may point to an existing
nonsecret configuration/deployment observation JSON file; its actual file hash
is retained. No revision or weight hash is invented to satisfy the strict live
schema. The run records `model_identity.status = "unattested"`,
`strict_live_qualification_requested = false`, and
`strict_live_qualification_passed = false`. Unattested revision, weight hash and
expected response identity remain `null`; any supplied raw observation remains
available separately. The window timestamps and per-attempt timestamps are
client observations, not a provider deployment lock.

Capability and cost completeness are distinct. Each successful observed task
still requires the actual final answer, independent workspace oracle, original
tool proposals/admissions and exact feedback checks. Missing provider usage
does not fabricate a capability failure; it leaves cost accounting incomplete
and exact token totals `null`. Capture/admission/feedback or task failures are
still failures. No additional model POST or replacement operation is created
to repair a missing usage field.

`observed_success_costs.by_case_and_lane` reports all original attempted costs
for each task and lane, including failed attempts, divided by the number of
independently observed capability successes. It preserves the known token
subtotal separately; exact per-success tokens are `null` if any contributing
attempt has unknown usage. The quotient is also `null` when there is no observed
success. Attempt wall time includes startup through shutdown and excludes
workspace preparation and the post-run correctness audit. Whole-system CPU,
provider GPU time and monetary cost are `null`; available local sampled process
metrics remain in each original result with their coverage limitations.
These are descriptive costs for this matrix and time window, not a future
success-cost estimate or a version-fixed model comparison. Do not pool these
rows with replay or strict-live qualification results.

## Minimum controlled experiment matrix

| Phase | Lanes | Cases | Repeats | Planned attempts | Purpose |
| --- | --- | --- | --- | --- | --- |
| Replay gate | app-server, facade, native | edit, repair, multi_tool, mcp_readonly | 1 | 12 | Confirm original proposals, tool effects and feedback with the new binaries |
| Live baseline | app-server, facade, native | same four cases | 3 | 36 | Record bounded observed behavior on the same frozen provider deployment |
| Controlled recovery | all three lanes | cancel, recover_process | 1 | 6 | Separate original-operation recovery checks; never pool with latency samples |
| Long-output slice | all three lanes | long_output | 1 | 3 | Verify retained raw output and the bounded presentation with explicit larger raw-output profiles |

Run each phase into its own fresh directory. The live baseline's default ceiling
is 216 generation requests (36 attempts × 6), 55,296 requested output tokens
(216 × 256), and at most 64 KiB per model request. These are ceilings, not
observed consumption. The alias, actual reported model, provider deployment
revision and model evidence must be frozen before the first attempt. The same
source workspace, immutable tests, base instructions, user task, dynamic-tool
descriptors, output/context/tool budgets, network capability and observation
cadence apply to all three lanes. Lane order rotates by repeat. A failure uses
its original slot and is retained; it does not authorize a replacement run.

The harness also records actual first-provider-request conditions. Framework
environment messages, schemas, reasoning settings or other context may differ
even when the requested task policy is identical. `initial_condition_parity`
reports this explicitly and never rewrites captured inputs to manufacture
equality. A strict same-input claim requires those observed fields to agree.
Live trajectories can then diverge as the agents choose different actions;
later requests are not assumed equal. Three repeats per case do not justify a
p95 or general quality ranking. The separate individually-optimized group must
declare its actual applied policies and must not be pooled with this baseline.

## Failed attempts and resource accounting

Every observed gateway POST has a durable started row before validation or
provider dispatch, and a finished row if the handler returns. Bounded original
request bytes, effective forwarded bodies and response captures are retained.
Over-budget or malformed requests proven not to have reached a provider have
zero provider tokens, while the local attempt and its wall/CPU/memory window
still count. Once provider dispatch is attempted, missing or partial terminal
usage is **unknown**, including connection failures. It is never imputed as
zero, silently retried, or discarded. A provider's observed terminal usage
counts even if the task, independent oracle or provider completion failed.
Duplicate or ambiguous response identities cannot create an exact token total.

Each row records startup, task wait and shutdown wall time, original pending
turn/job identities when available, all original tool admissions, and sampled
resources even on failure. The existing process-metrics V2 collector covers the
comparison controller's descendants plus detached runtime cgroups discovered
only from that attempt's fresh controller registry. It does not select the
whole parent cgroup, which could contain unrelated work. Sampling includes the
local observer and excludes workspace setup and post-run correctness audit.
Its existing coverage warnings remain: PSS may be incomplete, RSS sums shared
pages, polling can miss short-lived processes, process/cgroup CPU totals overlap
and cannot be added, and provider inference CPU/GPU is outside this local scope.

`REPORT.json` v3 aggregates **all** attempted tasks by lane, including failed
ones. A known token subtotal is shown separately from the exact total; the
exact total is null whenever any dispatch or ledger remains unresolved. Raw
resource rows stay available rather than producing a success-only efficiency
ratio. An in-flight capture after shutdown remains unresolved at the report's
observation time and requires reconciliation of that original evidence, never
another generation POST.

## Live and separate configurations

Live uses the existing bounded Responses gateway and requires a nonsecret model
identity evidence file. It captures actual request bodies, Responses streams,
reported model identities and usage. An alias by itself is insufficient.

```json
{
  "schema": "hepta.model-identity.v1",
  "model": "qwen38-flash-next-uc",
  "response_model": "EXACT_REPORTED_MODEL",
  "provider_revision": "EXACT_PROVIDER_DEPLOYMENT_REVISION",
  "model_sha256": "64-lowercase-hex-from-the-frozen-model",
  "evidence_sha256": "64-lowercase-hex-of-the-deployment-evidence"
}
```

Use `--mode live --upstream http://AUTHORIZED-ENDPOINT/v1 --model-evidence PATH`.
This interface does not read credentials or manufacture model identity evidence.
The operator must independently verify the pinned deployment and preserve the
source evidence. The run cannot detect an upstream replacement hidden behind
unchanged metadata; this remains a deployment-observation limitation.

`--group individually_optimized` requires a `--profiles` JSON mapping for all
three lanes. Each lane has `budgets` with the same fields as `BUDGET` in the runner
and a nonempty `notes` description. These ceilings are actually passed to the
native loop, Codex tool dispatcher and common gateway. This does not claim to
expose every engine-specific optimization. Behavior-matched profiles require
identical ceilings, while actual request/context parity is retained for audit.
Use separate fresh output directories for each mode/group; do not pool them.

## Long output qualification slice

Use `--cases long_output --profiles qualification/native-agent-v1/production-qualification/long_output_profiles.json` in a fresh output directory. Local fixture tests observe the frozen generator's 1,179,648 stdout bytes. The separate runtime experiment is designed to execute that generator through its original runtime-owned process descriptors. Its equal profiles retain up to 4 MiB, while the case independently caps each model-facing tool item at 4,096 bytes. The excerpt explicitly names the original host, job, operation, idempotency key and runtime-intent digest and retains exact full-stream lengths and SHA-256. The audit requires the original job's retained files and compares every byte with a separately generated oracle. It rejects a changed reference, missing terminal record, extra runtime job, oversized item or incomplete stream. This implementation description does not establish that the remote long-output experiment has passed.

The native default presentation hook preserves the original complete-byte receipt check and is bounded by the existing tool deadline and cancellation. The qualification bridge overrides that hook; the production Agentd continuation fold still uses its default full JSON policy. Passing this slice therefore does not close the production long-output recovery gate.

The private qualification host uses the existing runtime's operator contract, which requires `allow_job_network=true`. This is an explicitly network-capable operator configuration, not proof of network isolation. All three lanes use the same capability. Frozen fixtures and MCP stdio contain no external-service operations.

## Controlled cancellation and process restoration

The current `representative_faults.py` entry verifies the exact official 0.166
build and the current native library/runtime build before creating an output
directory or launching an owner. Use one fresh output directory for each of
the six lane/case pairs:

```sh
python3 qualification/native-agent-v1/production-qualification/representative_faults.py \
  --output <fresh-pair-output> \
  --native <current-native-proof-dir>/bin/hepta-native-qualification \
  --codex <official-0166-proof-dir>/bin/codex \
  --facade <official-0166-proof-dir>/bin/hepta_facade \
  --codex-build-evidence <official-0166-proof-dir>/OFFICIAL_BUILD.json \
  --native-build-evidence <current-native-proof-dir>/NATIVE_BUILD.json \
  --cost-scope execution-observation \
  --lane <native|app-server|facade> --case <cancel|recover_process>
```

These fixed-response runs are separate from latency samples and live
model-quality comparisons. The v2 report retains both verified builds, the
executed owner boundary, `product_total_cost: null`, and
`execution_layer_causal_attribution: false`. `--cost-scope product-total`
fails before even binary checks. The default four-case representative matrix
does not run these six slots. The old `fault_recovery.py` entry and its receipts
remain historical; substituting a binary or output path does not qualify them
under this new owner/UI policy.

The watcher requires the original immutable admission, original runtime job, durable pending checkpoint, actual child metadata and retained `STARTED` bytes before acting. Cancellation sends the owner's existing cancel/session message, then re-enters the same immutable owner command only for observation until a complete durable original cancellation terminal appears. Codex lanes also require the original turn's interrupted notification. Restoration SIGKILLs only the waiting runner created by this experiment, verifies its injected EOF, starts exactly one replacement helper and re-enters the unchanged command. The runtime child remains untouched and creates the original `done` artifact. Both variants verify there is one original job and terminally consumed call, no live original child and no duplicate model request.

These fixtures exercise SessionOwner, not production Agentd ThreadStore, QueueStore or FinalUse. Production cancellation and controller restart gates remain separate. A tool/transport failure outside the explicitly verified injection point is retained as failure and never authorizes restart.

The shared turn owner is frozen under the same v2 scope as the representative
matrix. Codex tool proposals carry their unchanged original parent thread and
turn IDs; the original manifest must retain that exact parent, current context
policy, complete configuration, and UI contract. The replacement runner must
announce the identical ready contract, and a second EOF cannot authorize a
second restart. Native UI frames before and after the injected boundary are
consumed as events, never mistaken for a final result. A recovered completion
requires actual text deltas and matching completion under one original item
ID. This fixed script emits its assistant answer after restoration; it does
not qualify arbitrary cross-process replay of previously completed UI items.
For cancellation, actual native/Codex events are retained through the original
terminal observation, but final-answer completion is explicitly not applicable
to an interrupted turn. No synthetic delta or fabricated completion is used.

## Owner boundary, shared turn scope, and required streamed UI

The current matrix accepts only `--cost-scope execution-observation` (the
default). Every frozen case, result, aggregate and report records an
`owner_boundary`, `product_total_cost: null`, and
`execution_layer_causal_attribution: false`. `--cost-scope product-total`
fails before binary checks, output creation or any dispatch. Supplying strict
model identity and passing every task cannot satisfy this independent gate.

The native lane executes the native loop with a private, file-backed
`SessionOwner`. The Codex lanes additionally execute the actual Codex Core
thread/turn owner through `thread/start` and `turn/start`. All lanes share the
runtime jobs implementation, but none traverses the product's complete Agentd
signed admission, canonical context, Queue, ProductionDurableWriter, external
FinalUse issuance/claim, or product restart/reconciliation path. Native also
does not traverse the actual Core/ThreadStore UI/history owner. The observed
cost difference therefore describes these complete qualification harness
combinations; it cannot establish product total-cost savings or isolate the
causal cost of replacing an execution layer. A separately measured owner
constant cannot safely be added or subtracted to manufacture that conclusion.

New matrix runs explicitly freeze
`qualification_owner_scope = "hepta.qualification.turn-owner.v2"`. All Codex
tool proposals in one turn use one durable backend session, carrying the
original Codex thread/turn IDs and unmodified call IDs/arguments. The handle is
reopened and the hash chain verified for each external tool request; the
native loop retains its handle throughout the turn. This remaining lifetime
difference is recorded. Each admitted request keeps its original operation
key, intent and parameters. Duplicate completed calls only return the
previous output; an unknown pending call, cancelled turn, changed proposal,
changed parent binding, or exceeded budget cannot admit another call.
An elapsed shared-tool deadline durably closes fresh admission even after the
same original operation is later reconciled to terminal; reconciliation never
turns a failed measurement into a newly executing continuation.

The old per-call CLI scope is observation-only for an existing pending or
completed tool session. It is never migrated into v2, and no old operation key
is rederived under a new parent. Old sessions lacking the current frozen
context policy remain held. Historical per-call commands and `fault_recovery.py`
do not become valid fresh v2 runs merely by changing their output directory or
binary version; use the explicitly gated current entries above.

The native runner now calls `run_with_events`. Both native JSON-lines deltas
and Codex `item/agentMessage/delta` notifications are actually consumed by the
same bounded `UiCollector`. An assistant's completed text must match its real
streamed text under the same item ID. A final-only reply does not satisfy this
capability; no synthetic delta is produced from final text. The contract caps
each UTF-8 delta at 32 KiB, each item at 64 KiB, 1,024 items, 4 MiB retained text
and 8,192 events. `ui-events.jsonl` and `ui_observation` retain the consumed
events and original timing. This is a qualification collector, not evidence
that the native lane paid for Core UI ownership. Streaming errors preserve the
original pending operation rather than opening another model POST.
This qualification collector covers a fresh attempt. A pending attempt fails
and retains its evidence; it is not reopened under a new collector to rescue a
score. Cross-process UI delivery/replay is not qualified here. Production Core
stream/recovery tests remain separate, and old qualification completion items
must not be replayed into an existing collector as if they were new events.

To qualify product total cost later, use the existing product admission and
owner endpoint with its already configured authority for both backend choices,
require the same original Queue/ThreadStore/writer receipts and required
capabilities, and measure from accepted input through durable settlement and
terminal resource accounting. No fixture signer, substitute owner store or
synthetic authority may be introduced to make the gate pass.

