# Actual native adapter for the frozen same-graph placement study

This adapter binds the already frozen original graph owner to the real Hepta
Runtime Full Operator `process_start`, `process_status`, and `process_read`
contract. It is not a new agent, service, transport, or runtime deployment.
No original graph inference was used to develop or test it. Local tests use
constructed byte streams and temporary files; they do not qualify the actual
18-graph experiment.

## Fixed authority and inputs

The original owner, worker, reducer, report, graph arithmetic, six selected
warmup heads, 480 input rows, A/B/C partition, numerical tolerances, and block
order remain unchanged. The adapter protocol records their exact hashes and
the root's already frozen graph/environment/dispatch identities. The root must
review/commit this adapter before the first real worker.

The only remote worker hosts are configured `main` and `pocket4`. Their absolute
Python and task-owned worker paths are constants in the adapter. Each original
stdin string is checked against its dispatch byte count and SHA256. The original
CPU quota, memory ceiling, 45-second timeout, one-thread environment, request ID,
and idempotency key are passed directly to the real start API. The worker checks
its own cgroup ceilings; the reducer validates that proof. These are local
configured ceilings, not a claim of reserved/effective host capacity.

The reducer and evidence wrapper run on main, using one fixed Python environment
and the fixed graph worktree. The wrapper reads only the pinned prepared dispatch,
its own source, the original reducer, and task-owned graph evidence. It never
opens original checkpoints, original feature archives, task gold, or retention
outcomes. New evidence is created exclusively. Existing identical bytes can be
acknowledged for publication; conflicting bytes and repeated reducer computation
are rejected. There is no caller-selected remote path or executable.

## Native identity and exact byte collection

Every actual API invocation stores its exact argument JSON and raw MCP result
before parsing, including returned failures and malformed receipts. Hashes and
logical serialized byte counts refer to that observed JSON representation, not
wire/TLS bytes. The raw MCP text contains the original decimal uint64 fingerprint;
the parser's view preserves unsafe integer lexemes as strings. `request_digest`,
job ID, exact original start-argument hash, and `reused` are bound separately.

Primary admission requires native `reused:false`. Recovery requires
`reused:true`, the same original job and native digest/fingerprint, and exactly
the same arguments/idempotency key. No timing heuristic or fresh-ID substitute
is used. A malformed/unacknowledged start remains an attempted request with its
raw receipt; it cannot be silently retried as a new cold sample.

Terminal success requires the native succeeded state, exit code zero, no timeout
or cancellation, explicit complete output, no log errors/truncation, and equal
seen/stored byte counts within the original bounds. Running systemd status,
including `ExecMainStatus=0`, is never terminal success. Each stream is collected
using `bytes_hex`, exact byte offsets, at most 16,384 bytes per page, and exact
EOF/size checks. A second terminal status must confirm stable counts and exit
identity. The textual display field is not used to reconstruct output.

The collection strategy is fixed: at most 10 terminal-status observations with
3 seconds between unsuccessful observations, at most 12 read pages, then one
final status check. Including start this is at most 24 worker native calls.
The original owner's before/after-await 60-second admission checks remain in
force. A late uninterruptible API response is retained and fails admission;
JavaScript does not claim to interrupt that Promise.

On a newly created primary job's collection failure, cleanup makes one
instrumented original status call in the original owner's separate bounded
cleanup lane. This adapter does not cancel or kill. Runtime's actual
`process_cancel` is not disguised as `process_terminate`, and no unavailable API
is invented. The original native 45-second process timeout remains the stop
mechanism; a cleanup observation is not a termination acknowledgement.

Every start attempt is marked outstanding before the awaited call, including
unknown launch outcomes with no acknowledged job ID. Only an authoritative
terminal status for the correctly bound original host/job releases that process
from the overlap gate. A still-running or unknown worker/reducer blocks the next
graph and recovery even when its failed owner record was successfully published.
The same gate covers reducer/helper launch uncertainty. Missing later graphs
remain missing and the full census cannot qualify; no new key or extra cold
sample is used to get around the uncertainty.

## Reducer, publication, and costs

The main wrapper saves the exact collection, creates a reducer launch-intent
record, and invokes the unchanged original reducer once. The subprocess has a
35-second bound inside the wrapper's native 45-second bound. It preserves CLI
stdout/stderr/exit or timeout partial output. It verifies the original reducer's
receipt bytes/hash before acknowledging completion. Reducer failure remains a
failed graph; no substitute inference is introduced.

All wrapper native calls have their own stored raw receipts and a separate
24-call/60-second helper collection bound. The reducer's native startup,
collection transfer, wrapper work, original reducer imports and execution, and
return transfer are inside the original owner's enclosing critical path. The
wrapper records self CPU/RSS and reaped-child CPU; the latter overlaps original
reducer CPU and must not be added twice. Worker/reducer inner phases are also
subsets of the owner wall, not additive latency components.

