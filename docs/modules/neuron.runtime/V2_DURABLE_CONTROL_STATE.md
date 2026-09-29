# Neuron V2 durable Agentd control state

This document defines the crash-visible lifecycle and generation-topology record
used by `AgentdNeuronGenerationControllerV2`. It is a control-plane record only.
It contains no model output, no admission capability and no result-use grant. The
authoritative operation, failure, dispatch, checkpoint and witness histories
remain in the existing V2 runtime stores.

## 1. Scope and non-authority

The durable control state closes a daemon-level crash window that cannot be
closed by the generation store alone: a process can terminate after it has
quiesced a generation or begun a handoff but before its in-memory lifecycle enum
and owner topology are observable to the next process.

The state file records only:

- schema version;
- lifecycle (`Starting`, `Serving`, `Quiescing`, `Sealed`, `Reloading`, `Stopped`
  or `Failed`);
- active generation;
- sorted retained generations;
- the strictly newer reload target while and only while `Reloading`;
- a canonical digest over all preceding fields.

It does **not** authorize any of the following:

- provider execution;
- creation of an operation reservation;
- mutation of historical runtime stores;
- release of a committed result;
- model selection, promotion, activation or rollback.

The current-use guard and exact runtime histories remain authoritative for those
questions.

## 2. APIs

Use a durable path when constructing the product controller:

```rust
let controller = AgentdNeuronGenerationControllerV2::new_with_state_path(
    active_handle,
    control_state_path,
)?;
```

On restart, reopen the runtime stores first, reconstruct the exact active and
retained handles, then bind them to the same control-state path:

```rust
let controller =
    AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
        active_handle,
        sealed_historical_handles,
        control_state_path,
    )?;
```

Supporting inspection interfaces are:

- `AgentdNeuronGenerationControllerV2::generation_state()` — read-only
  projection of the current lifecycle/topology record;
- `read_agentd_neuron_generation_state_v2()` — validated file read;
- `write_agentd_neuron_generation_state_v2()` — validated atomic replacement;
- `AgentdNeuronControlStateErrorV2::stable_code()` —
  `control_state_invalid`, `control_state_corrupt` or `control_state_io`.

Controller construction preserves those three control-state codes through
`AgentdNeuronControlErrorV2::ControlState`. `controller_poisoned` is reserved for
an in-process poisoned controller lock or execution fence. This distinction tells
the host whether to repair a path/permission problem, retain corrupt bytes for
forensics, retry an I/O dependency, or reconstruct poisoned process ownership.
All cases still fail closed and grant no operation or result-use authority.

## 3. Publication and filesystem contract

Before taking ownership of caller handles, construction validates that the
control-state parent already exists, is a directory and is not a symlink. On
Unix the parent must also have no group or other permission bits. Construction
captures this validated parent identity before fencing caller handles, so a
missing, shared or invalid namespace fails without silently advancing the
caller's execution epoch.

Every publication:

1. validates the complete candidate state and private parent namespace;
2. serializes a bounded JSON object;
3. creates a new same-directory temporary file with exclusive creation;
4. writes and syncs the complete bytes, then verifies that the opened temporary
   descriptor and temporary path still identify the same regular private file;
5. replaces the final path in the same directory;
6. syncs the parent directory on platforms that expose directory sync;
7. opens the published file, validates its metadata and reads back the exact
   bytes before reporting success;
8. revalidates the parent and, on Unix, requires its device/inode identity to be
   unchanged across the publication.

The final file must be regular, bounded and non-empty. On Unix it must have link
count one and no group/other permission bits. Reads compare the validated parent
before and after the operation and compare the pre-open path metadata, opened
file metadata and post-read path metadata; device/inode changes fail closed.
Symlinks and hard links are rejected. A state digest mismatch is corruption, not
an absent state. Do not delete the file and silently start a new topology.

The state path belongs in a host-owned, owner-private namespace distinct from
untrusted model or request content. It may share a protected runtime directory,
but it must never be placed inside a path an unprivileged provider can read,
traverse or replace. On Unix, deployment must provision the immediate parent
with owner-only permissions before constructing the controller.

## 4. Transition ordering

The controller publishes transitions in a fail-closed order:

