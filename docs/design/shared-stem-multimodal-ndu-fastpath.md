# Shared Stem, Multimodal Cell Differentiation, NDU/System2, and FastPath

Status: research decision record, shadow-only.  
Date: 2026-10-17.  
Scope: large populations of Hepta Neuron Cells with a shared encoder/stem, lightweight per-cell heads, multimodal differentiation, bounded System2 utility search, and lower-latency computer-use dispatch.

## Decision

Invest in one shared, versioned Stem plus per-Cell adapters and heads. Do not replicate the 421M parameter model for every Cell.

The first Stem should be the existing 421M model's stable encoder path if it can expose a documented hidden-state ABI and pass the bakeoff below. A new compact multimodal Stem is a candidate replacement, not an assumption. Stem selection must be decided from measured task quality, out-of-distribution behavior, memory, p95/p99 latency, update stability, and calibration on the target hardware.

A Cell is a small, versioned specialization artifact:

- a routing/gating vector or low-rank adapter;
- a task or modality head;
- a bounded memory/query policy;
- a declared capability set;
- an exact Stem, runtime, policy, and snapshot binding.

A Cell never receives authority merely because it scores well. It produces a proposal and evidence; Guardian, TaskFlow, Agentd, and the owner state remain the authority path.

## Why the shared Stem dominates copies

Let (N) be the Cell count, (P) the Stem parameter count, (h) the hidden width of a Cell head, and (b) the bytes per parameter.

Replicated models require approximately:

[
M_{copies} = N(Pb + K)
]

where (K) includes runtime state, allocator slack, KV/cache state, and per-model metadata.

A shared design requires approximately:

[
M_{shared} = Pb + N(hb_h + A + K_{cell}) + K_{shared}
]

where (A) is the adapter/gate state. The savings grow with (N), but the real target is a measured resident set and tail-latency envelope on the production host. A 421M-parameter bf16 model is about 842 MB of weights before runtime overhead, so 1,000 independent copies are already roughly 842 GB of weights. This is an order-of-magnitude sizing estimate, not a capacity claim.

The shared Stem should be frozen or slow-moving. Frequent global updates invalidate every Cell's calibration and make receipt comparison difficult. Cell updates should be independently versioned, rollbackable, and evaluated against a fixed Stem snapshot.

## Stem selection

No universal Stem is optimal. Use a three-candidate bakeoff with the same Cell heads, training budget, datasets, and deployment limits:

| Candidate | Use when | Main risk |
| --- | --- | --- |
| Existing 421M encoder path | It exposes stable hidden states, good transfer, and acceptable tail latency | Hidden-state ABI may be task-specific or too expensive |
| Compact latent Transformer | A modality-agnostic token interface is required | Compression can discard fine-grained evidence |
| Transformer/SSM hybrid | Long streams and video/audio context dominate | More complex state, kernels, and debugging |

The candidate wins only if it satisfies all hard gates and is Pareto-efficient:

1. Hidden-state ABI is stable across a frozen test suite and supports deterministic digesting.
2. Text, image, video, and audio frontends can map into the same latent contract.
3. Cell heads do not need to grow with the number of modalities.
4. OOD and abstention behavior is calibrated; the Stem can say “insufficient evidence.”
5. p95/p99 latency, peak memory, energy, and throughput meet the target-host envelope.
6. Quantized and accelerated runtimes preserve the receipt contract.
7. A Stem update can be rolled back without silently changing Cell identity.

The bakeoff must hold the Cell side fixed. Otherwise a larger or better-trained head can hide a weak Stem. Store a transfer matrix with per-task accuracy, calibration, OOD AUROC or equivalent, memory, p50/p95/p99 latency, energy per request, and failure/abstention rates.

## Cell and gate contract

The Cell consumes the Stem latent sequence (Z), the request context (C), and a bounded memory view (R). It emits:

- a task distribution or proposal;
- an uncertainty interval;
- a resource estimate;
- an optional System2 request;
- an evidence digest.

A lightweight gate can be implemented as:

[
g_i = operatorname{softmax}(W_i operatorname{pool}(Z,C) + b_i)
]

with low-rank residuals:

[
H_i = H_0 + U_i V_i^	op
]

where (H_0) is shared and (U_i,V_i) are Cell-local. Use adapters, AdaLN-style modulation, or low-rank projections before considering a full per-Cell block.

Every Cell artifact binds to:

