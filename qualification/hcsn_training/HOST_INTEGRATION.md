# HCSN TaskFlow host integration

The library provides `HcsnTaskFlowDriver`, a concrete `HcsnProcessSupervisor`, and
immutable job/receipt types. Register the driver at the existing
`AutomationStore::execute_authorized_taskflow_effect` boundary. That boundary
verifies and consumes `SignedFinalUseGrant`, records the provider attempt, and
persists observations before changing TaskFlow state.

The existing production owner is `AgentdAutomationEffectHost`, reached through
`AgentdConfig::with_automation_effect_host_file`. The new HCSN composition uses
that owner's SQLite store, current TaskFlow fence, final-use verification,
revocation refresh, and reconciliation APIs. It does not add a second scheduler.
The existing `hepta-taskflow-runtime` binary remains an unsupported standalone
host and exits without dispatching.

## Registration status on this baseline

The HCSN host configuration is schema version 2 with
`provider: "hcsn_process_v1"`. It requires an explicit `authority_profile`:

| Profile | Admission on this baseline |
| --- | --- |
| `engineering_ed25519_v1` | Available only when the Agentd host module is compiled with `cfg(test)`. Ordinary debug and release builds refuse it before creating authority or worker state. |
| `production_ml_dsa65_v2` | Always refused. The required PQ owner authority, signed revocations, protected clock, and external frontier are not composed into this baseline. |

Production deployment remains unqualified. A real signed-grant/worker engineering
test is not evidence that the production PQ authority profile is available. The
production owner composition must be completed on the branch that owns that
authority protocol; the schema-2 engineering configuration cannot downgrade it.

In the test composition, the host owns the provider scope, final-use scope,
authority/revocation inputs, canonical directories, executable/source pins, and
bounded supervision deadline. Only `hcsn.training.start` and
`hcsn.training.cancel` are registered. The host's public control payload limit
remains 24 KiB; the lower-level HCSN driver limit is separately 8 MiB.

The host retains the exact signed intent and original UTF-8 request bytes in a
private `taskflow-requests` directory under the configured supervisor store.
Retention occurs inside the already-authorized dispatch callback, with
create-only writes and file/directory synchronization before provider contact.
The retained directory is revalidated on dispatch and lookup. Exposed,
redirected, linked, missing, or mismatched retained requests cannot authorize a
launch. Recovery validates the stored intent and payload against the pending
SQLite attempt and only queries the same job.

## Initialize the concrete host

The supplied Python backend serves one private store on one Linux host. Its
canonical absolute parent directory must already exist. Initialization prepares
the engineering backend; it does not enable production Agentd registration.
Initialize the store once, before accepting jobs:

```sh
/opt/hepta/venv/bin/python -I -B /opt/hepta/release/qualification/hcsn_training/supervisor.py \
  --root /var/lib/hepta/hcsn-jobs --initialize
```

Initialization creates a mode-0700 root, job/cancellation namespaces, and a host
identity record. Keep this store across host-process restarts. A missing store,
missing reservation, changed host, or incomplete launch record cannot establish
that an earlier job never ran. The backend never recreates a missing store during
normal service. Its internal `--run` and `--worker` modes belong to supervision.

The host supplies approved SHA-256 pins and canonical directories. The native
transport verifies the Python executable and fixed supervisor script before
each exchange. A venv interpreter symlink is retained when launching Python.
The supervisor also binds its retained execution-source manifest and interpreter
hash before launching the runner/worker. Job payloads contain no command or argv.

