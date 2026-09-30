# neuron.runtime readiness dashboard

Generated from `docs/modules/neuron.runtime/MODULE_SPEC.json`. Runtime evidence is emitted by `.github/workflows/neuron-runtime-readiness.yml`.

**Production activation: false.** Passing source qualification is necessary but does not authorize product activation or release.

| Gate | Runner | Platform | Toolchain | Candidate |
|---|---|---|---|---|
| `linux-stable-source-head` | `ubuntu-24.04` | `linux-x86_64` | `stable` | `source-head` |
| `linux-stable-synthetic-merge` | `ubuntu-24.04` | `linux-x86_64` | `stable` | `synthetic-merge` |
| `linux-msrv-source-head` | `ubuntu-24.04` | `linux-x86_64` | `msrv` | `source-head` |
| `linux-msrv-synthetic-merge` | `ubuntu-24.04` | `linux-x86_64` | `msrv` | `synthetic-merge` |
| `linux-arm64-source-head` | `ubuntu-24.04-arm` | `linux-arm64` | `stable` | `source-head` |
| `linux-arm64-synthetic-merge` | `ubuntu-24.04-arm` | `linux-arm64` | `stable` | `synthetic-merge` |
| `macos-arm64-source-head` | `macos-15` | `macos-arm64` | `stable` | `source-head` |
| `macos-arm64-synthetic-merge` | `macos-15` | `macos-arm64` | `stable` | `synthetic-merge` |

Every gate emits a provenance record binding the exact source and tested tree to the workflow run, target triple, runner fingerprint, test-set hash, `Cargo.lock`, documentation and generated implementation map.

The aggregate `READINESS_MANIFEST.json` is an immutable workflow artifact. It rejects mixed SHAs, mixed integration bases, stale generated projections, missing target evidence and failed gates. Provenance v2 checks exact Git objects, actual compiler/target, one workflow run/attempt and every required stage. Metadata consistency is not remote attestation: the workflow must also require all matrix jobs, download and aggregation to succeed.

## Performance policy

Concurrency levels: 1, 8, 32, 128, 256.

No lock-topology refactor is authorized without retained p95/p99 evidence of head-of-line blocking.
