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

## UI observation-guarded shadow plan (V2 research branch)

`ui_guard.rs` extends the existing fixed-frame proposal with a bounded
exact UI readback requirement. `UiReadbackV1` binds principal scope,
external observer identity claim, actual tree digest claim, exact generation,
observed-at time and a maximum age of 5000 ms. A guarded proposal is accepted
only when the separately supplied observation matches **all** bound fields,
has not been observed in the future, and has not expired. Every proposed
action is checked by the existing five-opcode capability/sequence/data verifier.

`UiGuardedShadowProposalV1` binds the original proposal digest and complete
readback state under a domain-separated digest. Re-verification independently
reconstructs action and readback digests. The seven source-fixture Rust tests
cover cross-principal/tree observation drift, stale/future observations,
generation/TTL limits, missing identity, bad sequence/capability, tampered
action output and mutated guard/observer.

**There is NO actual observer authenticity, model execution, JIT compiler,
GPU program, OS UI action, authorization issuer or benchmark of real Computer
Use latency.** Both `observed` and `now_ms` remain supplied by the
caller, so even a perfectly valid digest can represent fabricated observations.
Any future live adapter must authenticate the readback owner, revalidate
current UI state and consume the existing short-lived FinalUse/effect token at
the last irreversible boundary. The original `DenyByDefaultSandboxV1`
still rejects execution. Research source-only tests are not production
qualification; leave **DRAFT / SHADOW_ONLY / DENY_ALL**.

Run targeted unit, lint and format on a native Rust-enabled host:

`cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use`

`cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --all-targets -- -D warnings`

`cargo fmt --manifest-path codex-rs/hepta-compiled-use/Cargo.toml -- --check`

## Actual Unix socket-pair fixed-frame pilot (V3, data only)

`FrameDuplexV1` sends and receives the existing canonical 256-byte ActionFrame
over a generic safe Rust `Read + Write` byte transport, with independent
monotonic send/receive sequences, bounded session length (up to 4096),
generation and capability revalidation, and fail-closed poisoning after
malformed inbound bytes or partial I/O failures. `receive()` only binds data;
it does **not** grant permission to execute actions.

The companion `unix_duplex_bench` uses an actual `UnixStream::pair` with
**two threads inside the same process**. Each original 256-byte action is
echoed as a verified 256-byte response through OS socket syscalls. It
reports descriptive p50/p95/p99 round-trip latency on an exact runner. It
does not compare against MCP, span separate processes, run a model,
invoke any OS UI effect, create machine code or execute a GPU Kernel.

Run on a Unix Rust host:

```text
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --all-targets -- -D warnings
cargo fmt --manifest-path codex-rs/hepta-compiled-use/Cargo.toml -- --check
cargo run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --example unix_duplex_bench -- --smoke
```

The readback owner, peer authentication, OS call deadlines, revocation and
`VerifiedUseToken` must be integrated by independent authority owners before
a live effect is possible. `DenyByDefaultSandboxV1` is unchanged.
**DRAFT / SHADOW_ONLY / DENY_ALL.** Synthetic fixtures and a kernel socket
microbenchmark do not establish production Computer Use gains.

## Separate-process Unix Socket pilot (V4 research)

The `two_process_unix_bench` example extends V3's real kernel
`UnixStream::pair` two-thread measurement to **two distinct Unix processes**
connected through an exclusive private (0700) Unix-socket directory. The
source process spawns an unprivileged child copy of the same executable.
Both sides independently decode and validate the original 256-byte
`ActionFrameV1`, sequence, generation and capability *data*; the child only
echoes exact frames. No user-interface access or native generated code occurs.

The parent bounds connection establishment and socket read/write periods,
records child setup and individual real 256B request/256B reply p50/p95/p99,
checks byte-for-byte response equality, verifies the child exit code, and
reaps the child even after a failed experiment. Its evidence reports
`separate_processes=true`, `peer_authentication_verified=false`,
`mcp_comparison=false`, `external_effects=false`, and
`production_authorized=false`. The enclosing source-digest and capability
checks DO NOT authenticate the actual OS peer. This is a limited transport
measurement, **not** a tool-call replacement performance claim or a
production-ready effect boundary.