Exited or timed-out reducer output outside its cap is rejected only after
preserving bounded prefixes, exact observed lengths/hashes, truncation flags,
and the known exit status. Partial timeout output is identified as partial.

Owner and recovery publication happen after the original owner/recovery end
timestamp. Their helper/API costs are recorded separately. Every adapter
construction or reconstruction also writes a setup receipt; do not count only
the first construction when each functions invocation rebuilds the bindings.
Source evaluation, input transfer before construction, and unavailable external
JavaScript CPU/RSS remain outside those setup counters and must be disclosed.

Full raw API evidence is retained in functions store throughout the run. A later
explicit flush snapshots the ledger, sends fixed 512-KiB chunks whose base64
envelopes remain below native stdin's 1-MiB limit, verifies every chunk, then
verifies and exclusively assembles the complete ledger on main. The snapshot
ends before its own future sealing calls; those calls and their costs remain in
functions store and are returned as a separate publication record. This avoids
pretending that a ledger can recursively contain the call that publishes itself.

Functions store is session retention across invocations, not a demonstrated
power-loss or session-loss journal. Remote publication uses exclusive files and
file fsync, followed by exact-byte hash checks; directory fsync and crash/power-
loss durability are outside this experiment. Those evidence guarantees are
separate from the original Runtime's durable-job contract.

The exported native ledger includes all prior helper and worker API receipts,
failed calls, setup receipts, exact original start arguments, and the run-state
census. It does not invent native process CPU/RSS fields absent from Runtime's
status schema. Known per-process costs come from the actual worker and reducer
receipts. Unknown failure costs remain null.

## Minimal root entry

Run `build_cell_graph_native_bundle.py` in the installed source directory to
produce a bundle JSON and hash receipt. The builder verifies the unchanged
owner and all three reviewed adapter source files against the adapter protocol.
It does not read graph parameters or contact hosts. Transfer the exact bundle
source and input strings to functions store under root-owned keys.

The input object is:

```javascript
{
  dispatch_text: EXACT_DISPATCH_UTF8_STRING,
  dispatch_sha256: "595d40d93a9ba394c21c39fd41c5c8b60ab5ceddfcdb8bdd9f5102ce193fa4ae",
  request_text_by_id: { /* exactly30 original UTF8 strings keyed by request_id */ },
  wrapper_sha256: REVIEWED_WRAPPER_SHA256
}
```

One functions invocation runs one complete original graph without a model turn
inside the owner span:

```javascript
const module = eval(load("hepta.graph.native.bundle.v1").source);
const adapter = module.create({
  tools, store, load, inputs: load("hepta.graph.native.inputs.v1")
});
const graph = adapter.dispatch.graphs[adapter.getState().next_graph];
const result = await adapter.runNextGraph(graph.graph_id, module.execute);
text({graph_id: result.graph_id, status: result.status,
  critical_path_ms: result.critical_path_ms});
```

`runNextGraph` admits only the next entry in the frozen order. It records the
active graph before any worker call. It advances only after the original
collection and owner are published. A publication failure retains the owner in
functions store and leaves the graph active: stop and reconcile evidence; do not
invoke its worker again or change the key. This guard deliberately does not
provide a convenience restart that could manufacture another cold sample.

After all 18 primary graph records are published, separately call, in order:

```javascript
await adapter.runRecovery("b0-A-s0", module.recover);
await adapter.runRecovery("b0-B-s0", module.recover);
await adapter.runRecovery("b0-C-s0", module.recover);
```

Each call uses the original cached job; an incomplete/failed original remains
an unavailable reference. No old worker CPU is charged again. This is an
idempotency lookup/read exercise, not a crash, power-loss or model migration
experiment. Afterwards use `await adapter.flushRawLedger()` and retain its
separate sealing receipts. Run the unchanged original full-census reporter only
against the complete main `graphs/` evidence tree.

## Tests and limits

```bash
node test_cell_graph_native_adapter.js
python3 -W error -m unittest test_cell_graph_native_wrapper -v
```

The JavaScript tests compare standard SHA256/RFC4648 vectors and independent
Node crypto/Buffer oracles in a VM without Node/browser codec globals. They also
exercise synthetic native response framing, exact uint64 preservation, full
12-page output, truncation/cursor failures, explicit failed/running states,
complete order/concurrency, unchanged identity recovery, repeated construction,
and greater-than-1-MiB raw-ledger chunking. Python tests use temporary fixture
paths and a fixture reducer, preserving the separation between interface tests
and real numerical qualification.

The native adapter itself has not established task competence, learning,
beneficial splitting or edges, migration benefit, whole-system net benefit,
or AGI. It makes the bounded same-fixed-graph placement experiment executable
and auditable on the original heterogeneous deployment stacks.