- Stem digest and hidden-state ABI;
- Cell/head/adapter digest;
- modality and task schema;
- runtime tuple and device class;
- policy and capability manifest;
- generation and snapshot;
- authorization version;
- training data/evaluation ledger.

An input, runtime, or Stem drift is a new evaluation request, not a cache hit. The owner-evidence contracts in `qualification/cell-fast-path-actionir-p0` through `p3` provide the shape for this shadow binding.

## Multimodal differentiation

Use a common latent interface, not one monolithic decoder.

```text
text tokens      image patches      video tubelets      audio codec frames
      \                |                  |                    /
       modality frontend + timestamp/space/type embeddings
                              |
                    canonical latent token envelope
                              |
                     shared Stem / latent trunk
                              |
                Cell gate + adapter + lightweight head
                  /            |             |           \
        text decoder    image decoder   video decoder   audio decoder
```

Each frontend maps its input to a canonical envelope containing:

- latent width and dtype;
- modality, sample rate or frame rate;
- temporal and spatial coordinates;
- mask and padding semantics;
- preprocessing and tokenizer/codec digests;
- source and input digests.

The Stem operates on the canonical sequence. The head predicts a task-specific representation or a decoder condition. Decoders remain modality-specialized:

- text: autoregressive token head with constrained decoding;
- image: diffusion or flow condition with a VAE/latent decoder;
- video: temporal denoising or token decoder with explicit frame state;
- audio: codec-token or spectrogram decoder followed by a bounded vocoder.

Generation should be staged. A Cell first produces a semantic plan and uncertainty, then requests a modality decoder. The decoder returns a receipt with output digest, resource observation, and quality checks. Cross-modal generation uses shared latent references and explicit alignment losses; it must not rely on an untyped “universal output” tensor.

Training should separate the concerns:

1. modality frontends learn reconstruction and alignment;
2. the Stem learns masked cross-modal prediction and contrastive alignment;
3. Cells learn task routing, low-rank specialization, and calibrated abstention;
4. decoders learn modality fidelity and safety constraints;
5. a held-out evaluation ledger tests transfer and composition.

A Cell split creates a new identity and requires replay-safe lineage. It does not mutate a parent's weights in place.

## NDU/System2 integration

Treat Neural Differential Utility as a bounded allocator and selector around the shared Stem, not as an unbounded online weight mutator.

For candidate (a), evaluate an interval-valued utility:

[
U(a) =
operatorname{LCB}[Delta task(a)]
-lambda , FLOPs(a)
-mu , latency(a)
-
u , memory(a)
-ho , risk(a)
-kappa , energy(a)
]

The lower confidence bound is deliberate: uncertain gains do not justify extra compute or authority. NDU may select among already-typed Cells, adapters, decoder settings, or System2 branches. It may request offline training or shadow evaluation. It must not change hard constraints, issue authority, claim physical effects, or write owner state.

Trigger System2 only for bounded reasons:

- novelty or OOD score above threshold;
- disagreement between Cells or modalities;
- high-stakes task class;
- low confidence interval;
- failed precondition or insufficient evidence;
- a measurable expected utility gain above a cost margin.

System2 receives hard budgets: maximum depth, branch count, tokens, wall time, memory, verifier steps, and energy. Its loop is:

1. deterministic feasibility filter;
2. generate a small candidate set from typed actions;
3. estimate utility and uncertainty;
4. prune by Pareto dominance;
5. verify preconditions, policy, and output schema;
6. execute only through the existing owner path;
7. record a receipt and update the ledger.

Splitting and differentiation alone do not guarantee reasoning. Emergent reasoning needs process supervision, outcome supervision, verifier feedback, durable memory, credit assignment across branches, calibration, and holdout tests that prevent a Cell population from merely memorizing the evaluator.

## FastPath computer use

A Cell should not write arbitrary binary bytes, pointers, PTX, or RWX memory for direct CPU/GPU execution. That design makes the model an authority and collapses provenance, revocation, and rollback.

The safe low-latency design is a typed ActionIR pipeline:

```text
Cell proposal
  -> ActionIR schema validation
  -> capability/policy/precondition checks
  -> signed artifact lookup
  -> fixed CPU/GPU dispatch table
  -> non-effect local execution or observation
  -> receipt projection
  -> Guardian / TaskFlow / Agentd owner path
```

CPU lane:

