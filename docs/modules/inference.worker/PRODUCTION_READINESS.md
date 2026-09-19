# inference.worker production readiness and runbook

This document is the short operational companion to [TECHNICAL.md](TECHNICAL.md).
It describes the repository-controlled source path that exists today and the
evidence still required before production activation. It is not an activation,
hardware qualification, independent-acceptance or release receipt.

## 1. Executable source surfaces

Hosted provider execution:

- `codex-rs/hepta-infer-worker-host/src/native_run_control.rs` owns worker-side
  admission/recovery sequencing.
- `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` owns the exact
  Agent/App Server client, provider observations and Core reconciliation.
- `codex-rs/hepta-infer-core/src/native_control.rs` remains the single durable
  inference-control journal for reservation, dispatch identity, cancellation,
  recovered admission and settlement.
- `codex-rs/hepta-inferd/src/worker_port.rs` is the typed
  `inference.control -> inference.worker` source-composition seam. It does not
  mint authority; the provider path requires a kernel-owned
  `FinalUseAuthority` and independently signed `SignedFinalUseGrant`.
- `codex-rs/hepta-inferd/src/bin/hepta-inference-runtime-host.rs` is the named
  hosted-provider source composition root. It binds protected host
  configuration, the canonical durable inference-control owner, final-use
  trust/revocation state and `NativeWorkerPort`. This is source composition,
  not evidence that a production deployment exists.

Local model execution:

- `model_worker.rs` validates the model/request/grant/resource lifecycle.
- `local_process_driver.rs` is the concrete local runtime-process driver.
  It verifies the selected runtime executable, weights, tokenizer,
  preprocessor, quantization metadata and device descriptor by SHA-256; requires
  a completed memory-reservation/load handshake; sends the exact lease-bound
  input; and performs bounded unload/kill cleanup. Each load receives only the
  worker grant's remaining unreserved memory, and aggregate live model
  reservations may not exceed the worker grant.
- A named local-model product caller is still absent. The local source path is
  therefore not a deployed/product-composed resource-authority boundary yet.

The `hepta-infer-worker --profile native-app-server` CLI remains an explicit
operator/qualification surface. Possessing CLI access is not production
provider-dispatch authority.

## 2. Authority and grant boundaries

There are two different authority objects and they must not be conflated.

1. Provider dispatch uses kernel `FinalUseAuthority`. The issuer signs the
   exact subject, destination, request, scope and canonical payload binding.
   `run_authorized` claims that grant only for a fresh Reserved request and
   immediately enters the durable dispatch-intent boundary. Planning in
   `hepta-inferd::plan` remains `DENY_ALL`.
2. Local resource admission uses `VerifiedResourceGrant`. A raw
   `ResourceGrant` is data, not proof of authenticity. External callers must
   pass it through a trusted `ResourceGrantVerifier` that returns an
   authenticated authority identity and evidence digest. The
   `TrustedInProcess` constructor is crate-private and only covers an
   explicitly shared trusted process boundary. `VerifiedResourceGrant` is a
   verification snapshot, not a live revocation subscription: a production
   local-model caller must check current authority epoch/revocation before
   constructing a worker generation and must fence/replace that generation when
   its resource authority is withdrawn. Reusing the snapshot across an authority
   change is not a supported trust model.

Neither path grants fleet mutation, grant issuance, model installation or
permission to widen another module's authority.

## 3. Isolation guarantees

Repository source currently enforces:

- exact Agent identity and generation fencing for hosted App Server execution;
- exact App Server home and selected model checks;
- read-only App Server sandbox policy and no worker-issued approval/tool grant;
- stable request/client-message/payload/turn binding and no blind provider replay;
- digest-pinned local runtime and model artifacts;
- one local runtime child per loaded handle, bounded protocol lines and output;
- per-load remaining-memory admission plus aggregate live reservation checks
  against the worker grant, followed by observed-memory checks;
- request concurrency/token/deadline validation in `InferenceWorker`;
- bounded local protocol response waits; a run wait is additionally capped by
  the exact request deadline and becomes indeterminate rather than replayable
  after an unknown post-write timeout;
- forced child kill/wait when local runtime cleanup becomes uncertain.

These are execution ownership, identity and resource-contract guarantees. They
are **not** proof of a host security sandbox.

## 4. Isolation non-guarantees and launcher obligations

The worker source does not itself establish or attest all of the following:

- cgroup v2 memory/CPU enforcement;
- Linux namespaces or container/VM isolation;
- seccomp/LSM policy;
- GPU device ACL/IOMMU/MIG partition enforcement;
- pinned-mount or immutable-filesystem ancestry for model artifacts;
- physical accelerator memory correctness, reset behavior or leak freedom;
- remote authenticated transport for a separately deployed worker.

The selected launcher/device authority must establish those controls where
required and the deployment evidence must name the exact host, runtime binary,
model artifacts, device, policy and generation. A digest-pinned device
descriptor is evidence input; it is not proof that the OS enforced the
descriptor.

## 5. Provider crash/restart reconciliation

Hosted provider requests use a persistent single-use App Server thread. Before
`turn/start`, inference.control synchronously records the thread/provider,
stable `client_user_message_id == request_id`, canonical input SHA-256 and
context digest.

If `turn/start` acknowledgement or the worker is lost, restart performs
`thread/queue/reconcile` in `ReconcileOnly` mode using the same thread,
client message ID, input and payload digest:

- `Persisted { turn_id }`: bind only that original turn, read persisted turn
  history, and refine terminal/output observations. `thread/resume` also
  replays persisted token usage to the recovery connection; the worker waits
  under the normal RPC bound for a matching exact-turn usage replay rather than
  relying on a fixed scheduling window.
