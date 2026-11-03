# P3 worker lifecycle resource receipt

`worker_lifecycle.py` runs one exact native worker under the existing Runtime
job. It preserves the worker's stdout bytes, saves its exact ready JSON line,
and obtains final resource usage by actually waiting for that child. It creates
no owner authority, daemon, replacement task, session, or process group. The
worker executable, model and shard configuration remain the existing P3 inputs.

## Deploy and launch once through Runtime

Copy this helper to both hosts and retain its SHA256 as a deployment cost. The
receipt's parent directory must already exist and be private to this experiment.
The receipt filename must be new; any existing receipt refuses a second launch.
Use the SHA256 of the actual built worker binary on that host. A hash mismatch
fails before creating a child.

The following is the exact argv shape to submit as one Runtime `process_start`
operation, substituting only the uppercase path/hash values:

```text
/usr/bin/python3 -I -S /tmp/hepta-cell-locality-20261030/worker_lifecycle.py --receipt /tmp/hepta-cell-locality-20261030/main-worker-lifecycle-v1.json --worker-sha256 ACTUAL_MAIN_WORKER_SHA256 -- ABSOLUTE_MAIN_WORKER /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-main-20261030 1 0 ABSOLUTE_MAIN_SHARDS_CONFIG
/usr/bin/python3 -I -S /tmp/hepta-cell-locality-20261030/worker_lifecycle.py --receipt /tmp/hepta-cell-locality-20261030/x230-worker-lifecycle-v1.json --worker-sha256 ACTUAL_X230_WORKER_SHA256 -- ABSOLUTE_X230_WORKER /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-x230-20261030 1 0 ABSOLUTE_X230_SHARDS_CONFIG
```

For structured `process_start`, use `executable: "/usr/bin/python3"` and each
remaining token as a separate `args` entry. Keep the original planned cwd,
resource bounds, host binding and unique original idempotency key. Do not both
execute these shell templates and submit the same work through Runtime.

An optional `HEPTA_QUALIFICATION_JOB_LABEL` is an experiment label only. The
helper does not set a job ID. If Runtime already provided `HEPTA_RUNTIME_JOB_ID`,
the helper records that inherited value as an observation, not as independent
identity proof. Retain a separate external association between Runtime's actual
start receipt/job ID, helper receipt path/hash, ready line and unit properties.
Do not edit a completed helper receipt to insert a subsequently learned ID.

Use the real ready `address`, `instance`, `generation` and artifact hash in the
deployment file. The helper adds no stdout banner. The first line is precisely
the worker's original bytes, with its original whitespace and newline. Its
base64 form, SHA256, parsed JSON and observation time are stored before that
line is forwarded. The worker's own `startup_ns` and the wrapper's
`wrapper_start_to_ready_seconds` measure different scopes.

## Cancellation and ownership boundary

Cancel only the original Runtime worker job. Use the existing Runtime cancel
API with that job ID and sufficient observation grace, for example
`grace_seconds: 10`. The wrapper's default direct-child policy is SIGTERM,
one-second grace, then SIGKILL if needed and up to two seconds for `wait4`.
Repeated signals do not extend those deadlines. Filesystem failures or an
uninterruptible kernel wait can still prevent a completed receipt; Runtime's
original owner remains responsible for reconciliation.

Signals normally use a pidfd opened for the wrapper's own child. A failed pidfd
acquisition immediately after `Popen` can use only that still-unreaped direct
child PID for cleanup. No signal is sent after `wait4` reaps the child, and
`ECHILD` invalidates all later numeric-PID signal authority. The wrapper never
signals a process group, scans arbitrary PIDs, or adopts an unrelated process.

The procfs PID is resolved from the pidfd's `Pid`/`NSpid` metadata before reading
start ticks and cgroup data. This matters in a PID namespace whose mounted
procfs describes an ancestor namespace: `/proc/<getpid()>` may otherwise name
an unrelated process. The receipt records both the syscall PID and procfs PID,
namespace PID sequence, boot ID, start ticks, observed parent, session, process
group and cgroup. None of these observations creates a new execution authority.

