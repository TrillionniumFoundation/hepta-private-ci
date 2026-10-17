# Worker → Agentd: pinned Cargo dependency baseline

## Identity and evidence

- Repository: `TrillionniumFoundation/hepta-private-ci`
- Baseline head: `bb63cd8cac3d3e4a813e015c6df376f73145563b`
- P0 execution-port source when the baseline was measured: `a70185c3ab49469baf52176dadc76fc0fec73ea8`
- Cargo.lock SHA-256: `8354b4cbdf14389db7aa5508e2ed5b524fc2d4c4ea0ecb475955c933f8bea389`
- Runner: `ubuntu-24.04`, requested target `x86_64-unknown-linux-gnu`
- Data: [successful read-only GitHub Actions run #39034190112](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39034190112), artifact `worker-dependency-footprint-39034190112` (GitHub artifact ID `12102209429`), generated `worker-footprint.json`
- Analyzer: `scripts/hepta_worker_dependency_footprint.py`, four tests passed. The historical CI printed a warning that `toolchain` was not a supported input of the SHA-pinned Rust setup action. The workflow is subsequently adjusted to install, select and **assert** Rust 1.95.0 explicitly; this original baseline is not retrospectively claimed to have proven that exact compiler version.

## Observed static Cargo resolution

| Packages (normal/build dependency edges, no dev-only edges) | Current Worker | Omit only Worker → Agentd | Attributable to direct Agentd edge |
|---|---:|---:|---:|
| Total resolved packages | 1,067 | 1,049 | **18** |
| Workspace packages | 146 | 128 | **18** |
| External packages | 921 | 921 | **0** |

The resolver closes over the **existing Cargo workspace feature resolution**, not an isolated alternative workspace with re-resolved features. The omission is a single graph-edge counterfactual, not a compilation or proposed patch to the production Worker. The entire omitted-edge-only set comprises these 18 workspace crates:

- `codex-hepta-agent-protocol`
- `codex-hepta-agentd`
- `codex-hepta-automation`
- `codex-hepta-bellman-operator`
- `codex-hepta-cognitive-store`
- `codex-hepta-context-compiler`
- `codex-hepta-control-plane`
- `codex-hepta-fleet`
- `codex-hepta-intelligence`
- `codex-hepta-intelligence-eval`
- `codex-hepta-intuition`
- `codex-hepta-learning-artifacts`
- `codex-hepta-learning-ledger`
- `codex-hepta-ndu`
- `codex-hepta-neuron`
- `codex-hepta-objective`
- `codex-hepta-plasticity`
- `codex-hepta-prompt-optimizer`

## Engineering decision and strict exclusions

The package graph **does not support an assertion that moving Agentd behind a new client will remove third-party crates**: in this observed resolver graph, no external package becomes unreachable. It may still meaningfully change binary size, link time, object code, RSS, startup costs or isolation, but those quantities are entirely **unmeasured**. Adding a new client crate or re-resolving Cargo features may also change the graph. Do not translate the 18 package edge delta into a percentage of physical memory or inference compute.

Do **not** add one network hop or one process per Neuron Cell to accomplish a dependency cleanup. Preserve the sole Agentd control/Final-use/effect owner, UDS request/reply schema, exact agent ID, generation, request ID, bounded frames and timeouts. Canonical source authority, durable dispatch journal, nonce consumption, reconciliation, and source/no-change baselines stay under existing owners.

The next authorized validation increment, after P0 CI actually passes, is a separately reviewed minimal-client build with a frozen `cargo metadata` and real before/after build/link duration, stripped executable bytes, max RSS, CPU utilization, UDS RPC count/bytes, p95/p99, offline/restart behavior and final-use/tombstone refusal. Measure actual scale at 64/256/1,024/4,096 Cells on the target host before any claim of practical savings or physical split.

This is **read-only P1 preparation**, not Final-use, target-host, future-window NDU or release approval. Both related PRs remain Draft and `DENY_ALL`.
