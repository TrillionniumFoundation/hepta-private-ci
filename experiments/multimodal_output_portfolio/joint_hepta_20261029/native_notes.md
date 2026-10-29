# Native owner integration and its scope

`native_build.py` extracts source commit
`a50c8974ac23c20c5174f7c3ad542a96e5652854` using Git objects. The three crates,
`AgentdNeuronOwner`, original research host, feature port, event ledger and
calibration profile are copied byte for byte. The isolated workspace changes
neither production source nor production configuration. Its lock is derived
from the original full `Cargo.lock`, pruned by Cargo, then checked for identical
package name, version, source and checksum before a `--locked` compile.

```bash
git fetch --filter=blob:none --depth=1 origin a50c8974ac23c20c5174f7c3ad542a96e5652854
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.native_build --repository . --destination /tmp/joint-native
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.native_bridge --binary /tmp/joint-native/target/debug/examples/owner_host --output /tmp/joint-native-probe
```

The last command must execute the real Rust host. It checks an actual durable
prefix, a new OS process reopening that prefix, STOP preventing later dispatch,
and expired native calibration preventing a third dispatcher call. The separate
`test_native_bridge.py` tests use an explicitly fake transport for Python adapter
contracts; their success is **not native owner qualification**.

## Caller interface

```python
guard = NativeGuard(
    binary=owner_host_binary,
    directory=new_episode_directory,
    case="bounded.stable.case",
    model_sha256=sha256_of_the_loaded_trained_checkpoint,
    profile_sha256=sha256_of_the_frozen_ndu_profile,
    allowed_actions=("continue", "delivery", "stop"),
    max_actions=8,
    expires=64,
)
record = guard.perform(action_name, concrete_json_action_trace, dispatch_callback)
recovery = guard.reopen()  # Optional; requires at least one committed tick.
terminal = guard.perform("stop", {"reason": "policy_or_budget"})
```

`readout`, `calibration`, `build_receipt` and `max_artifact_bytes` are optional
keyword arguments. The qualified `BUILD_RECEIPT.json` is found automatically at
the build root unless its path is supplied. Its source identity, unchanged
source declarations and exact binary digest are required. The default readout
is a constant untrained diagnostic head; it never selects a generation action.

The dispatcher is a zero-argument callback, executed only after an actual native
gate. It returns `artifact_refs`, `artifact_sha256` and `public_feedback`. The
guard reopens every referenced file to verify its bytes. Pure recurrent-state
updates may return empty artifact dictionaries but must provide a real
`final_state_digest`. Public feedback must be one of `-1, -0.5, 0, 1`, matching
the inherited finite encoder; mapping a continuous measurement into that alphabet
is a separately declared caller rule, not the native model's NDU valuation.

Each nonterminal action costs three actual owner ticks: gate, feedback and hold.
At most eight such actions plus one terminal tick stay within the original
32-record journal bound. This extends serial use of the existing finite host;
it does not introduce an unbounded production controller. Native abstention
stops subsequent dispatch. An abstention after a callback does not undo the work
already performed or remove its cost.

## Failure closure

`perform`, `reopen` and `stop` fail closed on ordinary Python exceptions, retain
the failure receipt, close/reap their owner process, then re-raise the original
error for the caller's terminal ledger. A model or observer failure outside
these methods can call `guard.abort("model_failed", action_trace=trace,
error=exc)`. This operation is idempotent and returns cleanup evidence. It does
not swallow `KeyboardInterrupt` or `SystemExit`.

Abort attempts a native terminal tick and Close while the transport is still
synchronized. A lost response makes subsequent protocol replies ambiguous, so
that transport receives no further commands. Closing stdin and reaping the
exact owned PID then takes priority; bounded TERM/KILL escalation is confined to
that process. The receipt distinguishes an acknowledged native STOP from mere
process termination and reports `native_process_reaped`, `cleanup_errors` and
the actual child exit status. It never claims a successful native checkpoint
transition when the acknowledgement was lost. `NATIVE_FAILURE.json` and
`NATIVE_RECEIPT.json` retain this evidence when the filesystem remains writable.
The caller must still record the failed/refused episode, already written files,
and all physical work; abort does not roll back or erase them.

## Joint checkpoint identity

The frozen generator checkpoint digest and NDU profile digest enter the bridge
identity; that identity's digest enters every native event. Each event also
binds the selected action trace, prior delivered artifact hashes, current
verified output hashes and reported final recurrent-state digest. The native
journal binds these receipts to its own checkpoint frontier.

The caller must bind the digest of the checkpoint actually loaded, and must
save/restore the Python tensor state separately: all Hepta layer states, decoder
state and output frontier, RNG state, policy state, remaining resources, model
identity and profile identity. Passing that saved state digest as
`final_state_digest` binds it to the owner event. `guard.reopen()` verifies native
state recovery; it does not by itself reload or verify Python tensor state.

## Cost accounting

The final receipt reports native tick count, journal bytes, peak checkpoint
bytes, per-request observed processing time and native CPU. The CPU measurement
uses POSIX `wait4` for each exact owner subprocess, including ticks, startup and
cold recovery. `native_owner_cpu_seconds` is final only after the host exits.
The host-process CPU field includes Python dispatcher work and overlaps the
caller's episode meter; do not add it again to an end-to-end self-plus-children
CPU measurement. On POSIX, reaped child usage is also accumulated in
`getrusage(RUSAGE_CHILDREN)`, so the caller's final meter can include this exact
same native CPU without adding the native subtotal again. Other children such
as codecs remain the caller's metering responsibility.

`RUSAGE_CHILDREN` exposes this usage only after a child is reaped. A caller using
only cumulative self-plus-children readings therefore charges a still-live
owner's earlier ticks at the subsequent reopen or terminal close. Its final
episode cost includes the work exactly once; an instantaneous per-decision
budget requires an additional live-process measurement or an explicitly
declared delayed-settlement convention. The host's `execution_micros` fields
are elapsed timing receipts and must not be relabeled as CPU measurements.

The measured native owner retains `DENY_ALL`. The PyTorch generator and NDU
policy remain Python-executed under a bounded research permit; this integration
does not activate a production daemon or execute tensor layers inside the
original finite feature port. Native confidence concerns only finite-domain
encoder validity, not semantic output quality.