The child inherits the wrapper's Runtime-owned session/process group and cgroup;
this helper deliberately does not call `setsid` or `setpgid`. The receipt proves
only its direct-child lifecycle and records the observed inheritance. It does
**not** prove arbitrary descendant cleanup or a specific systemd `KillMode`.
For this deployment, separately archive the original unit's `KillMode` and
`ControlGroup` while it exists, bind them to the original Runtime job, and
verify that Runtime retains the required whole-job cleanup scope. A cgroup path
string alone is not that proof. A future worker that changes sessions or cgroups
requires separate containment qualification.

Stdout forwarding uses nonblocking writes and a bounded 2 MiB queue. A full log
pipe cannot strand the wrapper in a blocking write while cancellation is
pending. Incomplete forwarding is recorded separately; it is never described
as complete output because the child was reaped. Stderr remains on Runtime's
existing log stream. This is a native TCP-worker wrapper, not an interactive
terminal or general subprocess-session manager.

## Read the resource receipt

The `hepta.cell-worker-lifecycle.v1` receipt is created exclusively before the
single launch attempt, then updated using fsynced atomic replacements. `ready`
is a running observation. `complete: true` means the original direct child was
actually reaped and its `wait4` resource values were obtained; it does not mean
all descendants or all output streams were proved complete.

| Field | Actual accounting scope |
|---|---|
| `wait4_usage.user_cpu_seconds` and `system_cpu_seconds` | Final usage returned for the one reaped direct child, including descendants it itself waited for |
| `wait4_usage.peak_rss_kib` | Linux child high-water RSS in KiB; not a sum of concurrent process RSS |
| `rusage_children_before` / `after` | Actual cumulative waited-child counters in this wrapper |
| `rusage_children_cpu_delta_seconds` | Difference of the CPU counters; cross-check against `wait4`, not additional CPU to add again |
| `wrapper_self_usage` | Wrapper's cumulative own CPU/RSS through the final sample, before the last receipt serialization/fsync |
| `observed_lifecycle_wall_seconds` | Observed helper execution from `run()` entry through final sampling; Python startup, final publication and Runtime startup/SSH/supervisor costs need the outer measurement |
| `stdout_transport_complete` | EOF observed and no buffered stdout remains; independent of child resource completeness |

Peak RSS is a maximum. Do not subtract before/after maxima or add wrapper and
worker peaks to claim a simultaneous combined peak. Do not double-count the
worker's `wait4` CPU and `RUSAGE_CHILDREN` delta. The resident-byte time integral,
SSH server CPU, Runtime supervisor CPU and arbitrary un-waited descendants are
outside this receipt.

`classification: normal` records a zero-exit ready worker; `failed` preserves a
nonzero exit or qualification failure; `cancelled` means the wrapper observed an
external stop signal. The exact child return code and signals sent remain
separate, so a cancellation classification does not invent signal causality.
`unknown`, an incomplete receipt, or a missing terminal update remains unknown.
If the wrapper itself is SIGKILLed, its prior intent/ready receipt remains and
must not be converted into zero CPU or a successful terminal measurement.

On any lost acknowledgement, inspect the same original Runtime key/job. Do not
delete the receipt, change keys, or start another worker automatically. After
the original job reaches terminal state, retrieve the final helper receipt and
link its exact bytes to that Runtime terminal receipt and the deployment's
external unit evidence.

## Local verification

```text
python3 -B -m unittest discover -s qualification/cell-meta-network -p test_worker_lifecycle.py -v
```

The six local tests execute real owned children: normal exit, SIGTERM with
graceful child exit, ignored SIGTERM requiring SIGKILL, nonzero exit, exclusive
receipt replay refusal, and cancellation while the actual stdout pipe is full.
They check raw ready preservation, actual `wait4`/`RUSAGE_CHILDREN` accounting
and process inheritance. They do not claim real main/x230 systemd containment,
cross-host performance, or native-model correctness.