| Transition | Required ordering |
| --- | --- |
| `Starting -> Serving` | Reconcile retained and active histories; publish `Serving`; open only the active execution gate; expose in-memory `Serving`. |
| `Serving -> Quiescing` | Close and advance the execution epoch; publish `Quiescing`; expose in-memory `Quiescing`. |
| `Quiescing -> Sealed` | Obtain the exclusive drain proof; reconcile; prove no pending operation or witness; publish `Sealed`; expose in-memory `Sealed`. |
| `Sealed -> Reloading` | Close the successor gate; publish old active topology plus the successor target; expose `Reloading`. |
| `Reloading -> Serving` | Drain and reconcile the successor; publish the complete new topology; swap active/retained handles; open only the successor; expose `Serving`. |
| `Sealed -> Stopped` | Publish `Stopped`; expose in-memory `Stopped`. |

A control-state write failure never opens a gate. A gate failure after a
publication moves the current process to `Failed` and leaves restart recovery to
normalize and reconcile the persisted topology.

## 5. Restart resolution matrix

A fresh process always closes every supplied handle before enabling service.
The persisted record and the reconstructed handles must agree exactly.

| Persisted state | Supplied topology | Recovered lifecycle |
| --- | --- | --- |
| `Starting` | exact active and retained set | `Starting` |
| `Serving` | exact active and retained set | `Starting`; reconciliation is mandatory before reopening service |
| `Quiescing` | exact active and retained set | `Quiescing`; new work stays closed |
| `Sealed` | exact active and retained set | `Sealed` |
| `Stopped` | exact active and retained set | `Stopped` |
| `Failed` | exact active and retained set | `Failed` |
| `Reloading(A -> B)` | active `A`, original retained set | `Sealed`; the successor was not durably selected |
| `Reloading(A -> B)` | active `B`, original retained set plus `A` | `Starting`; the successor topology was completed and must be reconciled |
| `Reloading(A -> B)` | any other topology | `generation_conflict`; fail closed |

This matrix prevents an interrupted handoff from guessing which generation is
writable. It also prevents a caller from omitting retained history or presenting
a future generation as already selected.

## 6. Relationship to runtime storage

This feature deliberately leaves `HPTNGS02`, `HPTNGI02`, provider ledgers and
witness formats unchanged. In particular:

- full receipt-to-checkpoint payload identity is preserved;
- success, failure, dispatch and witness histories are not copied into the
  control-state file;
- the control state cannot repair or override a runtime-store conflict;
- retained generations remain queryable through their original stores;
- capacity is recovered by explicit generation handoff, never by deleting or
  reinterpreting old history.

Any future compaction or unified segment representation still requires a new
versioned manifest, migration, crash-cut tests and retained historical queries.

## 7. Incident procedure

When startup reports `control_state_invalid`, `control_state_corrupt`,
`control_state_io`, `controller_poisoned` or `generation_conflict`:

1. keep all generation execution gates closed;
2. retain the state file and runtime paths as incident evidence;
3. for `control_state_invalid`, verify the parent/file type, Unix parent and file
   permissions, link count, parent identity and opened-file identity before
   replacing anything;
4. for `control_state_corrupt`, retain the exact bytes and verify the canonical
   digest; do not rewrite the topology by hand;
5. for `control_state_io`, restore the required host-owned namespace or storage
   dependency and retry construction without inventing a new state;
6. for `controller_poisoned`, reconstruct process ownership from durable files
   rather than treating it as an operation retry;
7. enumerate the actual active and retained generation directories and provider
   ledgers;
8. reconstruct only a topology accepted by the restart matrix;
9. reconcile every retained generation, then the active generation;
10. reopen service only through `start()`.

Never edit `activeGeneration`, remove a retained generation or clear a reload
target manually to make startup succeed.

## 8. Qualification boundary

Repository regression tests cover state round-trip, digest tampering, every
published lifecycle transition, both accepted interrupted-reload topologies,
ambiguous-topology rejection, specific corrupt/I/O error propagation, parent
preflight before handle fencing, Unix non-private-parent rejection, and Unix
symlink/hard-link/private-file-mode rejection. These tests are source evidence
only until the exact-head qualification workflow completes.

Target-host qualification must still terminate the process at each publication
cut and exercise real filesystem sync failure, owner panic, namespace replacement
and concurrent in-flight invocation drain.