- signed AOT or WASM/WASI artifacts;
- W^X memory and fixed ABI;
- capability-scoped syscalls;
- bounded fuel, memory, and wall-clock;
- no raw pointer or syscall fields in model output.

GPU lane:

- precompiled kernels and shape-specialized dispatch;
- CUDA Graphs or equivalent captured graphs for repeated sequences;
- fixed tensor layouts and workspace limits;
- no model-supplied PTX or dynamic kernel compilation;
- explicit device, driver, and runtime digests.

A shared-memory ring, persistent worker, batched head, or captured graph can remove serialization and CPU launch overhead. It replaces a data-plane round trip; it does not replace Guardian, TaskFlow, Agentd, revocation, or the MCP control plane. MCP remains appropriate for discovery, capability negotiation, user consent, and cross-process interoperability. FastPath is an owner-approved execution optimization behind those boundaries.

The existing P0-P3 contracts intentionally stop before execution:

- P0 types and binds ActionIR candidates;
- P1 qualifies generation, preconditions, budgets, replay, and fallback;
- P2 projects Guardian/TaskFlow/Neuron evidence into owner evidence;
- P3 adapts a verified Rust Neuron receipt without reimplementing Rust hashing.

A later execution experiment may add a deterministic local non-effect lane. It must first prove artifact signatures, verifier coverage, resource bounds, revocation latency, and receipt completeness. Any effectful operation remains behind owner authorization.

## Split and differentiation lifecycle

Use immutable lineage:

```text
parent Cell
  -> propose split with reason and evaluation ledger
  -> freeze parent snapshot
  -> create child specs and data partitions
  -> train adapters/heads offline
  -> shadow evaluate against parent and sibling holdouts
  -> register child artifact and generation
  -> route by calibrated gate
  -> rollback by generation or revoke by digest
```

A split is accepted only when the child improves a declared slice without regressing global safety, calibration, resource, or abstention metrics. A gate that routes too aggressively is a regression even if mean task score rises.

Track these ledgers:

- parameter and optimizer bytes;
- resident and transient memory;
- p50/p95/p99 latency;
- queue age and batch utilization;
- energy per request;
- task quality and calibration;
- OOD/abstention;
- modality alignment;
- split lineage and rollback time;
- receipt completeness and verifier coverage.

## Phased implementation

### Phase A: existing Stem transfer

Expose and freeze the existing encoder hidden-state ABI. Add Cell adapter/head artifacts, exact runtime tuple binding, and the transfer matrix. Use the P0-P3 evidence shape for every shadow request.

Exit gate: fixed-Cell bakeoff plus target-host resource receipts.

### Phase B: canonical multimodal envelope

Implement text/image/video/audio frontends and a canonical latent token envelope. Start with one modality pair, then add temporal video and codec audio. Keep decoders separate.

Exit gate: cross-modal transfer, alignment, OOD, and p95/p99 budgets.

### Phase C: bounded NDU/System2

Add interval utility scoring, triggers, branch budgets, verifier steps, and ledger updates. Keep weight updates offline and shadowed.

Exit gate: System2 improves held-out tasks at a measured resource cost without authority leakage.

### Phase D: FastPath observation lane

Implement signed artifact lookup and a fixed non-effect CPU lane. Measure shared-memory and batching overhead against MCP transport. Add GPU captured graphs only after receipt and revocation tests pass.

Exit gate: lower p95/p99 latency with complete receipts, fail-closed behavior, and no effect claims.

### Phase E: owner-approved effects

Only after the prior gates pass should a narrow effectful capability be considered. It must be a predeclared operation with Guardian/TaskFlow/Agentd authorization, idempotency, revocation, and rollback. Raw model-generated machine code remains out of scope.

## References

- Hepta NDU boundaries: `docs/modules/utility.ndu/TECHNICAL.md`
- FastPath ActionIR qualification: `qualification/cell-fast-path-actionir-p0` through `qualification/cell-fast-path-actionir-p3`
- MCP specification: https://modelcontextprotocol.io/specification/2025-06-18
- LoRA: https://arxiv.org/abs/2106.09685
- Perceiver: https://arxiv.org/abs/2103.03206
- CUDA Graphs: https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#cuda-graphs
- WebAssembly security: https://webassembly.org/docs/security/
- Linux eBPF verifier model: https://www.kernel.org/doc/html/latest/bpf/verifier.html
