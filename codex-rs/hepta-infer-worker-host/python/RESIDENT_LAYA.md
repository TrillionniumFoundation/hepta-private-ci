# Resident pinned Laya transport

## Scope and owners

`laya_resident.py` extends the existing local semantic predictor with a bounded
resident child. It reuses `BinaryRetrievalDriver`, `OwnerDeadline`, the pinned
checkpoint loader, the HPTARQ/HPTARS V1 codec and the existing POSIX/Darwin
owned-child cleanup protocol. It creates no admission authority, durable journal,
model selector, training service, Neuron owner or new product execution spine.

This is an experimental process component, **not the completed Agentd -> Neuron
-> inference-owner -> protected-consumer composition**. The existing native
owner must reserve capacity before loading, fence dispatch durably, persist the
full result, recheck current sources and the selected artifact at delivery, and
obtain the destination acknowledgment. A Python reply is not that acknowledgment.
The semantic source distribution must not be silently reinterpreted as an
arbitrary numeric Neuron feature profile.

## Protocol and lifecycle

The outer transport frame is a four-byte unsigned big-endian length followed by
unchanged HPTARQ/HPTARS V1 data bytes. Frames are bounded to 65,536 payload bytes.
The child loads the checked bundle once, then handles sequential requests using
the same predictor. There is no request batch, implicit queue or auto-restart.

A session binds workspace, generation and bundle. Each request retains its own
operation, objective, observation, source revisions and absolute deadline. An
operation ID is used at most once in a session, even if the new bytes match.
Historical-result replay belongs to the durable inference owner, not this leaf.
Source ordering, probability conversion and observed SDK usage are unchanged.

Admission binds the current request deadline and clears the previous reply hash.
A later failed exchange never inherits the previous successful reply identity;
pipe byte observations include ineligible output. A completely decoded reply
hash remains current-exchange evidence if cancellation arrives during hashing,
but `eligible_reply` remains false and no reply is returned. Previously returned
observations remain unchanged. Rejection before admission
(such as a duplicate operation) does not overwrite that historical observation.

Session limits are 1..64 operations and at most 300 seconds. They bound the
in-memory operation set and the child's idle read loop as well as active calls.
Each prediction keeps its original owner deadline across cold loading. The
supervisor bounds pipe waits, captures only bounded diagnostic counts/digests,
and terminates a child blocked inside model computation or output on cancellation
or deadline. Normal per-cell cancellation must not be confused with permission
to free a shared model lease used by other consumers.

The public constructor accepts owner-selected canonical checkpoint/pin paths and
an absolute interpreter path; it does not accept commands from model output.
Use `ResidentLaya` as a context manager or explicitly call `close()`. Concurrent
use rejects instead of allocating waiting tasks. Pre-dispatch malformed,
expired, duplicate or wrong-generation requests do not write a new frame.
The supervisor rechecks cancellation and both original request/session deadlines
before process creation, after readiness waits, before each actual pipe I/O, and
after reply hashing and at delivery. Readiness is not permission to dispatch after cancellation.
A zero-byte failure still fences this handle conservatively; it is not authority
to replay an operation or release an inference-owner reservation.

After partial dispatch, malformed/late output, cancellation or a broken pipe,
the handle fences permanently: no subsequent inference, result substitution or
new process is permitted. `ProcessFailure` retains an unreaped child if cleanup
fails. `close()` reconciles only cleanup and raises while ownership remains
unresolved. The existing exclusive-reaper protocol must not be bypassed by an
external `poll()`/`wait()` or numeric-PID signal.

A completed reply does not unload the resident model. `direct_child_reaped`
only describes the leader; process groups do not prove escaped-descendant
containment, device-memory release, a hard resident-memory limit, source
currentness or task success. `model_reservation_released` stays false even after
local close. The authoritative owner must settle those obligations independently.
Parent death is not a crash-durable cleanup ledger; cross-process resource
reconciliation and kernel isolation remain required native integration work.

## Execution and evidence

Run all existing worker contracts plus the resident regressions:

```sh
python3 -m unittest discover -v \
  -s codex-rs/hepta-infer-worker-host/python -p 'test_*.py'
```

The new tests exercise one-load reuse, exact wire binding, generation/operation
rejection, partial frames/writes, zero progress, explicit overload, deadline and
cancellation, real child cleanup, retained signal failure, last-check cancellation,
idle lifetime expiry, cancellation/expiry after readiness but before the first
write, pre-spawn cancellation, and per-exchange failure identity. Unit predictors are deliberately synthetic; actual
child processes do not turn them into real-weight or product-acceptance evidence.

The existing `hepta-laya-smoke.yml` runs the resident smoke after its pinned
preparation, separately for exact source and fixed-base merge on Linux/macOS:

```sh
python3 codex-rs/hepta-infer-worker-host/python/laya_resident_smoke.py \
  --prepared "$RUNNER_TEMP/laya-smoke"
```

`resident-report.json` binds source SHA, tested SHA/tree, selected bundle, two
distinct request/reply hashes, actual SDK token usage, a reused live process ID
and the explicit close observation. Partial reports survive execution/cleanup
failure. A same-PID pair is process-reuse evidence, not an independent model-load
counter, task efficacy, native owner/Neuron consumer integration or learning gain.
Only the current workflow's actual result can establish this real-model smoke;
old runs, generated test source and queued jobs cannot substitute for it.

The smoke requests are synthetic read-only qualification tasks. No training-data
rights, future-time benefit, independent acceptance, model adoption, Browser
execution or structural migration is asserted. Those remain separate acceptance
obligations under the existing A-E sequence.
