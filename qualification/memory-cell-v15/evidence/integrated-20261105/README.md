# Integrated reference qualification, 2026-11-05

This record covers the exact modified reference implementation, not production
activation, language-model efficacy or a new cross-device model experiment.

## Executed result

| Check | Actual outcome |
|---|---|
| Current Python normal mode | 150 / 150, exit 0 |
| Current Python optimized mode (`-O`) | 150 / 150, exit 0 |
| Historical source/receipt rebinding controls | 9 / 9, exit 0 |
| Offline historical signed-object verification | 16 distinct signed objects, exit 0 |
| Current source unchanged during execution | true |
| Original historical `checks.json` / `checks.log` restored byte-for-byte | true |
| New model runs / independent language samples | 0 / 0 |

The run began at 16:25:10 UTC and completed at 16:27:35 UTC. `run.json` preserves
commands, exit codes, timestamps and 31 source digests. `normal-checks.json` and
`optimized-checks.json` preserve actual test IDs, source inventory, Python,
cryptography, cloudpickle and SQLite versions plus narrowly scoped process costs.
The native sources are inventoried, not compiled by this local capture. Native
execution is recorded separately in the identifier increment.

`capture.py` repeats the four steps with existing dependencies and a new output
directory, preserving previous `checks.*` in a `finally` block. The raw logs and
check receipts are retained without relabelling old device runs as current code.
The 150-case execution includes the existing 93, 7 identifier controls, 20 durable
ledger controls, 19 routing diagnostics controls and 11 typed-output controls.

## Independent observations and limits

- `historical-typed-audit.json` binds four original V14 blobs and the standalone
  read-only audit script. On 4,032 recorded single outputs and 504 compositions,
  strict JSON comparison changes zero historical scores. No model or executor ran.
- `native-composition-audit.json` identifies six existing native source files at
  `f88b826d3c22b5f89fd350dab4813be2855a2f93`. Native runtime, source revalidation,
  explicit configuration and external frontier interfaces already exist. Their
  presence does not qualify the V15 production composition or a deployed frontier.
- [Typed-output red/green](../typed-output-20261105/) uses the identical 256-case
  synthetic probe. The old worker wrongly approved bool outputs for int gold;
  the fixed worker rejects the candidate while preserving normal completion.
- [Durable evaluation](../durable-evaluation-20261105/) covers one persistent
  ledger, all registered callbacks, concurrency and retained crash outcomes.
  New databases, complete rollback and semantic provenance fraud remain outside it.
- [Identifier liveness](../identifier-liveness-20261105/) includes original and
  repaired authority probes plus exact-source x230 Rust execution. Its three new
  Rust checks and 1,600-line transition comparison are a native subset only.
- [Whole-authority rollback](../authority-rollback-20261105/observation.json)
  still reproduces stale-owner/revoked-source acceptance after complete restore.
  `guard_qualified=false`; successful observation is not successful protection.
- [Historical routing availability](../routing-diagnostics-20261105/historical-availability.json)
  remains unavailable for 42 method/seed groups. Missing traces are not invented.

Local `just fmt` is unavailable in this partial checkout (exit 127); native
Rust 1.95.0 formatting/compilation was performed separately on x230. No whole-repo
build or required CI completion is claimed. The remote PR checks must be assessed
against their actual head SHA, not these local source hashes alone.

## Current user request (verbatim)

```text
全量冲请研究 Hepta Neuron 如何分化成不同类型的 Memory Cell，使小模型在单节点专门压缩、存储、检索并更新某类记忆，再通过 split/merge、跨节点路由和持久迁移组成 Meta Network；明确该方案与 MoE 的专家专用性、路由、共享状态和权限的相同与不同，以及小设备获得大规模能力的真正条件。比较共享 Encoder + 专属 Head、KV/retrieval、ridge/centroid、Transformer/LoRA 参数记忆、类型化记忆和候选覆盖/专家内评分/跨专家路由。

实现可回滚的模型及记忆版本、唯一 owner、跨节点身份与证据、故障恢复和负迁移拒绝；对相同输入记忆、同预算、同执行器与完整存储/推理/训练成本评估准确率、长期稳定性和净收益。不得因参数化记忆更复杂或 Meta Network 节点数增加就推断整体智能或产品收益已提升。全量冲剩余blocker，直到所有blocker全部闭合
```