- `Missing` or `Cancelled`: durably record no-admission proof and release the
  local slot. Re-execution requires a new request identity and new authority.
- `Queued`: reject as an unexpected state for the direct-turn path.
- unavailable/ambiguous reconciliation: retain `Indeterminate`; never submit a
  replacement turn.

Missing token usage stays unknown (`None`). A recovered terminal status does
not authorize inventing zero usage.

## 6. Local runtime protocol and startup

The selected runtime executable must implement
`hepta.local-model-driver.v1` on stdin/stdout when launched with
`--hepta-local-model-worker-v1`.

Before load:

1. select an exact `ModelManifest` and authenticated resource grant;
2. configure absolute local paths for runtime, weights, tokenizer,
   preprocessor, quantization descriptor and device descriptor;
3. verify every digest and reject symlink/non-regular terminal files;
4. start the exact runtime process;
5. compute already-reserved live model memory and send the model tuple plus only
   the remaining permitted worker memory; the runtime cannot legitimately
   reserve against the grant's full budget for every model independently;
6. require an echoed model/runtime/device identity and nonzero
   `reserved_memory_bytes <= remaining_memory_bytes`;
7. require `observed_memory_bytes <= reserved_memory_bytes`;
8. re-hash runtime/artifacts after the load handshake before publishing the
   handle.

Run requests contain the exact input whose SHA-256 equals both request and lease
payload digests. Local protocol responses use a bounded wait; for `run`, that
wait is the smaller of the configured runtime-response ceiling and the request's
remaining deadline. Unknown runtime outcome is nonterminal with unknown usage
and is never an automatic replay signal.

## 7. Shutdown, rollback and leak handling

Stop new admission first. Reconcile hosted requests with possible dispatch
before releasing slots. Drain local active requests before unload. A successful
local unload requires the exact handle acknowledgement and process exit inside
the bounded shutdown deadline; otherwise the child is killed and waited.

Rollback selects a previously qualified compatible runtime/model tuple under a
new process generation. Never mix a new runtime with old unverified model
artifacts or carry a stale resource/final-use grant across the generation.

## 8. Current source bounds

Important hard bounds in source include:

- hosted prompt: 32 KiB;
- hosted output: 1 MiB;
- hosted attached model context: 8 KiB;
- App Server RPC timeout: 5 seconds;
- local model input: 1 MiB;
- local runtime protocol line: configurable, default 2 MiB, hard maximum 8 MiB;
- local runtime response wait: default 30 seconds, hard configuration maximum
  300 seconds; `run` is further capped by its request deadline;
- local runtime output: 1 MiB;
- loaded models: 8;
- active local requests: 256;
- local token bound: 1,000,000.

Deployment SLOs such as p99 latency, tokens/second, peak RSS/VRAM, leak budget
and restart recovery time require measurements on the selected model/runtime
and hardware. Source constants are not SLO evidence.

## 9. Required qualification matrix

Do not claim production local inference until the exact candidate has evidence
for, at minimum:

| Case | Required observation |
| --- | --- |
| real CPU load/run/unload | exact binary/artifact/device digests; real terminal output/usage |
| real GPU load/run/unload | exact accelerator identity plus enforced device/memory allocation |
| OOM during load | no published handle and no leaked child/device allocation |
| OOM during run | bounded failed/indeterminate outcome; no fabricated usage |
| concurrency saturation | deterministic rejection at configured grant/bound |
| repeated load/unload | stable RSS/VRAM/FD baseline within declared leak budget |
| cancellation during run | durable cancel intent; observed runtime/provider terminality |
| worker kill before provider admission | exact reconciliation proves Missing/Cancelled |
| worker kill after provider admission | same turn recovered; no replacement dispatch |
| App Server restart/transport loss | original client ID/payload reconciled or remains indeterminate |
| local runtime crash | nonterminal/indeterminate unless a trusted runtime receipt proves terminality |
| authority revocation race | no post-revocation fresh dispatch admission |
| artifact mutation | digest mismatch before usable handle |
| device reset | current handle fenced; no stale success |
| rollback | predecessor tuple starts in a new generation with current authority |

Use a real selected model and actual target device for hardware cases. The
Python subprocess fixture in the crate proves protocol integration only.

## 10. Activation checklist

A production activation candidate is ready for independent review only when all
of these are true:

- exact source commit/tree and synthetic merge candidate are recorded;
- package tests, all-target build and strict Clippy pass on that exact candidate;
- the named deployed hosted-provider product caller reaches
  `NativeWorkerPort::execute`, and any selected local-model profile has a
  separately authenticated local product caller;
- protected signer trust/revocation state is configured outside the worker;
- economic quota and hardware-capacity authority are composed;
- real model/runtime/device qualification above is attached;
- OS isolation controls required by the deployment are identified and measured;
- provider crash/restart and late/missing-usage cases have target-host evidence;
- rollback predecessor identity and procedure are exercised;
- independent acceptance is issued by the designated external actor.

Until those gates are satisfied, keep `productionImplementation`,
`productExecutionComplete`, `deploymentQualificationComplete`,
`activation` and `release` false.

## 11. Verification commands

From `codex-rs`:

```text
just test -p codex-hepta-infer-core
just test -p codex-hepta-infer-worker-host
just test -p codex-hepta-inferd
cargo check -p codex-hepta-infer-core -p codex-hepta-infer-worker-host -p codex-hepta-inferd --all-targets
cargo clippy -p codex-hepta-infer-core -p codex-hepta-infer-worker-host -p codex-hepta-inferd --all-targets --no-deps -- -D warnings
```

These are invocations, not pass receipts. Exact-head CI and merge-candidate
qualification remain the evidence source.