To reproduce on an authorized Unix Rust test host:

```text
cargo run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --example two_process_unix_bench -- --smoke
```

The new read-only exact-head workflow also runs package unit tests,
Clippy and rustfmt and compares bounded JSON evidence to the required
non-authorizing schema. No model, API, credential, OS UI port, JIT or GPU
access is wired. `DenyByDefaultSandboxV1` is unchanged.


### Two-mode exact-source RTT receipt (V4.1)

The exact-head, source-only CI now performs two **separate original OS
two-process** RTT runs using the same native executable:

- A 64-roundtrip smoke profile to detect obvious transport/worker failure.
- A 1024-roundtrip bounded profile to observe a larger latency distribution.

The CI publishes a source-bound JSON envelope containing the actual Git HEAD,
SHA256 of the benchmark Rust source and SHA256 of both original raw JSON
results, plus the measured p50/p95/p99, process setup time and 256-byte
per-direction payload counts. It refuses extra or missing output fields and
keeps all effect/peer-authentication/model-vs-MCP/production flags false.

An immutable Git SHA and a file digest establish *source consistency*, not
trustworthy host attestation, statistical confidence in p99, API or MCP
equivalence, GPU inference, model-generation time, or real OS/UI completion.
Do not combine the two modes as independent task cases or claim a speedup
over remote tools without paired end-to-end work under an equivalent
environment. The latest exact-HEAD Action must finish before either receipt
is treated as measured evidence.


## V5 paired binary vs canonical JSON-hex control

This research-only extension quantifies one narrow hypothesis: how much of a
local, two-process verified-action RTT comes from canonical JSON text
framing versus the same underlying typed 256-byte binary ActionFrame.

The `paired_binary_json_control` example runs two subprocess
arms **with the same action bytes, verifier digest, generation, sequence,
one private 0700 Unix Socket directory and the same kernel process boundary**:

- `binary`: the existing SHA/digest-verified 256-byte transport.
- `json_hex`: strictly canonical, 4-byte-length-prefixed JSON with
  the exact same 256-byte action represented as lowercase hex; it parses
  exactly the registered schema and rechecks the same original ABI/digest,
  capability, generation and contiguous sequence. No general JSON parser
  or external tool-call system is exercised.

Each arm warms up 16 real request/response pairs before 64 or 1,024
measured pairs, with two repetitions and reversed execution order
(binary, JSON, JSON, binary). Each repetition separately records process
startup/accept cost and p50/p95/p99 RTT. The exact-head GitHub Action
runs the same protocol on x64 and ARM64 **as two separate host studies**:
its files are labeled by architecture, and no cross-architecture RTT
ratio is admissible.

The goal is an *internally matched encoding-control study*, **NOT an MCP
comparison**. JSON-hex represents a byte frame as text; it is not a
complete tool schema, MCP server, network RPC, LLM inference, OS computer
use, user-permitted effect, compiled JIT, native machine-code generation or
GPU kernel. Even if one encoding is faster, no claim about a real
end-to-end Computer Use speedup is supported without paired actual UI
tasks and full capture/model/effect/feedback costs.

The new 5 native source-level negative tests reject changed grants,
wrong sequence, oversized/noncanonical JSON and undeclared modes.
The read-only CI requires original native crate tests, strict Clippy,
rustfmt, a 64-case smoke and 1,024-case actual two-process workload
on each runner class. Raw results are sealed by exact source SHA and
actual Git HEAD, and the receipt retains false authority and false
MCP-comparison indicators.

No production compiler, effect port or capability owner is altered.
**DRAFT / SHADOW_ONLY / DENY_ALL / NO MAIN MERGE / NO FINALUSE.**
