# Proposal-only compiled computer-use Cell

`codex-hepta-compiled-use` is an experiment scaffold for the local hot path
described in Experiment 6. It defines a 256-byte, digest-bound ABI for five
typed actions:

* read the accessibility tree;
* click an element identified by a digest from an accessibility-tree read;
* type bounded UTF-8 text;
* scroll; and
* capture a bounded region.

`ActionVerifierV1` checks the generation, capability grant digest and action
mask before `SharedMemoryQueueV1` accepts a frame. The queue is bounded and
sequence-fenced. The current backing is process-owned `VecDeque` storage with
the same fixed-frame contract; an OS shared-memory adapter can be added later
behind the ABI without putting unsafe code or pointers in this crate.

`propose_compiled_use_v1` packages a verified, consecutively numbered action
list into a deny-all `CompiledUseProposalV1`; `verify_compiled_use_proposal_v1`
rebuilds its digest before it can be handed to an independent sandbox owner.

There is no machine-code field, executable-memory writer, dynamic loader or
OS effect. `DenyByDefaultSandboxV1` always rejects submission. A real product
caller must first obtain `VerifiedActionV1` from the verifier, then supply an
independently reviewed sandbox implementation of `SandboxActionPortV1`, bind
it to the existing authority/capability plane and retain rollback/audit
evidence.

Run the safe smoke runner with:

```text
cargo run -p codex-hepta-compiled-use --example compiled_use_runner
```

## Atomic local batch pilot (2026-10-15)

`SharedMemoryQueueV1::push_batch` now validates a bounded contiguous group
before any queue mutation. It rejects a late wrong capability, stale generation,
bad sequence, out-of-capacity batch, empty group or 64-bit sequence overflow
without consuming the queue sequence or partially appending an action. The
scalar `push` path shares exactly this code path. `ActionVerifierV1::verify`
no longer constructs an unused owned action clone.

`cargo test --locked -p codex-hepta-compiled-use` exercises atomicity and
fixed-wire equality. `cargo run -p codex-hepta-compiled-use --example
atomic_batch_bench -- --smoke` runs an actual Rust CPU microbenchmark and
reports local p50/p95/p99 enqueue+dequeue latency over preconstructed,
digest-bound 256-byte action frames. This is NOT a model-to-tool RPC benchmark,
browser completion time, GPU launch, OS action execution or measured production
p99. It is explicitly a source-only native transport pilot.

The original smoke example now uses only defined capability bits instead of
`u16::MAX`, which the contract correctly rejects as malformed.

**DRAFT / SHADOW_ONLY / DENY_ALL.** These changes deliberately add no machine
code, raw pointers, executable memory writer, JIT compilation, OS syscall,
GPU device authority or grant issuer. A separately reviewed original sandbox
and FinalUse/Control/CNS owner must provide effect authorization before any
native Computer Use action can actually execute.