```rust
use std::path::PathBuf;
use std::time::Duration;
use codex_hepta_automation::{HcsnProcessSupervisor, HcsnProcessSupervisorConfig,
    HcsnTaskFlowActionV1, HcsnTaskFlowDriver};

// The SHA-256 values come from the host's approved deployment metadata.
let config = HcsnProcessSupervisorConfig {
    python_executable: PathBuf::from("/opt/hepta/venv/bin/python"),
    python_sha256: approved_python_sha256,
    repository_root: PathBuf::from("/opt/hepta/release"),
    supervisor_sha256: approved_supervisor_sha256,
    durable_root: PathBuf::from("/var/lib/hepta/hcsn-jobs"),
    deadline: Duration::from_secs(5),
};
let provider_scope = "provider:hcsn".to_string();
let mut training = HcsnTaskFlowDriver::new(
    provider_scope.clone(), HcsnTaskFlowActionV1::Start,
    HcsnProcessSupervisor::new(config.clone())?,
)?;
```

The deadline bounds the short supervision RPC; training has a separate worker
lifetime limit. The transport invokes exactly `python -I -B <fixed-script>
--root <fixed-store>`, writes a typed JSON command to stdin, and accepts a bounded
JSON response. A timeout kills/reaps its own RPC child. Any ambiguity after spawn
becomes `Indeterminate`; the durable worker remains the supervisor's concern.

## Authorize and retain the exact start request

Create and claim a TaskFlow effect step using the normal owner fence. Its
`AuthorizedEffectIntent.operation_id` is `hcsn.training.start`, its destination
equals `provider_scope`, and its payload digest hashes the exact worker-request
UTF-8 bytes. The worker request retains its own training `operation_id`.
Retain those exact bytes with the host's operation record: the TaskFlow dispatch
ledger stores their digest, and recovery requires the original bytes. JSON
re-encoding can change that digest. The library accepts up to 8 MiB; an Agentd
control request remains subject to the smaller public wire limit described above.

```rust
let binding = start_intent.final_use_binding()?;
// signed_start is issued by the real final-use authority for this binding.
let receipt = store.execute_authorized_taskflow_effect(
    &authority, &mut training, &start_intent, &start_wire_bytes,
    &owner_fence, &signed_start, &binding, "hcsn-start-dispatch", now_ms,
).await?;
```

Job identity uses the existing provider key for `taskflow:{run_id}:{step_id}`;
job/output IDs also bind the payload digest. Retry attempt numbers do not create
new provider identities. HCSN step IDs must exclude `:` so this legacy key framing
cannot alias different run/step pairs. The supervisor reserves the original
identity durably before launch. Exact repeated provider requests observe it;
different bytes under the same key remain a conflict.

## Recover through lookup

Reopen the normal `AutomationStore` and obtain its pending effect record. Query
the registered driver with the retained bytes, then give a terminal observation
back to the same store under its current owner fence:

```rust
use codex_hepta_automation::{AuthorizedEffectRecovery, AuthorizedProviderEffectLookup};

match training.lookup(&pending, &start_wire_bytes) {
    AuthorizedProviderEffectLookup::Observed(receipt) => {
        store.recover_authorized_taskflow_effect(
            &pending.run_id, &pending.step_id, pending.attempt, &owner_fence,
            AuthorizedEffectRecovery::Observed(receipt), observed_at_ms,
        ).await?;
    }
    AuthorizedProviderEffectLookup::Unresolved => { /* retain pending work */ }
    AuthorizedProviderEffectLookup::ProvenAbsent { .. } => unreachable!("HCSN never proves absence"),
}
```

`Status` is read-only. It does not launch a job, signal a process, or write a
terminal receipt. Missing, malformed, mismatched, or incomplete evidence remains
unresolved. This adapter never returns `ProvenAbsent`. An unknown outcome must
not be converted into another Start, a new attempt, or a new output directory.

## Cancel with its own authorized effect

Derive the original `HcsnJobIdentityV1::for_taskflow(provider_scope, run_id,
step_id, start_payload_digest)` and serialize that identity as the cancellation
wire payload. Retain these bytes too. Create a distinct logical TaskFlow effect
with operation ID `hcsn.training.cancel`, its own payload binding, owner claim,
and signed final-use grant. Register another driver using
`HcsnTaskFlowActionV1::Cancel` and `HcsnProcessSupervisor::new(config)`; invoke the
same `execute_authorized_taskflow_effect` API with that cancellation intent.

The command binds both the cancellation dispatch and the original training job.
Cancellation succeeds only after confirmed termination, including an early
cancellation honored before worker launch. The original training effect then
observes `Failed`; the cancellation effect observes `Succeeded`. If training
already succeeded or failed, cancellation observes `Failed`. Pending cancellation
recovery uses the cancellation driver and its original cancellation wire bytes.

Running status requires the retained worker and controller incarnations. A lost
controller leaves an orphan unresolved. Linux orphan stopping is confined to
authorized Cancel handling: the backend requires a pidfd, matching host/boot/start
identity and retained worker command line, and confirmed exit. Callers never
supply or signal a PID. Status after a lost cancellation controller stays unknown
until explicit owner reconciliation; an accepted cancellation record is retained.

## Complete the learning-owner handoff

A successful supervision receipt binds the actual candidate, worker receipt,
and binary handoff digests. The learning owner still validates expected training
bindings and content through `prepare_hcsn_publication_v1` and its fenced publish
API. Evaluation, trust decisions, and model adoption remain explicit owner work.
TaskFlow completion alone never publishes or adopts a candidate.

## Explicit real-worker qualification

The [signed real-worker test](../../codex-rs/hepta-automation/tests/hcsn_signed_worker.rs)
combines the real `AutomationStore`, persistent synthetic `FinalUseAuthority`,
`HcsnTaskFlowDriver`, pinned process supervisor, and actual CPU worker. It rejects
an invalid signature before any job exists, deliberately loses the first real
provider reply, and re-executes itself in a new native process. That process
reopens the nonce journal and SQLite, rejects redispatch, queries the original
job, verifies actual output digests, and reconciles the same logical attempt.

Reconciliation preserves the first `Indeterminate` observation as history. The
test requires `state = Reconciled`, `final_outcome = Succeeded`, and the terminal
provider receipt digest, then closes and reopens SQLite again and checks equality
of the complete owner-visible terminal receipt. It does not replace historical
uncertainty with a fabricated initial success.

This test is explicitly ignored in ordinary test runs. An explicit invocation
requires `HEPTA_HCSN_SIGNED_WORKER_ROOT` naming a canonical fresh fixture directory
containing `request.json` and `supervisor-config.json`, with an initialized empty
`supervisor-store`. The config contains `python_executable`, `python_sha256`,
`repository_root`, `supervisor_sha256`, and `durable_root`; the last must equal
`<fixture-root>/supervisor-store`. Missing fixture input causes a failure, not a
reported pass. Its durable success output is `signed-taskflow.json`.

```sh
HEPTA_HCSN_SIGNED_WORKER_ROOT=/absolute/fresh-fixture \
  just test -p codex-hepta-automation --test hcsn_signed_worker --run-ignored only
```

`verify_bridge.py --supervised --signed-worker-executable <qualified-test-binary>`
creates the fixture and performs this dispatch before the existing artifact-owner
publication, cold continuation, and second-training-block checks. The binary can
also be invoked directly with `--ignored --exact
signed_authority_real_worker_cold_recovery --nocapture`; its SHA-256 and source
build provenance must be retained. A normal ignored-test build is compilation
evidence only. A failed fixture remains a retained attempt and must not be
silently overwritten or restarted.

The [existing signed TaskFlow test](../../codex-rs/hepta-automation/tests/hcsn_taskflow.rs)
uses a supervisor double for authorization, database recovery, and distinct
cancellation. The [supervisor tests](test_supervisor.py) exercise actual Linux
worker cancellation separately. The new combined real-worker fixture covers
signed **Start and recovery**; it does not claim a combined signed cancellation
and real-process termination result. All of these fixtures use synthetic trust
or explicit engineering setup and do not grant production adoption authority.
